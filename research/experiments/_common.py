"""
Shared helpers for the research experiments (research/experiments/).
Read-only with respect to the application: experiments import MAPNAI's pure modules and read MongoDB, never write.
"""

import json
import math
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = Path(__file__).resolve().parent
RESULTS = EXP_DIR / "results"
DATA = EXP_DIR / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_metadata(script: str, **extra) -> Dict:
    """Provenance stamped into every result file."""
    try:
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True, timeout=10).stdout.strip()
    except Exception:
        commit = None
    return {"script": script, "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": commit, "python": platform.python_version(), **extra}


def write_json(name: str, payload: Dict) -> Path:
    """Write results/<name>; refuses to overwrite an existing file (use a new name instead)."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    if path.exists():
        raise FileExistsError(f"{path} exists; results are never overwritten — pass a new --tag")
    path.write_text(json.dumps(payload, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    return path


def write_csv(name: str, rows: List[Dict]) -> Path:
    import csv
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    if path.exists():
        raise FileExistsError(f"{path} exists; results are never overwritten — pass a new --tag")
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    return path


def wilson(k: int, n: int, z: float = 1.96) -> Optional[List[float]]:
    """Wilson score interval for a binomial proportion k/n."""
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def prf(tp: int, fp: int, fn: int) -> Dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"precision": p, "recall": r, "f1": f}


def percentile(values: Sequence[float], q: float) -> float:
    s = sorted(values)
    if not s:
        return float("nan")
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)


def mongo_db():
    """Read-only use only. Credentials come from the repo's .env and are never printed."""
    from dotenv import dotenv_values
    from pymongo import MongoClient
    env = dotenv_values(ROOT / ".env")
    client = MongoClient(env["MONGO_URI"], serverSelectionTimeoutMS=20000)
    return client[env.get("MONGO_DB_NAME") or "mapnai"]


def utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
