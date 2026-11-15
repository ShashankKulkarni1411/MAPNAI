"""
E23 — CAFG on MAPNAI rewrites (dev tuning on human pilot labels) and S4 on the adjudicated test gold (PREREG §8, §13).

  "$C" e23_cafg_mapnai.py --step ft5                    MiniCheck-FT5 support per rewrite sentence, all 400 items -> cache
  "$V" e23_cafg_mapnai.py --step tune --tag <date>      24-point dev grid, §13 selection rule, writes the frozen config
  "$V" e23_cafg_mapnai.py --step test --config <path> --tag <date>
                                                        refuses unless the config's sha256 is in LEDGER.md and the file
                                                        is committed unchanged; computes S4 once

Inputs: annotation_gold-<tag>.csv (rendered source + rewrite per item), key_<tag>.json (article, cell, split, gate v1,
weight), pilot workbooks (dev labels), gold_adjudicated_main CSV (test labels), e02 sources (NER names).
Outputs contain ids and labels only, no news text.
"""

import argparse
import csv
import gzip
import hashlib
import itertools
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

from _common import DATA, EXP_DIR, ROOT, run_metadata, utf8_stdout, write_json

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("NLTK_DATA", str(ROOT / "models" / "nltk_data"))

TAG = "gold-2026-11-01"
EXPORT = ROOT / "research" / "annotation" / "export"
TA = EXPORT / "to_annotators"
PILOT = [TA / "A1" / "pilot_A1_gold-2026-11-01_Shaunak_be.xlsx", TA / "A2" / "pilot_A2_gold-2026-11-01_Satvik_be.xlsx"]
MAIN_A1 = TA / "A1" / "_A1-ShaunakOP.xlsx"
MAIN_A2 = {"round1": TA / "A2" / "main_A2_gold-2026-11-01_SatvikOP_rl.xlsx",
           "round2": TA / "A2" / "main_A2_gold-2026-11-01op2.xlsx"}
GOLD = EXPORT / "adjudication" / "gold_adjudicated_main-2026-11-01.csv"
FT5_CACHE = EXP_DIR / "cache" / "e23_ft5_sentences_gold-2026-11-01.jsonl"
CONFIGS = ROOT / "research" / "faithgate" / "configs"
BUDGET = {"short": 50, "medium": 120}
SEED, NBOOT = 13, 2000
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“‘(])")          # = faithgate.cafg._SENT


def sentences(text):
    return [s for s in _SENT.split((text or "").strip()) if s]


def load_items():
    csv.field_size_limit(10 ** 8)
    key = json.loads((EXPORT / f"key_{TAG}.json").read_text(encoding="utf-8"))
    with open(EXPORT / f"annotation_{TAG}.csv", encoding="utf-8") as f:
        text = {r["item_id"]: (r["source"], r["rewrite"]) for r in csv.DictReader(f)}
    assert set(text) == set(key), "export and key differ"
    return key, text


# ---------------------------------------------------------------- step ft5 (checker venv)
def step_ft5(args):
    from minicheck.minicheck import MiniCheck
    key, text = load_items()
    done = set()
    if FT5_CACHE.exists():
        done = {json.loads(l)["item_id"] for l in FT5_CACHE.open(encoding="utf-8")}
    todo = [i for i in sorted(key) if i not in done]
    print(f"{len(done)} cached, {len(todo)} to score", flush=True)
    if not todo:
        return
    scorer = MiniCheck(model_name="flan-t5-large", cache_dir=str(ROOT / "models" / "ckpts"), batch_size=args.batch_size)
    with FT5_CACHE.open("a", encoding="utf-8") as fh:
        for n, iid in enumerate(todo, 1):
            src, rw = text[iid]
            sents = sentences(rw) or ([rw] if rw.strip() else [])
            probs = []
            if sents:
                _, probs, _, _ = scorer.score(docs=[src] * len(sents), claims=sents)
            fh.write(json.dumps({"item_id": iid, "probs": [round(float(p), 6) for p in probs]}) + "\n")
            fh.flush()
            if n % 25 == 0:
                print(f"  {n}/{len(todo)}", flush=True)


# ---------------------------------------------------------------- shared (research venv)
def names_by_article(article_ids):
    out = {}
    for line in (DATA / "e02_gate_sources_2026-10-23.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        if d["article_id"] in article_ids:
            out[d["article_id"]] = [e["name"] for e in d.get("entities") or [] if e.get("name")]
    return out


def grid():
    for names, ret, tau, theta in itertools.product([True, False], ["off", "budget_core"], [None, 0.90],
                                                    [0.3, 0.5, 0.7]):
        yield {"added_names": names, "retention": ret, "lexical_accept": tau, "theta": theta}


def to_cfg(p, length):
    from research.faithgate.cafg import CAFGConfig
    core = p["retention"] == "budget_core"
    return CAFGConfig(normalize_entities=True, added_names=p["added_names"], added_months=False,
                      lexical_accept=p["lexical_accept"], require_retention=core,
                      budget_words=BUDGET[length] if core else None, core_k=3, learned=True, theta=p["theta"])


def run_cafg(p, ids, key, text, names, ft5):
    from research.faithgate.cafg import decide
    out = {}
    for iid in ids:
        src, rw = text[iid]
        if not rw.strip():
            out[iid] = (False, False, "unparseable")
            continue
        probs = ft5[iid]
        checker = lambda doc, claims, _p=probs: _p if len(claims) == len(_p) else (_ for _ in ()).throw(
            RuntimeError("sentence split mismatch"))
        d = decide(src, rw, names[key[iid]["article_id"]], to_cfg(p, key[iid]["cell"].split(":")[0]), checker)
        out[iid] = (d.accept, d.checker_called, d.stage)
    return out


def rates(ids, accept, faithful, weight):
    """Weighted FRR = P(reject | faithful), FAR = P(accept | unfaithful); faithful may be soft (0..1)."""
    fw = sum(weight[i] * faithful[i] for i in ids)
    uw = sum(weight[i] * (1 - faithful[i]) for i in ids)
    frr = sum(weight[i] * faithful[i] * (not accept[i]) for i in ids) / fw if fw else float("nan")
    far = sum(weight[i] * (1 - faithful[i]) * accept[i] for i in ids) / uw if uw else float("nan")
    return frr, far


LABELS_CACHE = EXP_DIR / "cache" / "e23_workbook_labels_gold-2026-11-01.json"


def _read_xlsx_raw(path):
    import openpyxl
    ws = openpyxl.load_workbook(path, data_only=True)["Items"]
    hdr = [c.value for c in ws[1]]
    return {d["item_id"]: {k: (None if v is None else str(v)) for k, v in d.items()
                           if k in ("item_id", "faithful", "addition", "distortion", "omission")}
            for d in (dict(zip(hdr, r)) for r in ws.iter_rows(min_row=2, values_only=True)) if d.get("item_id")}


def step_labels(args):
    """Any Python with openpyxl: workbook labels -> cache JSON (labels only), with each workbook's sha256."""
    out = {}
    for p in PILOT + [MAIN_A1, *MAIN_A2.values()]:
        out[p.name] = {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "items": _read_xlsx_raw(p)}
    LABELS_CACHE.write_text(json.dumps(out), encoding="utf-8")
    print({k: (v["sha256"][:12], len(v["items"])) for k, v in out.items()})


def read_xlsx(path):
    try:
        return _read_xlsx_raw(path)
    except ImportError:
        c = json.loads(LABELS_CACHE.read_text(encoding="utf-8"))[path.name]
        if hashlib.sha256(path.read_bytes()).hexdigest() != c["sha256"]:
            raise SystemExit(f"{path.name} changed since --step labels")
        return c["items"]


# ---------------------------------------------------------------- step tune
def step_tune(args):
    key, text = load_items()
    ft5 = {json.loads(l)["item_id"]: json.loads(l)["probs"] for l in FT5_CACHE.open(encoding="utf-8")}
    labs = defaultdict(list)
    for p in PILOT:
        for iid, d in read_xlsx(p).items():
            labs[iid].append(int(d["faithful"]))
    ids = sorted(labs)
    assert all(key[i]["split"] == "dev" for i in ids) and len(ids) == 160
    faithful = {i: sum(v) / len(v) for i, v in labs.items()}
    weight = {i: key[i]["weight"] for i in ids}
    names = names_by_article({key[i]["article_id"] for i in ids})
    v1 = {i: bool(key[i]["gate_v1_serve"]) for i in ids}
    frr1, far1 = rates(ids, v1, faithful, weight)
    rows = []
    for k, p in enumerate(grid()):
        res = run_cafg(p, ids, key, text, names, ft5)
        acc = {i: res[i][0] for i in ids}
        frr, far = rates(ids, acc, faithful, weight)
        rows.append({"idx": k, **p, "frr": round(frr, 4), "far": round(far, 4), "bacc": round(1 - (frr + far) / 2, 4),
                     "ft5_calls": sum(res[i][1] for i in ids),
                     "stages": dict(Counter(res[i][2] for i in ids)),
                     "qualifies": far <= far1 + 0.02})
    q = [r for r in rows if r["qualifies"]]
    sel = (min(q, key=lambda r: (r["frr"], r["ft5_calls"], r["idx"])) if q
           else max(rows, key=lambda r: (r["bacc"], -r["ft5_calls"], -r["idx"])))
    config = {k: sel[k] for k in ("added_names", "retention", "lexical_accept", "theta")}
    config.update({"normalize_entities": True, "added_months": False, "core_k": 3, "budget_words": BUDGET,
                   "learned": "minicheck-ft5 @ 96eafd01 (P-fixed), min over rewrite sentences",
                   "selected_by": "PREREG §13: min dev FRR s.t. FAR <= FAR_v1 + 0.02" if q else
                                  "PREREG §13 fallback: max dev BAcc (no point met the FAR constraint)",
                   "dev_tag": args.tag})
    CONFIGS.mkdir(exist_ok=True)
    cpath = CONFIGS / f"cafg_mapnai_{args.tag}.json"
    cpath.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    sha = hashlib.sha256(cpath.read_bytes()).hexdigest()
    payload = {"meta": run_metadata("research/experiments/e23_cafg_mapnai.py", step="tune", tag=args.tag,
                                    labels="human pilot labels (soft = mean of annotators)"),
               "n_dev_items": len(ids), "dev_unfaithful_mass": round(sum(1 - faithful[i] for i in ids), 2),
               "v1": {"frr": round(frr1, 4), "far": round(far1, 4), "bacc": round(1 - (frr1 + far1) / 2, 4)},
               "grid": rows, "selected_idx": sel["idx"], "frozen_config": str(cpath.relative_to(ROOT)),
               "frozen_config_sha256": sha}
    print(write_json(f"e23_cafg_mapnai_dev_{args.tag}.json", payload))
    print(f"v1 dev FRR {frr1:.3f} FAR {far1:.3f}")
    for r in rows:
        print(f"{r['idx']:2d} names={r['added_names']!s:5} ret={r['retention']:11} tau={r['lexical_accept']!s:4} "
              f"theta={r['theta']}  FRR {r['frr']:.3f} FAR {r['far']:.3f} calls {r['ft5_calls']:3d} "
              f"{'Q' if r['qualifies'] else ' '}")
    print(f"selected {sel['idx']} -> {cpath}\nsha256 {sha}")


# ---------------------------------------------------------------- step test
def frozen(cpath):
    sha = hashlib.sha256(cpath.read_bytes()).hexdigest()
    if sha not in (ROOT / "research" / "LEDGER.md").read_text(encoding="utf-8"):
        raise SystemExit(f"sha256 {sha} not in LEDGER.md: freeze first")
    rel = str(cpath.resolve().relative_to(ROOT)).replace("\\", "/")
    git = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()
    if not git("ls-files", rel) or git("status", "--porcelain", rel):
        raise SystemExit(f"{rel} is not committed unchanged")
    return sha, git("log", "-1", "--format=%h", "--", rel)


def kappa(x, y):
    n = len(x)
    po = sum(a == b for a, b in zip(x, y)) / n
    cx, cy = Counter(x), Counter(y)
    pe = sum(cx[c] * cy[c] for c in cx) / n / n
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def is_lexical(g):
    if g["faithful"] != "0":
        return False
    note = g.get("reason") or ""
    return g["distortion_type"] in ("number", "entity") or (
        g["addition"] == "1" and bool(re.search(r"\d|(?<=\w )[A-Z]\w", note)))


def step_test(args):
    import random
    cpath = Path(args.config)
    sha, commit = frozen(cpath)
    out = EXP_DIR / "results" / f"e23_s4_test_{args.tag}.json"
    if out.exists():
        raise SystemExit(f"{out.name} exists: S4 is computed once")
    cfg = json.loads(cpath.read_text(encoding="utf-8"))
    p = {k: cfg[k] for k in ("added_names", "retention", "lexical_accept", "theta")}
    key, text = load_items()
    ft5 = {json.loads(l)["item_id"]: json.loads(l)["probs"] for l in FT5_CACHE.open(encoding="utf-8")}
    with open(GOLD, encoding="utf-8") as f:
        gold = {r["item_id"]: r for r in csv.DictReader(f)}
    ids = sorted(gold)
    assert len(ids) == 240 and all(key[i]["split"] == "test" for i in ids)
    names = names_by_article({key[i]["article_id"] for i in ids})
    res = run_cafg(p, ids, key, text, names, ft5)
    gates = {"v1": {i: bool(key[i]["gate_v1_serve"]) for i in ids}, "cafg": {i: res[i][0] for i in ids}}
    weight = {i: key[i]["weight"] for i in ids}
    f_all = {i: int(gold[i]["faithful"]) for i in ids}
    lex = {i for i in ids if is_lexical(gold[i])}
    sem = {i for i in ids if f_all[i] == 0 and i not in lex}

    def metrics(sample):
        m = {}
        for g, acc in gates.items():
            frr, far = rates(sample, acc, f_all, weight)
            _, far_lex = rates([i for i in sample if i in lex or f_all[i] == 1], acc, f_all, weight)
            _, far_sem = rates([i for i in sample if i in sem or f_all[i] == 1], acc, f_all, weight)
            m[g] = {"frr": frr, "far": far, "far_lex": far_lex, "far_sem": far_sem,
                    "serve": sum(weight[i] * acc[i] for i in sample) / sum(weight[i] for i in sample)}
        return m

    point = metrics(ids)
    by_art = defaultdict(list)
    for i in ids:
        by_art[key[i]["article_id"]].append(i)
    arts = sorted(by_art)
    rng = random.Random(SEED)
    boots = []
    for _ in range(NBOOT):
        sample = [i for a in (rng.choice(arts) for _ in arts) for i in by_art[a]]
        boots.append(metrics(sample))

    def ci(f):
        v = sorted(x for x in (f(b) for b in boots) if x == x)
        return [round(v[int(0.025 * len(v))], 4), round(v[int(0.975 * len(v)) - 1], 4)] if v else None

    summ = {g: {k: {"est": round(point[g][k], 4), "ci95": ci(lambda b, g=g, k=k: b[g][k])} for k in point[g]}
            for g in gates}
    diff = {k: {"est": round(point["v1"][k] - point["cafg"][k], 4),
                "ci95": ci(lambda b, k=k: b["v1"][k] - b["cafg"][k])} for k in ("frr", "far", "far_lex", "far_sem")}
    s4 = {"frr_lower_by_10pts": diff["frr"]["est"] >= 0.10,
          "far_lex_noninferior_2pts": diff["far_lex"]["ci95"] is not None and diff["far_lex"]["ci95"][0] > -0.02,
          "semantic_target": diff["far_sem"]["ci95"] is not None and diff["far_sem"]["ci95"][0] > 0}
    s4["S4_pass"] = s4["frr_lower_by_10pts"] and s4["far_lex_noninferior_2pts"]

    # agreement (main batch), both A2 rounds, bootstrap over items
    a1 = read_xlsx(MAIN_A1)
    agree = {}
    for rnd, path in MAIN_A2.items():
        a2 = read_xlsx(path)
        x = [str(a1[i]["faithful"]) for i in ids]
        y = [str(a2[i]["faithful"]) for i in ids]
        r2 = random.Random(SEED)
        ks = sorted(kappa(*zip(*[(x[j], y[j]) for j in (r2.randrange(240) for _ in range(240))])) for _ in range(NBOOT))
        agree[rnd] = {"kappa_faithful": round(kappa(x, y), 4), "ci95": [round(ks[50], 4), round(ks[1949], 4)],
                      "agreement": round(sum(a == b for a, b in zip(x, y)) / 240, 4)}

    payload = {"meta": run_metadata("research/experiments/e23_cafg_mapnai.py", step="test", tag=args.tag,
                                    frozen_config=str(cpath), frozen_config_sha256=sha, config_commit=commit,
                                    bootstrap=f"{NBOOT} over {len(arts)} source articles, seed {SEED}, weighted"),
               "n": len(ids), "n_unfaithful": sum(1 - f_all[i] for i in ids), "n_lexical": len(lex),
               "n_semantic": len(sem), "cafg_ft5_calls": sum(res[i][1] for i in ids),
               "cafg_stages": dict(Counter(res[i][2] for i in ids)),
               "gates": summ, "diff_v1_minus_cafg": diff, "s4": s4, "main_batch_agreement": agree,
               "confusion_unweighted": {g: dict(Counter(f"faithful={f_all[i]}/accept={int(acc[i])}" for i in ids))
                                        for g, acc in gates.items()}}
    print(write_json(out.name, payload))
    with gzip.open(out.with_name(out.stem + "_preds.jsonl.gz"), "wt", encoding="utf-8") as fh:
        for i in ids:
            fh.write(json.dumps({"item_id": i, "faithful": f_all[i], "lexical": i in lex, "v1": gates["v1"][i],
                                 "cafg": gates["cafg"][i], "stage": res[i][2], "weight": weight[i]}) + "\n")
    print(json.dumps({k: payload[k] for k in ("gates", "diff_v1_minus_cafg", "s4", "main_batch_agreement")}, indent=1))


if __name__ == "__main__":
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", required=True, choices=["ft5", "labels", "tune", "test"])
    ap.add_argument("--tag", default="2026-11-15")
    ap.add_argument("--config")
    ap.add_argument("--batch-size", type=int, default=8)
    a = ap.parse_args()
    {"ft5": step_ft5, "labels": step_labels, "tune": step_tune, "test": step_test}[a.step](a)
