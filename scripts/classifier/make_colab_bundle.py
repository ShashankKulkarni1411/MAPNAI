"""
MAPNAI — scripts/classifier/make_colab_bundle.py
Packs everything the Colab notebook needs into data/classifier/colab_bundle.zip:
    candidates.jsonl, classifier_taxonomy.py, classifier_model.py
Upload the zip to Google Drive at  MyDrive/MAPNAI_classifier/colab_bundle.zip.

Usage (from the project root):
    python -m scripts.classifier.collect_rss      # optional: grab the latest articles
    python -m scripts.classifier.build_dataset
    python -m scripts.classifier.make_colab_bundle
"""

import zipfile
from pathlib import Path

OUT = Path("data/classifier/colab_bundle.zip")
FILES = {
    "data/classifier/candidates.jsonl": "candidates.jsonl",
    "config/classifier_taxonomy.py": "classifier_taxonomy.py",
    "agents/classifier_model.py": "classifier_model.py",
}


def main():
    missing = [src for src in FILES if not Path(src).exists()]
    if missing:
        raise SystemExit(f"Missing {missing} — run build_dataset.py first.")
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for src, name in FILES.items():
            z.write(src, name)
    print(f"Wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB). Upload it to MyDrive/MAPNAI_classifier/")


if __name__ == "__main__":
    main()
