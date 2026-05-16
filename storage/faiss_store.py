"""
MAPNAI — storage/faiss_store.py
FAISS Vector Store
Stores article embeddings for semantic similarity search.
Uses sentence-transformers (all-MiniLM-L6-v2) for fast CPU-based embeddings.
Persists index + metadata to disk between runs.
"""

import os
import pickle
from typing import List, Dict, Optional, Tuple
import numpy as np

from config.settings import settings
from utils.models import ProcessedArticle
from utils.logger import logger


def _load_sentence_transformer():
    """Lazy-load sentence transformer model."""
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(settings.embedding_model)
        logger.info(f"[FAISS] Embedding model loaded: {settings.embedding_model}")
        return model
    except ImportError:
        logger.error("[FAISS] sentence-transformers not installed. Run: pip install sentence-transformers")
        return None
    except Exception as e:
        logger.error(f"[FAISS] Model load error: {e}")
        return None


def _load_faiss():
    """Lazy-load faiss."""
    try:
        import faiss
        return faiss
    except ImportError:
        logger.error("[FAISS] faiss-cpu not installed. Run: pip install faiss-cpu")
        return None


_MODEL = None
_FAISS = None


def _get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = _load_sentence_transformer()
    return _MODEL


def _get_faiss():
    global _FAISS
    if _FAISS is None:
        _FAISS = _load_faiss()
    return _FAISS


class FAISSStore:
    """
    FAISS-backed vector store for article semantic search.
    Index type: IndexFlatIP (inner product = cosine similarity on normalized vectors)
    Metadata: stored in parallel list (article_id, title, domain, url)
    Persistence: index saved to .faiss file, metadata to .pkl file
    """

    EMBEDDING_DIM = 384   # all-MiniLM-L6-v2 output dimension

    def __init__(
        self,
        index_path: str = None,
        metadata_path: str = None,
    ):
        self.index_path    = index_path or settings.faiss_index_path
        self.metadata_path = metadata_path or settings.faiss_metadata_path

        self._index    = None
        self._metadata: List[Dict] = []   # parallel to FAISS vectors

        self._ensure_dirs()
        self._load_or_create()

    def _ensure_dirs(self):
        for path in [self.index_path, self.metadata_path]:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def _load_or_create(self):
        """Load existing index from disk, or create a new one."""
        faiss = _get_faiss()
        if faiss is None:
            return

        if os.path.exists(self.index_path) and os.path.exists(self.metadata_path):
            try:
                self._index = faiss.read_index(self.index_path)
                with open(self.metadata_path, "rb") as f:
                    self._metadata = pickle.load(f)
                logger.info(
                    f"[FAISS] Loaded existing index: "
                    f"{self._index.ntotal} vectors from {self.index_path}"
                )
                return
            except Exception as e:
                logger.warning(f"[FAISS] Could not load existing index: {e}. Creating new.")

        # Create new flat inner-product index
        self._index    = faiss.IndexFlatIP(self.EMBEDDING_DIM)
        self._metadata = []
        logger.info(f"[FAISS] New index created (dim={self.EMBEDDING_DIM})")

    def _embed_texts(self, texts: List[str]) -> Optional[np.ndarray]:
        """
        Generate normalized embeddings for a list of texts.
        Normalization → inner product == cosine similarity.
        """
        model = _get_model()
        faiss = _get_faiss()
        if model is None or faiss is None:
            return None

        try:
            embeddings = model.encode(
                texts,
                batch_size=32,
                show_progress_bar=False,
                normalize_embeddings=True,   # L2-normalize → cosine via IP
                convert_to_numpy=True,
            )
            return embeddings.astype(np.float32)
        except Exception as e:
            logger.error(f"[FAISS] Embedding error: {e}")
            return None

    def add_articles(self, articles: List[ProcessedArticle]) -> int:
        """
        Embed and add articles to the FAISS index.
        Returns number of vectors added.
        """
        if not articles:
            return 0

        faiss = _get_faiss()
        if faiss is None or self._index is None:
            logger.error("[FAISS] Store not initialized — cannot add articles.")
            return 0

        # Build text for embedding: title + first 300 chars of body
        texts = [
            f"{a.title}. {a.body[:300]}" for a in articles
        ]

        embeddings = self._embed_texts(texts)
        if embeddings is None:
            return 0

        try:
            self._index.add(embeddings)
        except Exception as e:
            logger.error(f"[FAISS] Index add error: {e}")
            return 0

        # Update metadata — parallel to vectors
        start_idx = len(self._metadata)
        for i, article in enumerate(articles):
            meta = {
                "faiss_idx":  start_idx + i,
                "article_id": article.article_id,
                "title":      article.title,
                "domain":     article.domain.value,
                "url":        article.url,
                "source":     article.source_name,
                "published":  article.published_at.isoformat() if article.published_at else "",
            }
            self._metadata.append(meta)
            article.embedding_id = str(start_idx + i)

        added = len(articles)
        logger.info(f"[FAISS] Added {added} vectors. Total index size: {self._index.ntotal}")
        return added

    def search(
        self,
        query: str,
        top_k: int = 10,
        domain_filter: str = None,
    ) -> List[Dict]:
        """
        Semantic similarity search.
        Returns top_k metadata dicts sorted by cosine similarity.
        Optionally filter by domain.
        """
        if self._index is None or self._index.ntotal == 0:
            return []

        embeddings = self._embed_texts([query])
        if embeddings is None:
            return []

        # Search top_k * 3 to allow for domain filtering
        search_k = top_k * 3 if domain_filter else top_k
        search_k = min(search_k, self._index.ntotal)

        try:
            scores, indices = self._index.search(embeddings, search_k)
        except Exception as e:
            logger.error(f"[FAISS] Search error: {e}")
            return []

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            if idx >= len(self._metadata):
                continue
            meta = self._metadata[idx].copy()
            meta["similarity_score"] = float(score)

            if domain_filter and meta.get("domain") != domain_filter:
                continue

            results.append(meta)
            if len(results) >= top_k:
                break

        return results

    def save(self):
        """Persist index and metadata to disk."""
        faiss = _get_faiss()
        if faiss is None or self._index is None:
            return

        try:
            faiss.write_index(self._index, self.index_path)
            with open(self.metadata_path, "wb") as f:
                pickle.dump(self._metadata, f)
            logger.info(
                f"[FAISS] Saved index ({self._index.ntotal} vectors) to {self.index_path}"
            )
        except Exception as e:
            logger.error(f"[FAISS] Save error: {e}")

    @property
    def total_vectors(self) -> int:
        return self._index.ntotal if self._index else 0
