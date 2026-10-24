"""
E11 (EXP-1 step 2) — style rewrites through the production render path, offline.

Same as personalization/render.py Renderer.render up to the fact check: source = render.source_text(doc, length),
messages = render.build_messages(source, style), the production model/temperature/max_tokens/extra_body from
config.personalization, JSON response parsed with render.parse_response. Client = utils.groq_client.init_groq_llm
(the one render uses). Nothing is written to render_cache or any database.

Budget (R9): every HTTP request, retries included, is appended to cache/groq_calls.jsonl; the run refuses to start
or continue past --budget-cap total calls (default 4,000 across all runs). HTTP 429 / transient errors back off
exponentially (5, 10, 20, 40, 60 s; at most 6 attempts). Resumable: rewrites are appended to
cache/e11_<tag>.jsonl (git-ignored: derived from third-party text) and done (source, cell) pairs are skipped.
Output: results/e11_rewrites_<tag>.json (counts, errors, latency, tokens, sha256 of the rewrites file; no text).

Cells: "length:tone:jargon" items, e.g. --cells short:plain:low,medium:plain:low (the EXP-1 pilot).
"""

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone

from _common import DATA, EXP_DIR, percentile, run_metadata, utf8_stdout, write_json
from config.personalization import PersonalizationSettings
from personalization import render

CACHE = EXP_DIR / "cache"
LEDGER = CACHE / "groq_calls.jsonl"


def calls_so_far() -> int:
    return sum(1 for _ in LEDGER.open(encoding="utf-8")) if LEDGER.exists() else 0


def log_call(tag: str, key: str, status: str, latency_ms: float) -> None:
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "script": "e11",
                             "tag": tag, "key": key, "status": status, "latency_ms": round(latency_ms, 1)}) + "\n")


def call_with_backoff(client, model, messages, cfg, tag, key, cap):
    delays = [5, 10, 20, 40, 60]
    for attempt in range(len(delays) + 1):
        if calls_so_far() >= cap:
            raise SystemExit(f"budget cap {cap} reached (H3)")
        t0 = time.perf_counter()
        try:
            r = client.chat.completions.create(
                model=model, messages=messages, response_format={"type": "json_object"},
                temperature=cfg.render_temperature, max_tokens=cfg.render_max_tokens, extra_body=cfg.render_llm_extra)
            ms = (time.perf_counter() - t0) * 1000
            log_call(tag, key, "ok", ms)
            usage = getattr(r, "usage", None)
            return {"content": r.choices[0].message.content, "latency_ms": round(ms, 1), "attempts": attempt + 1,
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None), "error": None}
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            status = getattr(e, "status_code", None) or type(e).__name__
            log_call(tag, key, f"error:{status}", ms)
            retry = status in (429, 500, 502, 503, 504) or type(e).__name__ in ("APIConnectionError", "APITimeoutError")
            if not retry or attempt == len(delays):
                return {"content": None, "latency_ms": round(ms, 1), "attempts": attempt + 1,
                        "prompt_tokens": None, "completion_tokens": None, "error": f"{status}: {str(e)[:200]}"}
            time.sleep(delays[attempt])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="e10_sources_2026-10-24.json")
    ap.add_argument("--snapshot", default="2026-10-23")
    ap.add_argument("--subset", default="pilot", choices=["pilot", "dev", "test", "all"])
    ap.add_argument("--cells", default="short:plain:low,medium:plain:low")
    ap.add_argument("--model", default=None, help="default: config render_model (production)")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--budget-cap", type=int, default=4000)
    ap.add_argument("--max-new", type=int, default=0, help="stop after this many new rewrites (0 = no limit)")
    args = ap.parse_args()
    utf8_stdout()
    cfg = PersonalizationSettings(_env_file=None)
    assert cfg.render_prompt_version == "r2", cfg.render_prompt_version
    model = args.model or cfg.render_model

    split = json.loads((DATA / args.sources).read_text(encoding="utf-8"))["items"]
    keep = {x["article_id"] for x in split if args.subset == "all" or x["split"] == args.subset
            or (args.subset == "pilot" and x["pilot"])}
    docs = {}
    for line in (DATA / f"e02_gate_sources_{args.snapshot}.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        if d["article_id"] in keep:
            docs[d["article_id"]] = d
    cells = [dict(zip(("length", "tone", "jargon"), c.split(":"))) for c in args.cells.split(",")]

    CACHE.mkdir(exist_ok=True)
    out_path = CACHE / f"e11_{args.tag}.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            r = json.loads(line)
            if r["rewrite"] is not None or r["error"] is None:
                done.add((r["article_id"], r["cell"]))
    from utils.groq_client import init_groq_llm
    client, _ = init_groq_llm("[E11]", "Research rewrites")
    if client is None:
        raise SystemExit("no Groq client (GROQ_API_KEY missing)")

    start_calls, new = calls_so_far(), 0
    with out_path.open("a", encoding="utf-8") as fh:
        for aid in sorted(docs):
            for style in cells:
                cell = f"{style['length']}:{style['tone']}:{style['jargon']}"
                if (aid, cell) in done:
                    continue
                if args.max_new and new >= args.max_new:
                    break
                source, field = render.source_text(docs[aid], style["length"], cfg)
                res = call_with_backoff(client, model, render.build_messages(source, style), cfg, args.tag,
                                        f"{aid}|{cell}", args.budget_cap)
                rewrite = render.parse_response(res["content"]) if res["content"] is not None else None
                fh.write(json.dumps({"article_id": aid, "cell": cell, "style": style, "source_field": field,
                                     "source_hash": render.source_hash(source), "model": model,
                                     "prompt_version": cfg.render_prompt_version, "rewrite": rewrite,
                                     "raw_unparseable": res["content"] if rewrite is None else None,
                                     **{k: res[k] for k in ("latency_ms", "attempts", "prompt_tokens",
                                                            "completion_tokens", "error")}},
                                    ensure_ascii=False) + "\n")
                fh.flush()
                new += 1
                if new % 20 == 0:
                    print(f"  {new} new rewrites, {calls_so_far() - start_calls} calls this run", flush=True)

    last = {}
    for line in out_path.open(encoding="utf-8"):                 # a retried pair keeps its latest row
        r = json.loads(line)
        last[(r["article_id"], r["cell"])] = r
    rows = list(last.values())
    lat = [r["latency_ms"] for r in rows if r["error"] is None]
    payload = {
        "meta": run_metadata("research/experiments/e11_generate_rewrites.py", tag=args.tag, model=model,
                             prompt_version=cfg.render_prompt_version, temperature=cfg.render_temperature,
                             max_tokens=cfg.render_max_tokens, extra_body=cfg.render_llm_extra, subset=args.subset,
                             cells=args.cells, sources=args.sources),
        "rows": len(rows), "new_this_run": new,
        "groq_calls_this_run": calls_so_far() - start_calls, "groq_calls_total_all_runs": calls_so_far(),
        "parsed": sum(r["rewrite"] is not None for r in rows),
        "unparseable": sum(r["rewrite"] is None and r["error"] is None for r in rows),
        "errors": sum(r["error"] is not None for r in rows),
        "latency_ms": {"p50": percentile(lat, .5), "p95": percentile(lat, .95)} if lat else None,
        "tokens": {"prompt": sum(r["prompt_tokens"] or 0 for r in rows),
                   "completion": sum(r["completion_tokens"] or 0 for r in rows)},
        "rewrites_file": str(out_path.relative_to(EXP_DIR)).replace("\\", "/"),
        "rewrites_file_sha256": hashlib.sha256(out_path.read_bytes()).hexdigest(),
    }
    print(write_json(f"e11_rewrites_{args.tag}.json", payload))
    print({k: payload[k] for k in ("rows", "parsed", "unparseable", "errors", "groq_calls_this_run",
                                   "groq_calls_total_all_runs", "latency_ms", "tokens")})


if __name__ == "__main__":
    main()
