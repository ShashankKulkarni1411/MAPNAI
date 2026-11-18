"""
MAPNAI — agents/query_llm.py
Modular LLM Interface Layer for Query Agent (Agent 5).

Provides:
  - QueryLLM: Abstract base class for LLM backends
  - GroqQueryLLM: High-throughput cloud LLM inference using Groq (LLaMA 3.3)
  - CustomModelQueryLLM: Drop-in interface for locally trained / hosted HuggingFace models
"""

import os
import re
from typing import Optional, Dict, Any, List, Tuple
from config.settings import settings
from utils.logger import logger
from utils.groq_client import chat_completion, get_groq_client


SYSTEM_PROMPT = """You are the Query Agent (Agent 5) in the MAPNAI news intelligence pipeline.
You answer questions about news articles strictly based on the article summaries provided to you.
Do not invent facts outside the provided summaries.
If the answer cannot be found in the summaries, say so clearly.
Cite sources with markers like [2], the number of the Source Article, after each sentence that states a fact.
Do not mention article IDs. Write two to four plain sentences: no tables, headings or lists.
Keep answers concise and factual."""


class QueryLLM:
    """Abstract base class for all Query Agent LLM backends."""

    def generate_answer(self, question: str, context: str) -> str:
        """
        Generate a grounded answer for a question given the retrieved article context.

        Args:
            question: The natural language question from user.
            context: Formatted string containing relevant article summaries and metadata.

        Returns:
            Grounded natural language answer string.
        """
        raise NotImplementedError("Subclasses must implement generate_answer")


class GroqQueryLLM(QueryLLM):
    """
    Groq-powered LLM answering engine.
    Uses ultra-fast LLaMA 3.3 models on Groq LPUs.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ):
        # Ask's own model (QUERY_GRAPH_MODEL), like the query graph, so it has its own daily token limit
        self.model_name = model_name or settings.query_graph_model or settings.groq_model
        self.api_key = api_key or settings.groq_api_key or os.environ.get("GROQ_API_KEY", "")
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate_answer(self, question: str, context: str) -> str:
        """Generate grounded answer using Groq API with fallback for offline environments."""
        if not context or not context.strip():
            return "No relevant article summaries were provided to answer this question."

        user_content = (
            f"Context:\n{context}\n\n"
            f"Question: {question}\n\n"
            "Please provide a factual, grounded answer based strictly on the above context, citing the "
            "Source Article numbers as [n] markers."
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            answer = chat_completion(
                messages=messages,
                model=self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                api_key=self.api_key,
            )
            if answer and answer.strip():
                return answer.strip()
        except Exception as e:
            logger.warning(f"[GroqQueryLLM] Live LLM call failed: {e}. Utilizing fallback generation.")

        # Offline / Mock Fallback when Groq API key is absent or unreachable
        return self._offline_fallback_answer(question, context)

    def _offline_fallback_answer(self, question: str, context: str) -> str:
        """Groq unavailable: quote the source sentences closest to the question (see extractive_answer)."""
        return extractive_answer(question, context)


# ── Extractive fallback (no LLM) ─────────────────────────────

_BLOCK = re.compile(r"\[Source Article (\d+) - ID: [^\]]*\]\n(.*?)(?=\n\[Source Article \d+ - ID: |\Z)", re.S)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'‘“A-Z0-9])")
_WORD = re.compile(r"[a-z0-9]+")
_ABOUT = re.compile(r"\s*\(about: .*\)\s*$", re.S)
_FALLBACK_SENTENCES = 3          # quoted at most
_FALLBACK_PER_ARTICLE = 2
_FALLBACK_MIN_SIMILARITY = 0.35  # cosine, sentence-transformer embeddings
_FALLBACK_MIN_OVERLAP = 0.2      # share of the question's words, when the embedding model is unavailable
FALLBACK_PREFIX = "The AI answer isn't available right now. Closest lines from the stories:"
FALLBACK_NOTHING = ("The AI answer isn't available right now, and no line in the stories answers this directly. "
                    "The closest stories are listed below.")


def _field(block: str, name: str) -> str:
    match = re.search(rf"^{name}: (.*)$", block, re.M)
    return match.group(1).strip() if match else ""


def _source_sentences(context: str) -> List[Tuple[int, str]]:
    """(source index, sentence) from each block's summaries, as QueryAgent._format_context lays them out."""
    out: List[Tuple[int, str]] = []
    for idx, block in _BLOCK.findall(context):
        text = _field(block, "Detailed Summary") or _field(block, "Short Summary")
        seen = set()
        for sent in _SENTENCE_SPLIT.split(text):
            sent = " ".join(sent.split())
            if 30 <= len(sent) <= 400 and sent.lower() not in seen:
                seen.add(sent.lower())
                out.append((int(idx), sent))
    return out


def _similarities(question: str, sentences: List[str]) -> Tuple[List[float], float]:
    """Cosine similarity with the embedding model behind the FAISS store; word overlap if it can't load."""
    try:
        from storage.faiss_store import _get_model
        model = _get_model()
        if model is not None:
            vecs = model.encode([question] + sentences, normalize_embeddings=True)
            return [float(vecs[0] @ v) for v in vecs[1:]], _FALLBACK_MIN_SIMILARITY
    except Exception as e:
        logger.warning(f"[QueryLLM] Embedding model unavailable for the fallback ({e}); using word overlap.")
    q_words = {w for w in _WORD.findall(question.lower()) if len(w) > 2}
    scores = [len(q_words & set(_WORD.findall(s.lower()))) / max(1, len(q_words)) for s in sentences]
    return scores, _FALLBACK_MIN_OVERLAP


def extractive_answer(question: str, context: str) -> str:
    """
    The no-LLM answer: up to three summary sentences closest to the question, each cited [n] (its source), at
    most two per article. When none is close enough it says so instead of quoting an unrelated story.
    """
    candidates = _source_sentences(context)
    if not candidates:
        return FALLBACK_NOTHING
    # The story title the app adds ("(about: …)") would pull every sentence of that story equally close.
    core = _ABOUT.sub("", question).strip() or question
    scores, floor = _similarities(core, [s for _, s in candidates])

    picked: List[Tuple[int, str]] = []
    per_article: Dict[int, int] = {}
    for score, (idx, sent) in sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True):
        if score < floor or len(picked) == _FALLBACK_SENTENCES:
            break
        if per_article.get(idx, 0) < _FALLBACK_PER_ARTICLE:
            per_article[idx] = per_article.get(idx, 0) + 1
            picked.append((idx, sent))
    if not picked:
        return FALLBACK_NOTHING
    return FALLBACK_PREFIX + "\n\n" + " ".join(f"{sent} [{idx}]" for idx, sent in picked)


class CustomModelQueryLLM(QueryLLM):
    """
    Placeholder and integration template for future custom fine-tuned ML models.

    =============================================================================
    HOW TO IMPLEMENT A CUSTOM LOCAL MODEL (e.g., Mistral, Llama, Falcon, Qwen):
    =============================================================================
    1. Save your fine-tuned weights or checkpoint under the `models/` directory:
       e.g., `models/mapnai-qa-mistral-7b/` or `models/mapnai-rag-llm/`

    2. In `__init__`:
       - Load tokenizer:
           from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
           import torch
           self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
           self.model = AutoModelForCausalLM.from_pretrained(
               self.model_path,
               torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
               device_map="auto" if torch.cuda.is_available() else None,
           )
           self.generator = pipeline(
               "text-generation",
               model=self.model,
               tokenizer=self.tokenizer,
               max_new_tokens=512,
               temperature=0.1,
           )

    3. In `generate_answer(question, context)`:
       - Format prompt with chat template:
           prompt = f"<s>[INST] <<SYS>>\\n{SYSTEM_PROMPT}\\n<</SYS>>\\n\\nContext:\\n{context}\\n\\nQuestion: {question} [/INST]"
       - Run inference:
           output = self.generator(prompt)
           return output[0]["generated_text"].replace(prompt, "").strip()
    =============================================================================
    """

    def __init__(self, model_path: str = "models/mapnai-query-model"):
        self.model_path = model_path
        self._model = None
        self._tokenizer = None
        self._is_loaded = False
        logger.info(f"[CustomModelQueryLLM] Configured placeholder with path: {self.model_path}")

    def load_model(self):
        """Lazy loader for custom ML model from models/ directory."""
        if not os.path.exists(self.model_path):
            logger.warning(
                f"[CustomModelQueryLLM] Model directory not found at '{self.model_path}'. "
                "Running in simulated mode. Place custom model weights in models/ to enable."
            )
            return

        try:
            from transformers import AutoTokenizer, AutoModelForCausalLM
            logger.info(f"[CustomModelQueryLLM] Loading weights from {self.model_path}...")
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            self._model = AutoModelForCausalLM.from_pretrained(self.model_path)
            self._is_loaded = True
            logger.info("[CustomModelQueryLLM] Custom model loaded successfully.")
        except Exception as e:
            logger.error(f"[CustomModelQueryLLM] Error loading custom model: {e}")

    def generate_answer(self, question: str, context: str) -> str:
        """
        Generate answer using local model weights or fallback message if weights are unpopulated.
        """
        if not self._is_loaded:
            # Check if weights are available on disk on demand
            self.load_model()

        if self._is_loaded and self._model and self._tokenizer:
            try:
                prompt = (
                    f"{SYSTEM_PROMPT}\n\n"
                    f"Context:\n{context}\n\n"
                    f"Question: {question}\n\n"
                    "Answer:"
                )
                inputs = self._tokenizer(prompt, return_tensors="pt")
                outputs = self._model.generate(
                    **inputs,
                    max_new_tokens=256,
                    temperature=0.1,
                    do_sample=False,
                )
                return self._tokenizer.decode(outputs[0], skip_special_tokens=True).replace(prompt, "").strip()
            except Exception as e:
                logger.error(f"[CustomModelQueryLLM] Inference error: {e}")

        # Simulated response if model weights are not loaded yet
        return (
            f"[CustomModel Placeholder] Answer generated based on context: "
            f"Regarding '{question}', the articles indicate relevant developments. "
            f"(To use full local model inference, train and place weights in {self.model_path})"
        )
