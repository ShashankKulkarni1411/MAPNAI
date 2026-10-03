"""
MAPNAI — personalization/materiality.py
Materiality m of an article (pure), with its auditable components:
    m = Σ w_i·x_i / Σ w_i over the components that exist:
        risk_norm    (w_risk)  = risk_score / risk_scale_max — only when A4 has scored the article
        size_score   (w_size)  = min(1, ln(1+n) / ln(size_log_base))
        first_report (w_first) = 1 for the earliest article of a cluster with ≥ 2 members, else 0
        source_cred  (w_cred)  = cfg.source_cred[source_name], else source_cred_default
An unscored article (no usable A4 risk) is renormalized over size, first_report and source_cred and flagged
`unscored`; its risk_norm is None.
"""

import math
from typing import Dict, Optional


def size_score(n: int, cfg) -> float:
    """Cluster size → [0, 1]: min(1, ln(1+n) / ln(size_log_base)). size_score(10) = 1 with base 11."""
    base = max(float(cfg.size_log_base), 1.000001)
    return min(1.0, math.log1p(max(0, int(n))) / math.log(base))


def risk_norm(raw, cfg) -> Optional[float]:
    """A4 risk_score → [0, 1], or None when it is missing or unusable."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw) / float(cfg.risk_scale_max)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return None if math.isnan(value) else min(1.0, max(0.0, value))


def materiality(article: Dict, cluster_size: int, is_first: bool, cfg) -> Dict:
    """{m, risk_norm, size_score, first_report, source_cred, unscored}, rounded to 6 places."""
    risk = risk_norm(article.get(cfg.risk_field), cfg)
    source_cred = cfg.source_cred.get(article.get(cfg.source_field), cfg.source_cred_default)
    source_cred = min(1.0, max(0.0, float(source_cred)))
    size = size_score(cluster_size, cfg)
    first = 1 if is_first and cluster_size >= 2 else 0

    parts = [(cfg.w_size, size), (cfg.w_first, first), (cfg.w_cred, source_cred)]
    if risk is not None:
        parts.append((cfg.w_risk, risk))
    total_w = sum(w for w, _ in parts)
    score = sum(w * x for w, x in parts) / total_w if total_w > 0 else 0.0
    return {
        "m": round(min(1.0, max(0.0, score)), 6),
        "risk_norm": None if risk is None else round(risk, 6),
        "size_score": round(size, 6),
        "first_report": first,
        "source_cred": round(source_cred, 6),
        "unscored": risk is None,
    }
