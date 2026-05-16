"""
MAPNAI — utils/logger.py
Centralized logging using loguru.
All agents import `logger` from here for consistent formatting.
"""

import sys
import os
from loguru import logger
from config.settings import settings

# ── Remove default loguru handler ───────────────────────────
logger.remove()

# ── Console handler — rich colorized output ──────────────────
logger.add(
    sys.stdout,
    level=settings.log_level,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
        "<level>{message}</level>"
    ),
    colorize=True,
)

# ── File handler — persisted logs ────────────────────────────
os.makedirs(os.path.dirname(settings.log_file), exist_ok=True)
logger.add(
    settings.log_file,
    level="DEBUG",
    rotation="50 MB",
    retention="14 days",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} — {message}",
    enqueue=True,   # thread-safe async write
)

__all__ = ["logger"]
