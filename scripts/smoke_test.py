"""
End-to-end smoke test of the personalization API against the live databases (PERSONALIZATION_PLAN.md §6 Phase 8).
Asserts status codes and response shapes for every endpoint, per demo persona, and prints each persona's digest
as `section | title | why`, then flags personas whose must_know sections overlap by more than 30%.

Per persona (from scripts/seed_demo_personas.py → data/demo_personas.json):
  read-only on the persona itself : profile, digest (fresh, then cached), render, alerts, proposals
  on a scratch clone "Smoke: …"   : POST /users, onboarding, PATCH exposures/topics/style/alert_prefs, digest,
                                    feedback × 8 types, then proposals accept/reject, alerts, render
Global: health, entity search, headlines, the six jobs through /v1/admin/jobs/{name}/run, metrics, error codes.

The clones and everything they logged are deleted at the end, and the τ row the tau job wrote during the run is
dropped, so the seeded personas and the live τ are unchanged (--keep skips the cleanup).

    python scripts/smoke_test.py                              # in-process (FastAPI TestClient, no server needed)
    python scripts/smoke_test.py --base-url http://127.0.0.1:8000   # against a running `python run_api.py`
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from personalization import candidates  # noqa: E402

IDS_FILE = os.path.join(ROOT, "data", "demo_personas.json")
OVERLAP_FLAG = 0.30
FEEDBACK_TYPES = ["open", "more", "less", "dwell", "save", "needed", "not_needed", "missed"]


class Smoke:
    """Calls endpoints, checks status + top-level keys, prints one line per call and keeps the tally."""

    def __init__(self, client, verbose: bool = True):
        self.client, self.verbose = client, verbose
        self.results = []
        self.short = {}                       # user_id → 8-char tag, for readable paths

    def _fmt(self, path: str) -> str:
        for full, tag in self.short.items():
            path = path.replace(full, tag)
        return path

    def call(self, method: str, path: str, expect: int = 200, keys=(), **kw):
        t0 = time.perf_counter()
        resp = self.client.request(method, path, **kw)
        ms = (time.perf_counter() - t0) * 1000
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        missing = [k for k in keys if not (isinstance(body, dict) and k in body)]
        ok = resp.status_code == expect and not missing
        self.results.append((method, path, resp.status_code, ok))
        mark = "ok " if ok else "FAIL"
        if self.verbose or not ok:
            print(f"  [{mark}] {resp.status_code} {method:<5} {self._fmt(path):<62} {ms:7.0f} ms")
        if not ok:
            why = f"want {expect}" + (f", missing keys {missing}" if missing else "")
            print(f"         {why}: {json.dumps(body, default=str)[:400]}")
        return body

    def check(self, label: str, cond: bool, detail: str = "") -> bool:
        self.results.append(("CHECK", label, None, bool(cond)))
        if self.verbose or not cond:
            print(f"  [{'ok ' if cond else 'FAIL'}] check {label}" + (f" ({detail})" if detail else ""))
        return bool(cond)


def cut(text, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def print_digest(name: str, digest: dict) -> None:
    items, more = digest.get("items") or [], digest.get("more_you_need") or []
    print(f"\n  Digest: {name} · τ={digest.get('tau')} · {len(items)} items + {len(more)} more_you_need"
          f" · cached={digest.get('cached')}")
    print(f"  {'section':<13} | {'title':<58} | why")
    print(f"  {'-' * 13}-+-{'-' * 58}-+-{'-' * 60}")
    for item in items + more:
        print(f"  {item['section']:<13} | {cut(item.get('title'), 58):<58} | {cut(item.get('why'), 120)}")


def story(item: dict) -> str:
    """The same event served from two different outlets counts once: compare clusters, not article ids."""
    return item.get("cluster_id") or item["article_id"]


def overlap_report(digests: dict, names: dict) -> list:
    """Pairwise must_know overlap = |A ∩ B| / min(|A|, |B|) over cluster ids (plus Jaccard for reference)."""
    sets = {slug: {story(i) for i in d.get("items") or [] if i["section"] == "must_know"} for slug, d in digests.items()}
    print("\n== must_know overlap (by cluster; overlap = |A∩B| / min(|A|,|B|), flagged above "
          f"{OVERLAP_FLAG:.0%})")
    for slug, s in sets.items():
        print(f"  {names[slug]:<44} must_know = {len(s)}")
    flagged = []
    for a, b in combinations(sets, 2):
        inter = sets[a] & sets[b]
        denom = min(len(sets[a]), len(sets[b]))
        ov = len(inter) / denom if denom else 0.0
        jac = len(inter) / len(sets[a] | sets[b]) if sets[a] | sets[b] else 0.0
        flag = ov > OVERLAP_FLAG
        print(f"  {'FLAG' if flag else 'ok  '} {names[a]}  ×  {names[b]}: shared {len(inter)}, overlap {ov:.0%}, "
              f"jaccard {jac:.0%}")
        if flag:
            flagged.append((a, b, ov, sorted(inter)))
    if not flagged:
        print(f"  No pair of personas shares more than {OVERLAP_FLAG:.0%} of its must_know stories.")
    return flagged


def probe_entity(svc, exclude: set, topics: set):
    """
    An entity the clone isn't exposed to that is among the top entities of ≥ proposal_min_articles window articles,
    so three `more` events on those articles meet the engagement-proposal rule. Prefers the persona's topics.
    """
    c = svc.cfg
    docs = svc.articles.window(c.cand_window_h, svc.clock(), projection={
        "_id": 0, c.id_field: 1, c.published_field: 1, c.topic_field: 1, "entity_keys": 1, c.entities_field: 1})
    aliases = svc.logs.alias_map()                 # "man city" is an exposure when "manchester city" is
    by_key = defaultdict(list)
    for d in docs:
        for k in candidates.doc_entity_keys(d, c)[: c.beta_top_entities]:
            by_key[k].append(d)
    ranked = sorted(((k, ds) for k, ds in by_key.items()
                     if aliases.get(k, k) not in exclude and len(ds) >= c.proposal_min_articles),
                    key=lambda kv: (-sum(d.get(c.topic_field) in topics for d in kv[1]), -len(kv[1]), kv[0]))
    for key, ds in ranked[:20]:
        if svc.exposures.resolve_key(key):
            return key, [d[c.id_field] for d in ds[: c.proposal_min_articles]]
    return None, []


def load_personas(svc) -> dict:
    if not os.path.exists(IDS_FILE):
        sys.exit(f"{os.path.relpath(IDS_FILE, ROOT)} not found: run `python scripts/seed_demo_personas.py` first")
    with open(IDS_FILE, encoding="utf-8") as fh:
        personas = json.load(fh)
    stale = [p["name"] for p in personas.values() if svc.personas.get(p["user_id"]) is None]
    if stale:
        sys.exit(f"demo personas missing from Mongo ({stale}): re-run scripts/seed_demo_personas.py")
    return personas


def persona_readonly(sm: Smoke, p: dict) -> dict:
    uid = p["user_id"]
    sm.call("GET", f"/v1/users/{uid}/profile", keys=("sentences", "exposures", "pi_topk", "persona_version"))
    digest = sm.call("GET", f"/v1/users/{uid}/digest", params={"refresh": "true"},
                     keys=("items", "more_you_need", "tau", "stats"))
    again = sm.call("GET", f"/v1/users/{uid}/digest", keys=("items", "cached"))
    sm.check("second digest GET is served from cache", isinstance(again, dict) and again.get("cached") is True)
    items = digest.get("items") or []
    sm.check("digest has items with section + why",
             bool(items) and all(i.get("section") and i.get("why") for i in items), f"{len(items)} items")
    if items:
        r = sm.call("GET", f"/v1/articles/{items[0]['article_id']}/render", params={"user_id": uid},
                    keys=("text", "why", "brief", "fallback", "cached"))
        if isinstance(r, dict) and "text" in r:
            print(f"         render: style={r.get('style')} fallback={r.get('fallback')} ({r.get('reason')}) "
                  f"cached={r.get('cached')} → {cut(r.get('text'), 110)}")
    alerts = sm.call("GET", f"/v1/users/{uid}/alerts", params={"include_pending": "true"})
    sm.check("alerts is a list", isinstance(alerts, list), f"{len(alerts) if isinstance(alerts, list) else '?'}")
    props = sm.call("GET", f"/v1/users/{uid}/proposals")
    sm.check("proposals is a list", isinstance(props, list))
    return digest


def clone_and_mutate(sm: Smoke, svc, p: dict, profile: dict, headlines: list) -> str:
    """POST /users as a copy of the persona, then onboarding, PATCH × 4, digest and feedback × 8 on the clone."""
    exps = [{"key": e["key"], "role": e["role"], "weight": e["weight"]} for e in profile["exposures"]]
    created = sm.call("POST", "/v1/users", expect=201, keys=("user_id", "exposures", "persona_version"), json={
        "name": f"Smoke: {p['name']}", "topics": profile["topics"], "style": profile["style"], "exposures": exps})
    cid = created.get("user_id")
    if not cid:
        return None
    sm.short[cid] = f"clone:{cid[:8]}"

    topics = set(profile["topics"])
    likes = [h["article_id"] for h in headlines if h.get("topic") in topics][:2]
    dislikes = [h["article_id"] for h in headlines if h.get("topic") not in topics][:1]
    sm.call("POST", f"/v1/users/{cid}/onboarding", json={"likes": likes, "dislikes": dislikes},
            keys=("beta_deltas", "persona_version"))

    first, last = exps[0], exps[-1]
    sm.call("PATCH", f"/v1/users/{cid}/exposures", keys=("exposures",),
            json={"upsert": [{**first, "weight": "medium"}], "remove": [last["key"]]})
    sm.call("PATCH", f"/v1/users/{cid}/exposures", expect=404,
            json={"upsert": [{"key": "zz no such entity zz", "role": "owns", "weight": "high"}]})
    sm.call("PATCH", f"/v1/users/{cid}/topics", json={"topics": {"health": 0.2}})
    flip = "short" if profile["style"].get("length") == "medium" else "medium"
    sm.call("PATCH", f"/v1/users/{cid}/style", json={"length": flip})
    sm.call("PATCH", f"/v1/users/{cid}/alert_prefs", json={"max_per_day": 5, "quiet_start": "23:00"})
    after = sm.call("GET", f"/v1/users/{cid}/profile", keys=("persona_version", "exposures"))
    sm.check("PATCHes bumped persona_version", (after.get("persona_version") or 0) > 1,
             f"v{after.get('persona_version')}")

    digest = sm.call("GET", f"/v1/users/{cid}/digest", params={"refresh": "true"}, keys=("items",))
    items = digest.get("items") or []
    served = {i["article_id"] for i in items + (digest.get("more_you_need") or [])}
    must = [i for i in items if i["section"] == "must_know"]
    unserved = [h["article_id"] for h in headlines if h["article_id"] not in served]
    if items:
        pick = {t: items[n % len(items)]["article_id"] for n, t in enumerate(FEEDBACK_TYPES)}
        if must:
            pick["needed"] = must[0]["article_id"]
        if unserved:
            pick["missed"] = unserved[0]
        for fb_type in FEEDBACK_TYPES:
            body = {"user_id": cid, "article_id": pick[fb_type], "type": fb_type}
            if fb_type == "dwell":
                body["value"] = 30
            sm.call("POST", "/v1/feedback", json=body, keys=("beta_deltas", "history_added"))
    sm.call("POST", "/v1/feedback", expect=422, json={"user_id": cid, "article_id": "x", "type": "bogus"})

    # engagement that should make the proposals job suggest a new exposure
    key, arts = probe_entity(svc, {e["key"] for e in exps}, topics)
    if key:
        print(f"         probe: 3 × `more` on articles about '{key}' → expect an engagement proposal")
        for aid in arts:
            sm.call("POST", "/v1/feedback", json={"user_id": cid, "article_id": aid, "type": "more"})
    return cid


def after_jobs(sm: Smoke, cid: str, digest_item: str) -> None:
    props = sm.call("GET", f"/v1/users/{cid}/proposals", params={"status": "pending"})
    pending = props if isinstance(props, list) else []
    sm.check("proposals job created a pending proposal", bool(pending), f"{len(pending)} pending")
    if pending:
        first = pending[0]
        print(f"         proposal: {cut(first.get('why'), 110)}")
        sm.call("POST", f"/v1/users/{cid}/proposals/{first['proposal_id']}/accept", keys=("proposal",))
        prof = sm.call("GET", f"/v1/users/{cid}/profile", keys=("exposures",))
        edge = next((e for e in prof.get("exposures") or [] if e["key"] == first["entity_key"]), None)
        sm.check("accepted proposal is an exposure with provenance=confirmed",
                 bool(edge) and edge.get("provenance") == "confirmed")
    if len(pending) > 1:
        sm.call("POST", f"/v1/users/{cid}/proposals/{pending[1]['proposal_id']}/reject", keys=("proposal",))
    else:
        sm.call("POST", f"/v1/users/{cid}/proposals/no-such-proposal/reject", expect=404)
    sm.call("GET", f"/v1/users/{cid}/alerts", params={"include_pending": "true"})
    if digest_item:
        sm.call("GET", f"/v1/articles/{digest_item}/render", params={"user_id": cid}, keys=("text", "fallback"))


def print_metrics(m: dict) -> None:
    if not isinstance(m, dict) or "serving" not in m:
        return
    s, e, mk, a = m["serving"], m["engagement"], m["must_know"], m["articles"]
    print(f"  serving    : {s['digests_served']} digests, {s['impressions']} impressions, "
          f"{s['users']} users, by section {s['by_section']}")
    print(f"  engagement : {e['events']} events {e['by_type']}")
    print(f"               read rate by section {e['read_rate_by_section']}")
    print(f"  must_know  : precision {mk['precision']}, miss_rate {mk['miss_rate']}, τ {mk['tau']}")
    print(f"  digests    : {m['digests']['computed']} computed, explore skipped {m['digests']['explore_skipped_rate']},"
          f" hop need items {m['digests']['hop_need_items']}, unscored share {m['digests']['unscored_share']}")
    print(f"  proposals  : {m['proposals']['by_status']}  alerts: {m['alerts']['created']} "
          f"(pending {m['alerts']['pending_quiet_hours']})")
    print(f"  render     : {m['render']['rewrites']} rewrites, fallback share {m['render']['fallback_share']} "
          f"{m['render']['fallback_reasons']}")
    print(f"  articles   : {a['articles']} in {a['window_h']}h, clustered {a['clustered_share']}, "
          f"{a['multi_article_clusters']} multi-article clusters, unscored {a['unscored_share']}, m {a['m']}")
    print(f"  jobs       : " + ", ".join(f"{k} {v['runs']} runs/{v['failed']} failed" for k, v in m["jobs"].items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Personalization API smoke test (live databases)")
    parser.add_argument("--base-url", help="hit a running API instead of an in-process TestClient")
    parser.add_argument("--keep", action="store_true", help="keep the scratch clones and the τ row")
    parser.add_argument("--quiet", action="store_true", help="print only failures, digests and the summary")
    args = parser.parse_args()

    if args.base_url:
        import httpx
        from personalization.service import PersonalizationService
        client, svc = httpx.Client(base_url=args.base_url, timeout=600), PersonalizationService()
    else:
        from fastapi.testclient import TestClient
        from api.app import create_app
        from api.personalization_router import get_service
        # no `with`: the app lifespan (and so the scheduler) doesn't start; jobs run through /admin/jobs
        client, svc = TestClient(create_app(), raise_server_exceptions=False), get_service()

    started = datetime.now(timezone.utc)
    tau_before = svc.logs.current_tau()
    personas = load_personas(svc)
    names = {slug: p["name"] for slug, p in personas.items()}
    sm = Smoke(client, verbose=not args.quiet)
    for p in personas.values():
        sm.short[p["user_id"]] = p["user_id"][:8]

    print("== Global")
    health = sm.call("GET", "/v1/personalization/health", keys=("ok", "mongo", "neo4j", "faiss", "scheduler"))
    sm.check("health ok (mongo, neo4j, faiss)", health.get("ok") is True,
             f"recent_articles={health.get('recent_articles')}")
    jobs_info = sm.call("GET", "/v1/admin/jobs", keys=("scheduler", "jobs"))
    scheduled = {k: v["cron"] for k, v in (jobs_info.get("jobs") or {}).items() if v.get("cron")}
    sm.check("6 jobs have a schedule", len(scheduled) == 6, json.dumps(scheduled))
    sm.call("POST", "/v1/admin/jobs/cluster/run", keys=("ok", "stats"))
    found = sm.call("GET", "/v1/entities/search", params={"q": "manch"})
    sm.check("entity search finds manchester city", any(r.get("key") == "manchester city" for r in found or []))
    headlines = sm.call("GET", "/v1/onboarding/headlines")
    sm.check("10 onboarding headlines", isinstance(headlines, list) and len(headlines) == 10,
             f"{len(headlines) if isinstance(headlines, list) else '?'}")
    headlines = headlines if isinstance(headlines, list) else []
    sm.call("GET", "/v1/users/no-such-user/profile", expect=404)
    sm.call("POST", "/v1/admin/jobs/no-such-job/run", expect=404)

    digests, clones, clone_items = {}, {}, {}
    for slug, p in personas.items():
        print(f"\n== {p['name']}  [{slug}, user {p['user_id'][:8]}]")
        digests[slug] = persona_readonly(sm, p)
        print_digest(p["name"], digests[slug])
        print()
        profile = svc.get_profile(p["user_id"])
        cid = clone_and_mutate(sm, svc, p, profile, headlines)
        if cid:
            clones[slug] = cid
            items = digests[slug].get("items") or []
            clone_items[slug] = items[-1]["article_id"] if items else None

    print("\n== Jobs (through /v1/admin/jobs/{name}/run)")
    users = {"user": list(clones.values())}
    for name, params in (("pi_topk", users), ("digests", users), ("tau", None), ("proposals", users),
                         ("alerts", None)):
        res = sm.call("POST", f"/v1/admin/jobs/{name}/run", params=params, keys=("ok", "stats"))
        print(f"         {name}: {cut(json.dumps(res.get('stats'), default=str), 150)}")
    for slug, cid in clones.items():
        print(f"\n== After jobs: clone of {names[slug]}")
        after_jobs(sm, cid, clone_items.get(slug))

    print("\n== Metrics")
    metrics = sm.call("GET", "/v1/admin/metrics", params={"days": 7},
                      keys=("serving", "engagement", "must_know", "digests", "proposals", "alerts", "render",
                            "articles", "jobs"))
    print_metrics(metrics)

    flagged = overlap_report(digests, names)

    if not args.keep:
        for cid in clones.values():
            svc.delete_user(cid)
        dropped = svc.logs.drop_tau_since(started)
        print(f"\nCleanup: deleted {len(clones)} scratch clones and {dropped} τ row(s) written during the run; "
              f"τ {tau_before} → {svc.logs.current_tau()}")

    svc.exposures.neo4j.close()
    svc.mongo.close()

    calls = [r for r in sm.results if r[0] != "CHECK"]
    failed = [r for r in sm.results if not r[3]]
    print(f"\nSmoke test: {len(calls)} endpoint calls, {len(sm.results) - len(calls)} checks, "
          f"{len(failed)} failed; must_know overlap flags: {len(flagged)}")
    for method, path, status, _ in failed:
        print(f"  FAILED: {method} {sm._fmt(path)} → {status}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
