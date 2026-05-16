"""
Groq LLM client via the OpenAI-compatible Python SDK.
"""

from typing import Optional, Tuple

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from config.settings import settings
from utils.logger import logger

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"


def init_groq_llm(agent_label: str, task: str) -> Tuple[Optional[object], Optional[str]]:
    """Return (client, model_name) for Groq, or (None, None) to use fallback logic."""
    if OpenAI is None:
        logger.warning(
            f"{agent_label} openai package not installed (Groq SDK). "
            f"Run: pip install openai. {task} will fallback."
        )
        return None, None
    if not settings.groq_api_key:
        logger.warning(f"{agent_label} GROQ_API_KEY missing in .env. {task} will fallback.")
        return None, None

    client = OpenAI(api_key=settings.groq_api_key, base_url=GROQ_BASE_URL)
    logger.info(f"{agent_label} Using Groq model {GROQ_MODEL}.")
    return client, GROQ_MODEL
