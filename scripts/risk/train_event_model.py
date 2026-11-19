"""
MAPNAI — scripts/risk/train_event_model.py
Trains Agent 4's offline event-type model (TF-IDF + logistic regression) on the LLM labels
from scripts/risk/label_*.ipynb. Runs on CPU in under a minute.

Usage (from the project root):
    python -m scripts.risk.train_event_model
Reads data/risk/risk_labeled.jsonl (v1 or v2 labels; v1's doping / match_fixing become integrity),
leaves out the hand-labelled gold ids (data/risk/gold_ids.txt) and writes models/risk/event_model.joblib.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline

from config.risk_taxonomy import (EVENT_SEVERITY, EVENT_TYPES, INTEGRITY_FIX_FROM, INTEGRITY_FIX_RX,
                                  LEGACY_EVENT_TYPES, event_text)

LABELS_PATH = Path("data/risk/risk_labeled.jsonl")
GOLD_IDS_PATH = Path("data/risk/gold_ids.txt")
OUT_PATH = Path("models/risk/event_model.joblib")


def build_pipeline():
    return make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=200_000),
        LogisticRegression(max_iter=3000, C=4, class_weight="balanced"),
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--labels", type=Path, default=LABELS_PATH)
    p.add_argument("--out", type=Path, default=OUT_PATH)
    args = p.parse_args()

    df = pd.read_json(args.labels, lines=True)
    df = df[df.in_scope].copy()
    df["y"] = df.event_type.replace(LEGACY_EVENT_TYPES)
    df = df[df.y.isin(EVENT_TYPES)]
    gold = set(GOLD_IDS_PATH.read_text().split()) if GOLD_IDS_PATH.exists() else set()
    df = df[~df.id.isin(gold)]
    X = [event_text(t, b) for t, b in zip(df.title.fillna(""), df.body.fillna(""))]
    fix = df.y.isin(INTEGRITY_FIX_FROM).to_numpy() & np.array([bool(INTEGRITY_FIX_RX.search(x)) for x in X])
    df.loc[fix, "y"] = "integrity"
    print(f"{len(df)} training rows ({len(gold)} gold ids held out, {fix.sum()} relabelled to integrity)\n"
          f"{df.y.value_counts().to_string()}")

    # 5-fold CV estimate against the LLM labels
    proba = cross_val_predict(build_pipeline(), X, df.y, method="predict_proba",
                              cv=StratifiedKFold(5, shuffle=True, random_state=0))
    classes = sorted(df.y.unique())
    pred = np.array(classes)[proba.argmax(1)]
    sev = np.array([EVENT_SEVERITY[c] for c in classes])
    mae = np.abs(proba @ sev - df.y.map(EVENT_SEVERITY).to_numpy()).mean()
    acc, f1 = accuracy_score(df.y, pred), f1_score(df.y, pred, average="macro")
    print(f"\nCV accuracy {acc:.3f} | macro-F1 {f1:.3f} | expected-severity MAE {mae:.2f} / 25")
    print(classification_report(df.y, pred, digits=2, zero_division=0))

    model = build_pipeline().fit(X, df.y)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "pipeline": model,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_train": len(df),
        "labeler": sorted(df.labeler.dropna().unique().tolist()) if "labeler" in df else [],
        "cv": {"accuracy": round(acc, 4), "macro_f1": round(f1, 4), "severity_mae": round(float(mae), 3)},
    }, args.out)
    print(f"Saved {args.out}")


if __name__ == "__main__":
    main()
