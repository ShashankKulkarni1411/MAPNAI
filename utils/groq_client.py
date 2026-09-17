"""
MAPNAI — utils/groq_client.py
Groq LLM Client Singleton and utilities.
Provides centralized initialization and query execution for Groq's high-speed LLM inference.

Two interfaces are exposed for compatibility with different agents:
  - init_groq_llm(): returns an OpenAI-SDK-compatible client via Groq's
    OpenAI-compatible endpoint (used by agent2/3/4).
  - get_groq_client() / chat_completion(): returns a native Groq SDK client
    singleton (used by the query agents).
"""

import os
from typing import Optional, Tuple, List, Dict, Any

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from config.settings import settings
from utils.logger import logger

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"

_GROQ_CLIENT = None


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


def get_groq_client(api_key: Optional[str] = None):
    """
    Get or initialize the singleton Groq client.
    Prefers passed api_key, falls back to settings.groq_api_key or GROQ_API_KEY environment variable.
    """
    global _GROQ_CLIENT
    resolved_key = api_key or settings.groq_api_key or os.environ.get("GROQ_API_KEY", "")

    if _GROQ_CLIENT is not None and not api_key:
        return _GROQ_CLIENT

    try:
        from groq import Groq
        if not resolved_key:
            logger.warning("[GroqClient] No GROQ_API_KEY provided in settings or environment.")
            return None

        client = Groq(api_key=resolved_key)
        if not api_key:
            _GROQ_CLIENT = client
        logger.info("[GroqClient] Groq client initialized successfully.")
        return client
    except ImportError:
        logger.error("[GroqClient] groq package is not installed. Run: pip install groq")
        return None
    except Exception as e:
        logger.error(f"[GroqClient] Failed to initialize Groq client: {e}")
        return None


def chat_completion(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    api_key: Optional[str] = None,
) -> Optional[str]:
    """
    Convenience function to perform a chat completion with Groq.
    Returns response text or None if failed.
    """
    client = get_groq_client(api_key=api_key)
    if client is None:
        return None

    model_name = model or settings.groq_model or "llama-3.3-70b-versatile"

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if response.choices and len(response.choices) > 0:
            return response.choices[0].message.content.strip()
        return None
    except Exception as e:
        logger.error(f"[GroqClient] Chat completion error with model {model_name}: {e}")
        return None
