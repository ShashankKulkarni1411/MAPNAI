"""
MAPNAI — utils/ollama_client.py
Local LLM client for Ollama's OpenAI-compatible endpoint (default http://localhost:11434/v1).

Used by Agent 4 as a quota-free fallback (or primary, with RISK_BACKEND=ollama). The OpenAI-compatible
endpoint ignores per-request options such as num_ctx, so the context window is set on the model itself:
the default RISK_OLLAMA_MODEL "mapnai-risk" is built from scripts/ollama/Modelfile.risk
(`ollama create mapnai-risk -f scripts/ollama/Modelfile.risk`).
"""

from typing import Optional, Tuple

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from config.settings import settings
from utils.logger import logger


def init_ollama_llm(agent_label: str, task: str, model: str) -> Tuple[Optional[object], Optional[str]]:
    """Return (client, model_name) for the local Ollama server, or (None, None) when unusable.

    Creating the client makes no request; a server that is down surfaces as an error on the first call.
    """
    if OpenAI is None:
        logger.warning(f"{agent_label} openai package not installed; local {task} via Ollama unavailable.")
        return None, None
    if not model:
        return None, None
    client = OpenAI(
        api_key="ollama",                       # required by the SDK, ignored by Ollama
        base_url=settings.ollama_base_url,
        timeout=settings.risk_ollama_timeout_seconds,
        max_retries=0,                          # a local server that is down won't recover in a retry
    )
    logger.info(f"{agent_label} Local fallback: Ollama model {model} at {settings.ollama_base_url}.")
    return client, model
