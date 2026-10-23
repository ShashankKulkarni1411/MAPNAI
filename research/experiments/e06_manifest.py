"""
E06 — inventory of every external dataset and model file used by the research harness.

Writes research/experiments/data/MANIFEST.json (tracked in git: hashes, sizes, sources and revisions only; the
files themselves live in git-ignored folders). Re-run after each acquisition; git history keeps older versions.
"""

import hashlib
import json
from pathlib import Path

from _common import DATA, ROOT, run_metadata

ENTRIES = [
    # (group, path relative to repo root, source, revision, licence)
    ("MIND-small", "research/experiments/data/external/mind/MINDsmall_dev.zip",
     "https://huggingface.co/datasets/Recommenders/MIND", "2115068f457b577f93a268fffe22373e45727d89",
     "Microsoft Research License (non-commercial research; no redistribution)"),
    ("MIND-small", "research/experiments/data/external/mind/MINDsmall_train.zip",
     "https://huggingface.co/datasets/Recommenders/MIND", "2115068f457b577f93a268fffe22373e45727d89",
     "Microsoft Research License (non-commercial research; no redistribution)"),
    ("MIND-small", "research/experiments/data/external/mind/dev/news.tsv", "extracted from MINDsmall_dev.zip", "", ""),
    ("MIND-small", "research/experiments/data/external/mind/train/news.tsv", "extracted from MINDsmall_train.zip", "",
     ""),
    ("EXP-7 sources", "research/experiments/data/external/mind_sources_120.jsonl",
     "e04_mind_sources.py --tag 2026-10-23", "", "derived from MIND-small (same licence)"),
]
MODEL_DIRS = [
    ("lytang/MiniCheck-Flan-T5-Large", "96eafd01cee2d16cf81aaa2fb226b14f422a37b3", "MIT"),
    ("lytang/MiniCheck-DeBERTa-v3-Large", "2f2d01a54fa022a7ffadb76260e1ea8bc88c82bb", "MIT"),
]
OTHER = [
    ("NLTK data", "models/nltk_data/tokenizers/punkt_tab.zip", "nltk.download('punkt_tab') with nltk 3.9.1", "",
     "Apache-2.0 (NLTK data)"),
]
PENDING = {
    "lytang/LLM-AggreFact": "PENDING (H4): gated on Hugging Face; needs the user's login and acceptance of the "
                            "CC-BY-ND-4.0 evaluation-only terms",
    "bespokelabs/Bespoke-MiniCheck-7B": "NOT DOWNLOADED locally (6 GB GPU); Colab script research/colab/run_bespoke.py",
}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def item(group, rel, source, rev, licence):
    p = ROOT / rel
    return {"group": group, "path": rel, "exists": p.exists(), "bytes": p.stat().st_size if p.exists() else None,
            "sha256": sha256(p) if p.exists() else None, "source": source, "revision": rev, "licence": licence}


def main():
    files = [item(*e) for e in ENTRIES + OTHER]
    for repo, rev, lic in MODEL_DIRS:
        snap = ROOT / "models" / "ckpts" / f"models--{repo.replace('/', '--')}" / "snapshots" / rev
        for f in sorted(snap.iterdir()):
            files.append(item(repo, str(f.relative_to(ROOT)).replace("\\", "/"), f"https://huggingface.co/{repo}",
                              rev, lic))
    out = {"meta": run_metadata("research/experiments/e06_manifest.py"), "files": files, "pending": PENDING}
    path = DATA / "MANIFEST.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(path, len(files), "files;", sum(f["bytes"] or 0 for f in files) / 1e9, "GB;",
          "missing:", [f["path"] for f in files if not f["exists"]])


if __name__ == "__main__":
    main()
