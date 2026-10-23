"""
E05 — smoke test of the learned checkers (MiniCheck-Flan-T5-Large, MiniCheck-DeBERTa-v3-Large) and the current gate.

10 hand-written (document, claim) pairs (original text written for this test, no third-party content).
`supported` is MiniCheck's label convention: 1 = every piece of the claim is supported by the document.
An omission is therefore supported (1): MiniCheck checks support, not completeness.

Runs offline against the pinned checkpoints in models/ckpts (HF cache layout, refs/main → pinned commit).
Pass criteria (smoke only, not an accuracy claim): the checker loads offline, returns a probability in [0, 1]
for every pair, and two consecutive runs give identical probabilities (determinism).
Latency: per pair, batch size 1, after one warm-up pass; device recorded.

Run with the checker venv:  ~/.venvs/mapnai-checkers/Scripts/python.exe research/experiments/e05_checker_smoke.py --tag <tag>
"""

import argparse
import json
import os
import subprocess
import sys
import time

from _common import ROOT, run_metadata, percentile, utf8_stdout, write_json

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("NLTK_DATA", str(ROOT / "models" / "nltk_data"))

CKPTS = ROOT / "models" / "ckpts"

DOC_BUDGET = ("The city council approved a budget of 4.2 million dollars on Tuesday. Mayor Elena Ruiz said the "
              "money will fund two new libraries and repair roads in the north district.")
DOC_MATCH = ("Arsenal beat Chelsea 2-1 at the Emirates Stadium on Saturday, with Bukayo Saka scoring the winner "
             "in the 88th minute.")
DOC_FIRE = ("Officials said the factory fire appears to have been caused by an electrical fault, but the "
            "investigation is ongoing. No one was injured.")

PAIRS = [
    ("faithful_paraphrase", DOC_BUDGET, "On Tuesday the council passed a 4.2 million dollar budget.", 1),
    ("number_change", DOC_BUDGET, "The council approved a budget of 5.2 million dollars on Tuesday.", 0),
    ("negation", DOC_BUDGET, "The city council rejected the budget on Tuesday.", 0),
    ("omission", DOC_BUDGET, "Mayor Elena Ruiz said the budget will pay for two new libraries.", 1),
    ("faithful_paraphrase", DOC_MATCH, "Bukayo Saka scored a late winner as Arsenal defeated Chelsea 2-1.", 1),
    ("role_swap", DOC_MATCH, "Chelsea beat Arsenal 2-1 at the Emirates Stadium on Saturday.", 0),
    ("entity_substitution", DOC_MATCH, "Arsenal beat Chelsea 2-1, with Declan Rice scoring the winner.", 0),
    ("omission", DOC_MATCH, "Arsenal beat Chelsea on Saturday.", 1),
    ("hedge_removed", DOC_FIRE, "Officials confirmed the factory fire was caused by an electrical fault.", 0),
    ("faithful_paraphrase", DOC_FIRE, "No one was hurt in the factory fire, officials said.", 1),
]
NAMES = {DOC_BUDGET: ["Elena Ruiz"], DOC_MATCH: ["Arsenal", "Chelsea", "Emirates Stadium", "Bukayo Saka"],
         DOC_FIRE: []}


def run_checker(model_name: str, device: str):
    """Runs in its own process (see main): CUDA_VISIBLE_DEVICES must be set before torch initialises CUDA."""
    import torch
    from minicheck.minicheck import MiniCheck
    t0 = time.perf_counter()
    scorer = MiniCheck(model_name=model_name, cache_dir=str(CKPTS))
    load_s = time.perf_counter() - t0
    dev = str(next(scorer.model.model.parameters()).device)
    docs, claims = [p[1] for p in PAIRS], [p[2] for p in PAIRS]
    scorer.score(docs=docs[:1], claims=claims[:1])                     # warm-up
    probs, lat = [], []
    for d, c in zip(docs, claims):
        if dev.startswith("cuda"):
            torch.cuda.synchronize()
        t = time.perf_counter()
        _, p, _, _ = scorer.score(docs=[d], claims=[c])
        if dev.startswith("cuda"):
            torch.cuda.synchronize()
        lat.append((time.perf_counter() - t) * 1000)
        probs.append(float(p[0]))
    _, probs2, _, _ = scorer.score(docs=docs, claims=claims)
    preds = [1 if p > 0.5 else 0 for p in probs]
    gold = [p[3] for p in PAIRS]
    out = {
        "model_name": model_name, "device": dev, "load_seconds": round(load_s, 2),
        "probs": [round(p, 6) for p in probs], "preds": preds,
        "correct": sum(int(a == b) for a, b in zip(preds, gold)),
        "deterministic": all(abs(a - float(b)) < 1e-6 for a, b in zip(probs, probs2)),
        "in_unit_interval": all(0.0 <= p <= 1.0 for p in probs),
        "latency_ms": {"per_pair": [round(x, 1) for x in lat], "p50": round(percentile(lat, .5), 1),
                       "max": round(max(lat), 1)},
    }
    out["smoke_pass"] = out["deterministic"] and out["in_unit_interval"] and len(probs) == len(PAIRS)
    del scorer
    if dev.startswith("cuda"):
        torch.cuda.empty_cache()
    return out


def run_gate():
    from personalization.factcheck import verify
    rows, lat = [], []
    for kind, doc, claim, gold in PAIRS:
        t = time.perf_counter()
        ok, missing, added = verify(doc, claim, NAMES[doc])
        lat.append((time.perf_counter() - t) * 1000)
        rows.append({"kind": kind, "gold": gold, "pass": int(ok), "missing": missing, "added": added})
    return {"rows": rows, "correct": sum(int(r["pass"] == r["gold"]) for r in rows),
            "latency_ms_p50": round(percentile(lat, .5), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--models", default="flan-t5-large:cuda,deberta-v3-large:cuda,deberta-v3-large:cpu")
    ap.add_argument("--one", help=argparse.SUPPRESS)                 # internal: run a single checker spec
    args = ap.parse_args()
    utf8_stdout()
    if args.one:
        name, device = args.one.split(":")
        print("RESULT " + json.dumps(run_checker(name, device)))
        return
    import platform
    import torch
    results = {"current_gate_v1": run_gate()}
    for spec in args.models.split(","):
        name, device = spec.split(":")
        env = dict(os.environ, **({"CUDA_VISIBLE_DEVICES": ""} if device == "cpu" else {}))
        proc = subprocess.run([sys.executable, __file__, "--tag", args.tag, "--one", spec], env=env,
                              capture_output=True, text=True, encoding="utf-8")
        line = [l for l in proc.stdout.splitlines() if l.startswith("RESULT ")]
        results[f"{name}@{device}"] = (json.loads(line[-1][7:]) if line else
                                       {"smoke_pass": False, "error": proc.stderr[-2000:]})
    payload = {
        "meta": run_metadata("research/experiments/e05_checker_smoke.py", tag=args.tag, torch=torch.__version__,
                             cuda=torch.version.cuda, gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available()
                             else None, cpu=platform.processor(),
                             label="SMOKE TEST on 10 hand-written pairs: not an accuracy estimate"),
        "pairs": [{"kind": k, "gold_supported": g} for k, _, _, g in PAIRS],
        "results": results,
    }
    print(write_json(f"e05_checker_smoke_{args.tag}.json", payload))
    for k, v in results.items():
        print(k, {x: v[x] for x in v if x in ("device", "correct", "smoke_pass", "deterministic", "latency_ms",
                                               "latency_ms_p50", "load_seconds", "preds")})


if __name__ == "__main__":
    main()
