"""
MAPNAI — scripts/replay_hotness.py
Replay hotness over stored articles (continousexplanation.md §10): step through time (default every 15 minutes) and
score every story as the hotness job would have at that moment, using only what was known then (articles published,
sightings recorded, front-page items seen up to t). Prints, per day, how many stories reached each tier, and every
breaking story with how long after its first report it was flagged. Read-only: nothing is written.

    python scripts/replay_hotness.py --days 3
    python scripts/replay_hotness.py --start 2026-11-10 --end 2026-11-12 --step 10 --csv data/replay.csv
    python scripts/replay_hotness.py --days 7 --breaking-h 0.6        # try another threshold

Note: social counts are not replayed, and prominence only covers the last 3 days (its TTL).
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from personalization import hotness as hot                      # noqa: E402
from personalization.scoring import parse_ts                    # noqa: E402


def as_of(members: Sequence[Dict], t: datetime) -> List[Dict]:
    """The members (and their sightings) known at time t."""
    out = []
    for m in members:
        if (parse_ts(m.get("published")) or parse_ts(m.get("ingested")) or t) > t:
            continue
        sightings = [s for s in m.get("sightings") or [] if (parse_ts(s.get("at")) or t) <= t]
        out.append({**m, "sightings": sightings})
    return out


def prominence_at(rows: Iterable[Dict], t: datetime, window_h: float) -> List[Dict]:
    """Front-page items on a page at some point in (t − window, t]."""
    lo = t - timedelta(hours=window_h)
    return [r for r in rows
            if (parse_ts(r.get("first_seen_at")) or t) <= t and (parse_ts(r.get("last_seen_at")) or t) >= lo]


def replay_story(members: Sequence[Dict], prominence_rows: Sequence[Dict], times: Sequence[datetime], cfg) -> List[Dict]:
    """[{t, score, tier, outlets}] at every step where the story existed."""
    out = []
    for t in times:
        known = as_of(members, t)
        if not known:
            continue
        index = hot.ProminenceIndex(prominence_at(prominence_rows, t, cfg.hot_prominence_window_h),
                                    cfg.hot_prominence_jaccard)
        h = hot.hotness(known, t, cfg, index)
        out.append({"t": t, "score": h["score"], "tier": h["tier"], "outlets": h["outlets"],
                    "first_seen": h["first_seen"], "domain": h["domain"]})
    return out


def summarize(timelines: Dict[str, List[Dict]], titles: Dict[str, str]) -> Dict:
    """Per day: stories that reached trending / breaking; every breaking story with its detection lag."""
    per_day: Dict[str, Dict[str, set]] = defaultdict(lambda: {"trending": set(), "breaking": set()})
    breaking = []
    for cid, rows in timelines.items():
        first_break = None
        for r in rows:
            if r["tier"] in ("trending", "breaking"):
                per_day[r["t"].date().isoformat()][r["tier"]].add(cid)
            if r["tier"] == "breaking" and first_break is None:
                first_break = r
        if first_break is not None:
            lag = (first_break["t"] - first_break["first_seen"]).total_seconds() / 60
            breaking.append({"cluster_id": cid, "title": titles.get(cid, ""), "flagged_at": first_break["t"],
                             "minutes_after_first_report": round(lag), "outlets": first_break["outlets"],
                             "domain": first_break["domain"]})
    days = {d: {"trending": len(v["trending"] - v["breaking"]), "breaking": len(v["breaking"])}
            for d, v in sorted(per_day.items())}
    return {"days": days, "breaking": sorted(breaking, key=lambda b: b["flagged_at"])}


def steps(start: datetime, end: datetime, minutes: int) -> List[datetime]:
    out, t = [], start
    while t <= end:
        out.append(t)
        t += timedelta(minutes=minutes)
    return out


def load(start: datetime, end: datetime, cfg):
    """Stories with an article published in [start − 1 day, end] → ({cluster: members}, prominence rows, titles)."""
    from storage.mongo_store import MongoStore
    db = MongoStore().db
    lo = (start - timedelta(days=1)).date().isoformat()
    fields = {"_id": 0, cfg.id_field: 1, cfg.source_field: 1, cfg.published_field: 1, "ingested_at": 1,
              cfg.title_field: 1, cfg.url_field: 1, "cluster_id": 1, "sightings": 1, cfg.risk_field: 1,
              "urgency_flag": 1, cfg.topic_field: 1}
    stories: Dict[str, List[Dict]] = defaultdict(list)
    titles: Dict[str, str] = {}
    for d in db[cfg.articles_collection].find({cfg.published_field: {"$gte": lo}}, fields):
        ts = parse_ts(d.get(cfg.published_field))
        if ts is None or ts > end:
            continue
        cid = d.get("cluster_id") or d[cfg.id_field]
        stories[cid].append({"article_id": d[cfg.id_field], "source": d.get(cfg.source_field),
                             "published": d.get(cfg.published_field), "ingested": d.get("ingested_at"),
                             "url": d.get(cfg.url_field), "title": d.get(cfg.title_field),
                             "sightings": d.get("sightings"), "risk_score": d.get(cfg.risk_field),
                             "urgency_flag": d.get("urgency_flag"), "domain": d.get(cfg.topic_field)})
        titles.setdefault(cid, d.get(cfg.title_field) or "")
    prominence = list(db[cfg.prominence_collection].find({}, {"_id": 0}))
    return stories, prominence, titles


def main(argv=None) -> int:
    from config.personalization import pers_settings
    p = argparse.ArgumentParser(description="Replay hotness over stored articles")
    p.add_argument("--days", type=float, default=1.0, help="replay the last N days (ignored with --start)")
    p.add_argument("--start", help="ISO date/time (UTC)")
    p.add_argument("--end", help="ISO date/time (UTC); default now")
    p.add_argument("--step", type=int, default=15, help="minutes between steps")
    p.add_argument("--breaking-h", type=float, default=None, help="override PERS_HOT_BREAKING_H")
    p.add_argument("--trending-h", type=float, default=None, help="override PERS_HOT_TRENDING_H")
    p.add_argument("--csv", help="write every (story, step) row to this CSV")
    args = p.parse_args(argv)

    update = {k: v for k, v in (("hot_breaking_h", args.breaking_h), ("hot_trending_h", args.trending_h))
              if v is not None}
    cfg = pers_settings.model_copy(update=update) if update else pers_settings
    end = parse_ts(args.end) if args.end else datetime.now(timezone.utc)
    start = parse_ts(args.start) if args.start else end - timedelta(days=args.days)
    times = steps(start, end, args.step)

    stories, prominence, titles = load(start, end, cfg)
    timelines = {cid: replay_story(members, prominence, times, cfg) for cid, members in stories.items()}
    timelines = {cid: rows for cid, rows in timelines.items() if rows}
    out = summarize(timelines, titles)

    print(f"Replayed {len(timelines)} stories, {len(times)} steps of {args.step} min, {start:%Y-%m-%d %H:%M} → "
          f"{end:%Y-%m-%d %H:%M} UTC (breaking ≥ {cfg.hot_breaking_h}, trending ≥ {cfg.hot_trending_h})\n")
    print(f"{'day':<12}{'trending':>10}{'breaking':>10}")
    for day, n in out["days"].items():
        print(f"{day:<12}{n['trending']:>10}{n['breaking']:>10}")
    if out["breaking"]:
        print("\nBreaking stories (flagged at, minutes after the first report, outlets then):")
        for b in out["breaking"]:
            print(f"  {b['flagged_at']:%m-%d %H:%M}  +{b['minutes_after_first_report']:>4} min  "
                  f"{b['outlets']:>3} outlets  [{b['domain']}] {b['title'][:80]}")
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["cluster_id", "t", "score", "tier", "outlets", "domain", "title"])
            for cid, rows in timelines.items():
                for r in rows:
                    w.writerow([cid, r["t"].isoformat(), r["score"], r["tier"], r["outlets"], r["domain"],
                                titles.get(cid, "")])
        print(f"\nWrote {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
