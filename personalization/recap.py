"""
MAPNAI — personalization/recap.py
Daily and weekly recaps (pure: no DB, no clock). The same recap for every reader of a time zone; the service adds
the per-reader marks ("you follow", "you read this") when it serves one.

  periods    daily  = one local calendar day [00:00, 24:00), ready the next day at recap_daily_ready, so articles
                      ingested overnight still count
             weekly = Monday to Sunday, cut at recap_week_end on Sunday: [Sunday before 22:00, Sunday 22:00).
                      News after the cut opens the next week; the hours before Monday are folded into Monday
  times      an article's time is published_ts (published_at, else its ingestion time). An undated article
             ("ingested") takes the earliest time of a dated sibling up to recap_undated_lookback_h earlier: the
             same cluster, or shared entities with a title Jaccard ≥ title_jaccard_min
  stories    one per cluster; near-identical clusters of a topic (title Jaccard ≥ recap_dup_title_jaccard) merge.
             A story's m is its best article's materiality m (computed on the spot for an article the clustering
             job hasn't reached, flagged m_fallback), its lead that article (earliest on a tie)
  daily      the recap_domains stories with m ≥ recap_min_m, recap_daily_min_per_domain per domain first, then
             the rest by m, recap_daily_size in all, ranked by m
  weekly     "Stories of the week": the recap_weekly_top best by m + recap_span_bonus · (days run − 1), at least
             recap_weekly_top_min_per_domain per domain; then per day (the day the story broke) the best story
             and a second one when its m ≥ recap_weekly_second_min_m (the other domain preferred), at most
             recap_weekly_max in all
  overview   2-3 sentences an LLM writes from the selected titles and summaries only; it is dropped when it
             brings in a number the sources don't have (personalization/factcheck.py)
"""

import json
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

from personalization import clustering, factcheck, materiality
from personalization.scoring import parse_ts

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")
DATED = ("published", "page_meta")
DUP_MIN_TOKENS = 3


# ── Periods ──────────────────────────────────────────────────

def hhmm(value: str) -> time:
    m = _HHMM.match(value or "")
    if not m:
        raise ValueError(f"expected HH:MM, got {value!r}")
    return time(int(m.group(1)), int(m.group(2)))


def _at(day: date, t: time, z: ZoneInfo) -> datetime:
    return datetime.combine(day, t, tzinfo=z).astimezone(timezone.utc)


def parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"expected YYYY-MM-DD, got {value!r}")


def week_key(monday: date) -> str:
    year, week, _ = monday.isocalendar()
    return f"{year}-W{week:02d}"


def parse_week(value: str) -> date:
    """"2026-W43" → that ISO week's Monday."""
    m = _WEEK.match(value or "")
    if not m:
        raise ValueError(f"expected YYYY-Www, got {value!r}")
    try:
        return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        raise ValueError(f"no such week {value!r}")


def latest_daily(now: datetime, z: ZoneInfo, cfg) -> date:
    """The newest day with a recap: yesterday once recap_daily_ready has passed today, else the day before."""
    local = now.astimezone(z)
    yesterday = local.date() - timedelta(days=1)
    return yesterday if local.time() >= hhmm(cfg.recap_daily_ready) else yesterday - timedelta(days=1)


def latest_weekly(now: datetime, z: ZoneInfo, cfg) -> date:
    """Monday of the newest week with a recap: the last Sunday whose recap_week_end has passed."""
    local = now.astimezone(z)
    sunday = local.date() - timedelta(days=(local.weekday() + 1) % 7)
    if local < datetime.combine(sunday, hhmm(cfg.recap_week_end), tzinfo=z):
        sunday -= timedelta(days=7)
    return sunday - timedelta(days=6)


def daily_period(day: date, z: ZoneInfo, cfg) -> Dict:
    """{kind, key, start, end (UTC), days, title, ready_at}."""
    return {"kind": "daily", "key": day.isoformat(), "start": _at(day, time(0), z),
            "end": _at(day + timedelta(days=1), time(0), z), "days": [day],
            "title": f"{day:%A}, {day.day} {day:%B}",
            "ready_at": _at(day + timedelta(days=1), hhmm(cfg.recap_daily_ready), z)}


def weekly_period(monday: date, z: ZoneInfo, cfg) -> Dict:
    cut = hhmm(cfg.recap_week_end)
    sunday = monday + timedelta(days=6)
    first = f"{monday.day} {monday:%B}" if monday.month != sunday.month else str(monday.day)
    return {"kind": "weekly", "key": week_key(monday), "start": _at(monday - timedelta(days=1), cut, z),
            "end": _at(sunday, cut, z), "days": [monday + timedelta(days=i) for i in range(7)],
            "title": f"{first}–{sunday.day} {sunday:%B}", "ready_at": _at(sunday, cut, z)}


def day_of(t: datetime, z: ZoneInfo, period: Dict) -> date:
    """The local day a time falls on, clamped into the period's days (the Sunday-night hours → Monday)."""
    return min(max(t.astimezone(z).date(), period["days"][0]), period["days"][-1])


# ── Article times ────────────────────────────────────────────

def _raw_time(doc: Dict) -> Optional[datetime]:
    for field in ("published_ts", "published_at", "ingested_ts", "ingested_at"):
        ts = parse_ts(doc.get(field))
        if ts:
            return ts
    return None


def date_source(doc: Dict) -> str:
    return doc.get("date_source") or ("published" if doc.get("published_at") else "ingested")


def effective_times(docs: Sequence[Dict], cfg) -> Dict[str, Tuple[datetime, str]]:
    """
    {article_id: (time, source)}: source is the doc's date_source, or "sibling" when an undated article took a
    dated sibling's earlier time. Articles with no usable time at all are left out.
    """
    c = cfg
    out: Dict[str, Tuple[datetime, str]] = {}
    dated: List[Dict] = []
    for d in docs:
        ts = _raw_time(d)
        if ts is None:
            continue
        out[d[c.id_field]] = (ts, date_source(d))
        if date_source(d) in DATED:
            dated.append(d)
    lookback = timedelta(hours=c.recap_undated_lookback_h)
    meta = {d[c.id_field]: {"title": d.get(c.title_field) or "", "entity_keys": d.get("entity_keys") or []}
            for d in docs}
    for d in docs:
        a = d[c.id_field]
        if a not in out or out[a][1] in DATED:
            continue
        own = out[a][0]
        best = None
        for s in dated:
            t = out[s[c.id_field]][0]
            if not (own - lookback <= t < own):
                continue
            same = bool(d.get("cluster_id")) and d.get("cluster_id") == s.get("cluster_id")
            if not same:
                ev = clustering.evidence(meta[a], meta[s[c.id_field]], c)
                same = bool(ev["entities"]) and ev["jaccard"] >= c.title_jaccard_min
            if same and (best is None or t < best):
                best = t
        if best is not None:
            out[a] = (best, "sibling")
    return out


# ── Stories ──────────────────────────────────────────────────

def article_m(doc: Dict, cfg) -> Tuple[float, bool]:
    """(materiality m, computed here) — the clustering job's m, else a lone-article m from the doc's own fields."""
    m = (doc.get("materiality") or {}).get("m")
    if m is not None:
        return float(m), False
    return float(materiality.materiality(doc, doc.get("cluster_size") or 1, False, cfg)["m"]), True


def build_stories(docs: Sequence[Dict], times: Dict[str, Tuple[datetime, str]], cfg) -> List[Dict]:
    """
    Cluster the period's articles into stories (docs: only those inside the period). Each story:
    {story_id, lead (doc), member_ids, topic, m, m_fallback, size, first_t, times, date_source}, best m first.
    """
    c = cfg
    groups: Dict[str, List[Dict]] = {}
    for d in docs:
        if d[c.id_field] in times:
            groups.setdefault(d.get("cluster_id") or d[c.id_field], []).append(d)

    stories = []
    for sid, members in groups.items():
        scored = [(article_m(d, c), times[d[c.id_field]][0], d) for d in members]
        (m, fallback), _, lead = min(scored, key=lambda x: (-x[0][0], x[1], x[2][c.id_field]))
        stories.append({
            "story_id": sid, "lead": lead, "member_ids": sorted(d[c.id_field] for d in members),
            "topic": lead.get(c.topic_field), "m": round(m, 6), "m_fallback": fallback,
            "size": max([len(members)] + [int(d.get("cluster_size") or 1) for d in members]),
            "first_t": min(t for _, t, _ in scored), "times": sorted(t for _, t, _ in scored),
            "date_source": times[lead[c.id_field]][1],
        })
    stories.sort(key=lambda s: (-s["m"], s["first_t"], s["story_id"]))

    # near-identical clusters of one topic are one story (clusters are never merged by the clustering job);
    # titles under DUP_MIN_TOKENS content words say too little to call two stories the same
    merged: List[Dict] = []
    tokens: List[set] = []
    for s in stories:
        toks = clustering.title_tokens(s["lead"].get(c.title_field) or "")
        twin = next((i for i, t in enumerate(tokens) if merged[i]["topic"] == s["topic"]
                     and min(len(toks), len(t)) >= DUP_MIN_TOKENS
                     and len(toks & t) / len(toks | t) >= c.recap_dup_title_jaccard), None)
        if twin is None:
            merged.append(s)
            tokens.append(toks)
            continue
        keep = merged[twin]
        keep["member_ids"] = sorted(set(keep["member_ids"]) | set(s["member_ids"]))
        keep["size"] += s["size"]
        keep["first_t"] = min(keep["first_t"], s["first_t"])
        keep["times"] = sorted(keep["times"] + s["times"])
    return merged


def drop_excluded(stories: List[Dict], excluded: Iterable[str]) -> List[Dict]:
    """Stories without any excluded article (an editor's removal takes the whole story out)."""
    gone = set(excluded or ())
    return [s for s in stories if not gone & set(s["member_ids"])]


def _pinned(stories: Sequence[Dict], pinned: Iterable[str]) -> List[Dict]:
    want = list(dict.fromkeys(pinned or ()))
    return [s for a in want for s in stories if a in s["member_ids"]]


def _balanced(ranked: Sequence[Dict], n: int, min_per: int, domains: Sequence[str],
              forced: Sequence[Dict] = ()) -> List[Dict]:
    """forced first, then min_per of each domain, then the rest in rank order; n in all, in rank order."""
    picks = list(dict.fromkeys(id(s) for s in forced))
    by_id = {id(s): s for s in list(forced) + list(ranked)}
    for d in domains:
        have = sum(1 for p in picks if by_id[p]["topic"] == d)
        for s in ranked:
            if have >= min_per:
                break
            if s["topic"] == d and id(s) not in picks:
                picks.append(id(s))
                have += 1
    for s in ranked:
        if len(picks) >= n:
            break
        if id(s) not in picks:
            picks.append(id(s))
    order = {id(s): i for i, s in enumerate(ranked)}
    chosen = [by_id[p] for p in picks[:max(n, len(forced))]]
    return sorted(chosen, key=lambda s: (s not in forced, order.get(id(s), -1)))


def eligible(stories: Sequence[Dict], cfg) -> List[Dict]:
    return [s for s in stories if s["topic"] in cfg.recap_domains and s["m"] >= cfg.recap_min_m]


def select_daily(stories: Sequence[Dict], cfg, pinned: Iterable[str] = ()) -> List[Dict]:
    """[{**story, rank, group: "day", score}] in rank order."""
    ranked = eligible(stories, cfg)
    forced = _pinned(stories, pinned)
    picks = _balanced(ranked, cfg.recap_daily_size, cfg.recap_daily_min_per_domain, cfg.recap_domains, forced)
    return [{**s, "rank": i, "group": "day", "score": s["m"]} for i, s in enumerate(picks, start=1)]


def span_days(story: Dict, z: ZoneInfo, period: Dict) -> int:
    return len({day_of(t, z, period) for t in story["times"]})


def select_weekly(stories: Sequence[Dict], z: ZoneInfo, period: Dict, cfg,
                  pinned: Iterable[str] = ()) -> List[Dict]:
    """
    [{**story, rank, group: "top" | "YYYY-MM-DD", score, span_days}]: the top section first, then the days in
    order. Pinned stories go into the top section.
    """
    c = cfg
    pool = []
    for s in stories:
        n = span_days(s, z, period)
        pool.append({**s, "span_days": n, "score": round(s["m"] + c.recap_span_bonus * (n - 1), 6)})
    ranked = sorted(eligible(pool, c), key=lambda s: (-s["score"], s["first_t"], s["story_id"]))
    forced = _pinned(pool, pinned)
    top = _balanced(ranked, c.recap_weekly_top, c.recap_weekly_top_min_per_domain, c.recap_domains, forced)
    taken = {s["story_id"] for s in top}

    by_m = sorted(eligible(pool, c), key=lambda s: (-s["m"], s["first_t"], s["story_id"]))
    days: List[Tuple[date, List[Dict]]] = []
    for day in period["days"]:
        cands = [s for s in by_m if s["story_id"] not in taken and day_of(s["first_t"], z, period) == day]
        if not cands:
            continue
        picks = [cands[0]]
        rest = [s for s in cands[1:] if s["m"] >= c.recap_weekly_second_min_m]
        rest.sort(key=lambda s: s["topic"] == picks[0]["topic"])       # stable: the other domain first
        picks += rest[: max(0, c.recap_weekly_per_day - 1)]
        days.append((day, picks))

    # over the cap: drop the weakest day items (a day's first story last)
    room = max(0, c.recap_weekly_max - len(top))
    day_items = [(day, i, s) for day, picks in days for i, s in enumerate(picks)]
    if len(day_items) > room:
        keep = sorted(day_items, key=lambda x: (x[1], -x[2]["m"]))[:room]
        kept = {(d, s["story_id"]) for d, _, s in keep}
        day_items = [x for x in day_items if (x[0], x[2]["story_id"]) in kept]

    out = [{**s, "group": "top"} for s in top]
    out += [{**s, "group": day.isoformat()} for day, _, s in day_items]
    return [{**s, "rank": i} for i, s in enumerate(out, start=1)]


def sections(kind: str, items: Sequence[Dict], period: Dict) -> List[Dict]:
    """[{key, title, count}] in display order, empty groups left out."""
    counts: Dict[str, int] = {}
    for i in items:
        counts[i["group"]] = counts.get(i["group"], 0) + 1
    if kind == "daily":
        return [{"key": "day", "title": period["title"], "count": counts.get("day", 0)}] if counts else []
    out = [{"key": "top", "title": "Stories of the week", "count": counts["top"]}] if counts.get("top") else []
    for day in period["days"]:
        if counts.get(day.isoformat()):
            out.append({"key": day.isoformat(), "title": f"{day:%A} {day.day} {day:%b}",
                        "count": counts[day.isoformat()]})
    return out


def coverage(docs: Sequence[Dict], times: Dict[str, Tuple[datetime, str]], stories: Sequence[Dict], cfg) -> Dict:
    """In-scope article counts for the period, and whether there were too few to trust (`limited`)."""
    c = cfg
    in_scope = [d for d in docs if d.get(c.topic_field) in c.recap_domains and d[c.id_field] in times]
    by_domain = {dom: sum(1 for d in in_scope if d.get(c.topic_field) == dom) for dom in c.recap_domains}
    by_source: Dict[str, int] = {}
    for d in in_scope:
        src = times[d[c.id_field]][1]
        by_source[src] = by_source.get(src, 0) + 1
    return {"articles": len(in_scope), "by_domain": by_domain, "date_sources": by_source,
            "stories": sum(1 for s in stories if s["topic"] in c.recap_domains),
            "eligible": len(eligible(stories, c)), "limited": len(in_scope) < c.recap_low_coverage}


def story_explanation(item: Dict, kind: str) -> str:
    n = item.get("size") or 1
    if n > 1:
        return f"Covered by {n} sources"
    return "One of the day's biggest stories" if kind == "daily" else "One of the week's biggest stories"


# ── Overview ─────────────────────────────────────────────────

OVERVIEW_PROMPT = """You write the opening of a news recap: {what}.

RULES
1. 2-3 sentences, at most 70 words, plain everyday language.
2. Use only the stories below. Add nothing that is not in them: no new facts, numbers, names, background,
   opinions or speculation.
3. Keep numbers and names exactly as written. Mention the biggest stories first; cover more than one topic when
   the stories do.
4. Return only a JSON object: {{"text": "<the overview>"}}"""

TOPIC_WORDS = {"sports": "Sports", "entertainment_movies": "Film"}


def overview_source(items: Sequence[Dict], cfg) -> str:
    """The stories as the model sees them: "1. [Sports] title — summary" lines."""
    lines = []
    for i in items:
        summary = (i.get("summary_short") or i.get("summary_long") or "").strip()
        if len(summary) > cfg.recap_overview_source_chars:
            summary = summary[: cfg.recap_overview_source_chars].rsplit(" ", 1)[0] + "…"
        topic = TOPIC_WORDS.get(i.get("topic"), "News")
        lines.append(f"{i['rank']}. [{topic}] {i.get('title') or ''}" + (f" — {summary}" if summary else ""))
    return "\n".join(lines)


def overview_messages(kind: str, title: str, source: str) -> List[Dict[str, str]]:
    what = f"the biggest stories of {title}" if kind == "daily" else f"the biggest stories of the week {title}"
    return [{"role": "system", "content": OVERVIEW_PROMPT.format(what=what)},
            {"role": "user", "content": source}]


def overview_check(source: str, text: Optional[str]) -> Tuple[bool, List[str]]:
    """(ok, added numbers): the overview may leave facts out, but must not bring in a number."""
    if not text:
        return False, []
    _, _, added = factcheck.verify(source, text, [])
    return not added, added


def parse_overview(content: Optional[str]) -> Optional[str]:
    try:
        text = json.loads(content or "").get("text")
    except (ValueError, AttributeError):
        return None
    return text.strip() if isinstance(text, str) and text.strip() else None


def in_window(times: Dict[str, Tuple[datetime, str]], period: Dict, carry: Set[str] = frozenset()) -> Set[str]:
    """Articles whose time falls inside the period, plus the carried-over ones."""
    return {a for a, (t, _) in times.items() if period["start"] <= t < period["end"] or a in carry}
