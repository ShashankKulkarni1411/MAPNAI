"""
MAPNAI — personalization/metrics.py
Aggregations behind GET /v1/admin/metrics: serving, engagement per section, must_know precision / miss rate and τ,
digest stats (unscored share, explore skips, hop contribution — risks R1/R2), proposals, alerts, render fallbacks
(R10), the article window (clustering and materiality) and job runs.

Each block reads one collection over [now − days, now] and counts in Python: the windows are small (one row per
impression / feedback event), and plain finds behave the same on MongoDB and mongomock.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from personalization.scoring import parse_ts

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
SECTIONS = ("must_know", "for_you", "explore", "more_you_need")


def rate(num: float, den: float) -> Optional[float]:
    """num / den rounded to 4 places; None when there is no denominator."""
    return round(num / den, 4) if den else None


def summary(values: Iterable[float]) -> Optional[Dict]:
    """{n, mean, p50, p90, max} of the non-null values; None when there are none."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None

    def pct(p: float) -> float:
        return round(xs[min(len(xs) - 1, int(p * len(xs)))], 4)

    return {"n": len(xs), "mean": round(sum(xs) / len(xs), 4), "p50": pct(0.5), "p90": pct(0.9),
            "max": round(xs[-1], 4)}


def serving(impressions: List[Dict]) -> Dict:
    digests = {i.get("digest_id") for i in impressions}
    by_section = Counter(i.get("section") for i in impressions)
    return {
        "digests_served": len(digests),
        "impressions": len(impressions),
        "users": len({i.get("user_id") for i in impressions}),
        "by_section": {s: by_section.get(s, 0) for s in SECTIONS},
        "items_per_digest": rate(len(impressions), len(digests)),
        "explore_propensity": summary(i.get("propensity") for i in impressions if i.get("section") == "explore"),
    }


def engagement(feedback: List[Dict], impressions: List[Dict], read_types: List[str]) -> Dict:
    """Feedback counts per type, and per section the share of served items that got a read event (open/more/…)."""
    by_type = Counter(f.get("type") for f in feedback)
    served = defaultdict(set)
    for i in impressions:
        served[i.get("section")].add((i.get("user_id"), i.get("article_id")))
    read = defaultdict(set)
    for f in feedback:
        if f.get("type") in read_types:
            read[f.get("section")].add((f.get("user_id"), f.get("article_id")))
    return {
        "events": len(feedback),
        "users": len({f.get("user_id") for f in feedback}),
        "by_type": dict(sorted(by_type.items())),
        # (user, article) pairs served in the section that were also read from it, over pairs served
        "read_rate_by_section": {s: rate(len(read[s] & served[s]), len(served[s])) for s in SECTIONS},
        "less_rate": rate(by_type.get("less", 0), len(impressions)),
    }


def must_know(feedback: List[Dict], tau_rows: List[Dict], current_tau: float) -> Dict:
    by_type = Counter(f.get("type") for f in feedback)
    needed, not_needed, missed = by_type.get("needed", 0), by_type.get("not_needed", 0), by_type.get("missed", 0)
    return {
        "needed": needed, "not_needed": not_needed, "missed": missed,
        "precision": rate(needed, needed + not_needed),          # of the must_know items judged, how many were needed
        "miss_rate": rate(missed, missed + needed),               # the quantity the τ job steers to miss_target
        "tau": current_tau,
        "tau_history": [{"t": r.get("t"), "tau": r.get("tau"), "prev_tau": r.get("prev_tau"),
                         "miss_rate": r.get("miss_rate")} for r in tau_rows],
    }


def digest_stats(digests: List[Dict]) -> Dict:
    stats = [d.get("stats") or {} for d in digests]
    return {
        "computed": len(digests),
        "unscored_share": summary(s.get("unscored_share") for s in stats),
        "explore_skipped_rate": rate(sum(1 for s in stats if s.get("explore_skipped")), len(stats)),
        "must_know_per_digest": summary(s.get("must_know") for s in stats),
        "hop_need_items": sum(s.get("hop_need_items") or 0 for s in stats),     # R1: hop paths rarely clear τ
        "max_hop_need": max((s.get("max_hop_need") or 0.0 for s in stats), default=None),
        "vector_coverage": summary(s.get("vector_coverage") for s in stats),
    }


def proposals(rows: List[Dict]) -> Dict:
    status = Counter(r.get("status") for r in rows)
    decided = status.get("accepted", 0) + status.get("rejected", 0)
    return {"created": len(rows), "by_status": dict(sorted(status.items())),
            "by_reason": dict(sorted(Counter(r.get("reason") for r in rows).items())),
            "acceptance_rate": rate(status.get("accepted", 0), decided)}


def alerts(rows: List[Dict], now: datetime) -> Dict:
    pending = sum(1 for r in rows if (t := parse_ts(r.get("deliver_after"))) and t > now)
    return {"created": len(rows), "users": len({r.get("user_id") for r in rows}), "pending_quiet_hours": pending,
            "deferred": sum(1 for r in rows if r.get("deferred")),
            "need": summary(r.get("need") for r in rows), "m": summary(r.get("m") for r in rows)}


def render(rows: List[Dict]) -> Dict:
    fallbacks = [r for r in rows if r.get("fallback")]
    return {"rewrites": len(rows), "fallback_share": rate(len(fallbacks), len(rows)),
            "fallback_reasons": dict(Counter(r.get("reason") for r in fallbacks).most_common()),
            "models": dict(Counter(r.get("model") for r in rows).most_common())}


def articles(docs: List[Dict], hours: int) -> Dict:
    """The candidate window: how much of it is clustered, scored by A4 (R2) and how material it is."""
    mats = [d.get("materiality") or {} for d in docs]
    sizes = Counter(d.get("cluster_id") for d in docs if d.get("cluster_id"))
    return {
        "window_h": hours, "articles": len(docs),
        "clustered_share": rate(sum(sizes.values()), len(docs)),
        "clusters": len(sizes), "multi_article_clusters": sum(1 for n in sizes.values() if n > 1),
        "with_materiality": sum(1 for m in mats if "m" in m),
        "unscored_share": rate(sum(1 for m in mats if m.get("unscored")), sum(1 for m in mats if "m" in m)),
        "m": summary(m.get("m") for m in mats),
    }


def jobs(runs: List[Dict]) -> Dict:
    out: Dict[str, Dict] = {}
    for r in sorted(runs, key=lambda r: parse_ts(r.get("started_at")) or _EPOCH):
        j = out.setdefault(r["job"], {"runs": 0, "failed": 0, "last_started": None, "last_ok": None,
                                      "last_error": None})
        j["runs"] += 1
        j["failed"] += r.get("ok") is False
        j["last_started"], j["last_ok"], j["last_error"] = r.get("started_at"), r.get("ok"), r.get("error")
    return dict(sorted(out.items()))


def collect(db, cfg, now: datetime, days: int, window_docs: List[Dict], current_tau: float,
            personas: int) -> Dict:
    """Every block over the last `days` days. window_docs: the article window (PersArticleStore.window)."""
    since = now - timedelta(days=days)

    def recent(collection: str, field: str, projection: Optional[Dict] = None) -> List[Dict]:
        return list(db[collection].find({field: {"$gte": since}}, {"_id": 0, **(projection or {})}))

    imp = recent(cfg.impressions_collection, "t", {"interest_parts": 0, "m_parts": 0})
    fb = recent(cfg.feedback_collection, "t")
    tau_rows = list(db[cfg.thresholds_collection].find({"t": {"$gte": since}}, {"_id": 0}).sort("t", -1).limit(10))
    return {
        "window": {"days": days, "since": since, "until": now},
        "users": {"personas": personas, "served": len({i.get("user_id") for i in imp}),
                  "gave_feedback": len({f.get("user_id") for f in fb})},
        "serving": serving(imp),
        "engagement": engagement(fb, imp, cfg.read_feedback_types),
        "must_know": must_know(fb, tau_rows, current_tau),
        "digests": digest_stats(recent(cfg.digests_collection, "generated_at", {"items": 0, "more_you_need": 0})),
        "proposals": proposals(recent(cfg.proposals_collection, "created_at")),
        "alerts": alerts(recent(cfg.alerts_collection, "created_at", {"path": 0, "m_parts": 0}), now),
        "render": render(recent(cfg.render_cache_collection, "created_at", {"text": 0, "rewrite": 0})),
        "articles": articles(window_docs, cfg.cand_window_h),
        "jobs": jobs(recent(cfg.job_runs_collection, "started_at", {"stats": 0})),
    }
