"""
Backfill Agent 4 risk scores for the personalization window, one Groq call per event cluster.

Scope: articles published in the last --window-h hours (default PERS_CLUSTER_WINDOW_H) with no risk_score.
Order: biggest clusters first. For each cluster, one representative is scored with Agent 4's own LLM call
(RiskScoringAgent._call_llm_risk, the same prompt and parsing the pipeline uses) and the result is written to
every unscored member with MongoStore.update_article_risk. Copies carry `risk_copied_from` (the representative's
article_id). A member that already has a score is copied to the rest of its cluster without a call.
Representative: a member with summary_short (A4's prompt uses it), then the cluster's first_report, then the
longest body.

Limits: at most --rpm calls per rolling minute and --daily-cap calls per UTC day, counted across runs in the
Mongo collection `a4_backfill_calls`. Resumable: scored articles are skipped, so rerunning continues where the
last run stopped (daily cap, Ctrl+C, or an LLM failure).
On an LLM failure (Agent 4 returns its fallback, e.g. HTTP 429) it waits 60 s and retries once, then stops.

    python scripts/backfill_a4.py --dry-run        # plan only: calls needed and duration, no Groq client
    python scripts/backfill_a4.py [--max-calls N] [--window-h 48] [--rpm 30] [--daily-cap 1000]
"""

import argparse
import math
import os
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.pipeline_bridge import mongo_doc_to_agent4_payload  # noqa: E402
from config.personalization import pers_settings  # noqa: E402
from personalization.scoring import parse_ts  # noqa: E402
from storage.mongo_store import MongoStore  # noqa: E402
from utils.logger import logger  # noqa: E402

LOG_COLLECTION = "a4_backfill_calls"


def plan(docs: List[Dict]) -> List[Dict]:
    """
    Group window articles by cluster, biggest first → [{cluster_id, size, missing: [doc], scored: doc|None,
    representative: doc|None}]. `representative` is None when a scored member can be copied instead.
    """
    clusters: Dict[str, List[Dict]] = {}
    for d in docs:
        clusters.setdefault(d.get("cluster_id") or d["article_id"], []).append(d)
    out = []
    for cid, members in clusters.items():
        missing = [d for d in members if d.get("risk_score") is None]
        if not missing:
            continue
        scored = next((d for d in members if d.get("risk_score") is not None), None)
        rep = None
        if scored is None:
            rep = sorted(missing, key=lambda d: (not d.get("summary_short"), d["article_id"] != d.get("first_report"),
                                                 -len(d.get("body") or ""), d["article_id"]))[0]
        out.append({"cluster_id": cid, "size": len(members), "missing": missing, "scored": scored,
                    "representative": rep,
                    "first_published": min(parse_ts(d.get("published_at")) or datetime.max.replace(
                        tzinfo=timezone.utc) for d in members)})
    out.sort(key=lambda p: (-p["size"], -p["first_published"].timestamp(), p["cluster_id"]))
    return out


class RateLimiter:
    """≤ rpm calls in any rolling 60 s, ≤ daily_cap calls per UTC day (persisted in Mongo)."""

    def __init__(self, log_col, rpm: int, daily_cap: int):
        self.log, self.rpm, self.daily_cap = log_col, rpm, daily_cap
        now = datetime.now(timezone.utc)
        self.recent = deque(d["t"].replace(tzinfo=timezone.utc) for d in
                            log_col.find({"t": {"$gte": now - timedelta(seconds=60)}}, {"_id": 0, "t": 1}))

    def calls_today(self) -> int:
        day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.log.count_documents({"t": {"$gte": day}})

    def wait(self) -> bool:
        """Block until a call is allowed. False when today's cap is used up."""
        if self.calls_today() >= self.daily_cap:
            return False
        while True:
            now = datetime.now(timezone.utc)
            while self.recent and (now - self.recent[0]).total_seconds() >= 60:
                self.recent.popleft()
            if len(self.recent) < self.rpm:
                return True
            time.sleep(60 - (now - self.recent[0]).total_seconds() + 0.05)

    def record(self, **fields) -> None:
        now = datetime.now(timezone.utc)
        self.recent.append(now)
        self.log.insert_one({"t": now, **fields})


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Agent 4 risk scores, one call per cluster")
    parser.add_argument("--window-h", type=int, default=pers_settings.cluster_window_h)
    parser.add_argument("--rpm", type=int, default=30)
    parser.add_argument("--daily-cap", type=int, default=1000)
    parser.add_argument("--max-calls", type=int, default=None, help="stop after N calls this run")
    parser.add_argument("--dry-run", action="store_true", help="print the plan; no Groq client, no writes")
    args = parser.parse_args()

    from storage.pers_article_store import PersArticleStore
    mongo = MongoStore()
    articles = PersArticleStore(mongo)
    now = datetime.now(timezone.utc)
    projection = {"_id": 0, "body": 1, "summary_short": 1, "summary_long": 1, "entities": 1, "domain": 1,
                  "category": 1, "sentiment_score": 1, "urgency_flag": 1, "classification_confidence": 1,
                  "taxonomy_version": 1, "article_id": 1, "title": 1, "source_name": 1, "published_at": 1,
                  "url": 1, "cluster_id": 1, "cluster_size": 1, "first_report": 1, "risk_score": 1,
                  "risk_processed": 1, "language": 1, "source_type": 1, "raw_source": 1}
    docs = articles.window(args.window_h, now, projection)
    steps = plan(docs)
    calls = sum(1 for s in steps if s["representative"] is not None)
    copies = sum(len(s["missing"]) for s in steps) - calls
    log_col = mongo.db[LOG_COLLECTION]
    limiter = RateLimiter(log_col, args.rpm, args.daily_cap)
    left_today = max(0, args.daily_cap - limiter.calls_today())
    days = 0 if calls == 0 else 1 if calls <= left_today else 1 + math.ceil((calls - left_today) / args.daily_cap)
    print(f"window {args.window_h}h: {len(docs)} articles, {sum(len(s['missing']) for s in steps)} unscored "
          f"in {len(steps)} clusters")
    print(f"calls needed: {calls} (one per cluster); scores copied to {copies} other members; "
          f"clusters copying an existing score: {sum(1 for s in steps if s['representative'] is None)}")
    print(f"representatives without summary_short: "
          f"{sum(1 for s in steps if s['representative'] is not None and not s['representative'].get('summary_short'))}")
    print(f"at {args.rpm}/min: ≥ {math.ceil(calls / args.rpm)} min of rate-limited time "
          f"(plus LLM latency); daily cap {args.daily_cap}, {left_today} left today → {days} day(s)")
    if args.dry_run:
        for s in steps[:10]:
            rep = s["representative"]
            print(f"  size {s['size']}: {(rep or s['scored'])['title'][:90]}"
                  f"{'' if rep else '  [copy existing score]'}")
        return 0

    from agents.agent4_risk_scorer import RiskScoringAgent
    agent = RiskScoringAgent(mongo_store=mongo)
    if not agent.client:
        print("Groq client unavailable (GROQ_API_KEY?); nothing done")
        return 1

    done = 0
    for s in steps:
        rep = s["representative"]
        if rep is None:
            source, result = s["scored"], {k: s["scored"].get(k) for k in
                                            ("risk_score", "risk_confidence", "risk_level", "risk_reasoning",
                                             "action_recommendation")}
        else:
            if args.max_calls is not None and done >= args.max_calls:
                print(f"--max-calls {args.max_calls} reached; rerun to continue")
                break
            if not limiter.wait():
                print(f"daily cap {args.daily_cap} reached; rerun tomorrow (UTC) to continue")
                break
            payload = mongo_doc_to_agent4_payload(rep)
            call = lambda: agent._call_llm_risk(  # noqa: E731
                payload.get("title", ""), payload.get("body", ""), payload.get("domain", "general"),
                payload.get("urgency_flag", False), payload.get("sentiment", 0.0),
                payload.get("summary_short", "") or "", payload.get("entities", []))
            result = call()
            limiter.record(article_id=rep["article_id"], cluster_id=s["cluster_id"],
                           ok=not result.get("_fallback"))
            if result.pop("_fallback", False):
                logger.warning("[A4 backfill] LLM call failed; retrying once in 60 s")
                time.sleep(60)
                if not limiter.wait():
                    break
                result = call()
                limiter.record(article_id=rep["article_id"], cluster_id=s["cluster_id"],
                               ok=not result.get("_fallback"))
                if result.pop("_fallback", False):
                    print("LLM still failing; stopped. Rerun later to continue.")
                    break
            source, done = rep, done + 1
        for member in s["missing"]:
            mongo.update_article_risk(member["article_id"], result)
            if member["article_id"] != source["article_id"]:
                mongo.db["processed_articles"].update_one(
                    {"article_id": member["article_id"]}, {"$set": {"risk_copied_from": source["article_id"]}})
        print(f"[{done}/{calls}] size {s['size']} risk {result.get('risk_score')} ({result.get('risk_level')}): "
              f"{source['title'][:80]}")
    print(f"calls made this run: {done}. Next `python -m personalization.jobs cluster` rescores materiality.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
