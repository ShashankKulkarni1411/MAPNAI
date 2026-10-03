"""
MAPNAI — storage/pers_vector_store.py
The personalization FAISS index (PERSONALIZATION_PLAN.md C5): the same FAISSStore class with its own files
(data/pers_faiss_index + data/pers_faiss_metadata.pkl), synced from Mongo by the clustering job.
The pipeline's data/faiss_index is never written.

Row i ↔ metadata[i]["article_id"]; when an id occurs twice the last row wins. Vectors are L2-normalised,
so inner product = cosine. Reads (vectors_for, search_vector, cosine) never load the embedding model.
"""

import os
import pickle
from typing import Dict, Iterable, List, Optional, Set, Tuple

import numpy as np

from config.personalization import pers_settings
from storage.faiss_store import FAISSStore, _get_faiss
from utils.logger import logger


class PersVectorStore(FAISSStore):
    def __init__(self, cfg=None, index_path: str = None, metadata_path: str = None):
        self.cfg = cfg or pers_settings
        super().__init__(
            index_path=index_path or self.cfg.pers_faiss_index_path,
            metadata_path=metadata_path or self.cfg.pers_faiss_metadata_path,
        )
        self._rows: Optional[Dict[str, int]] = None

    # ── Reads ────────────────────────────────────────────────

    def _row_by_id(self) -> Dict[str, int]:
        if self._rows is None:
            self._rows = {m["article_id"]: i for i, m in enumerate(self._metadata) if m.get("article_id")}
        return self._rows

    def indexed_article_ids(self) -> Set[str]:
        return set(self._row_by_id())

    def vectors_for(self, ids: Iterable[str]) -> Dict[str, np.ndarray]:
        """article_id → (dim,) vector for the ids present in the index."""
        rows = self._row_by_id()
        if self._index is None:
            return {}
        return {a: self._index.reconstruct(rows[a]) for a in dict.fromkeys(ids) if a in rows}

    def search_vector(self, vec: np.ndarray, k: int) -> List[Tuple[str, float]]:
        """Top-k (article_id, cosine) for a vector, best first."""
        if self._index is None or self._index.ntotal == 0 or k <= 0:
            return []
        query = np.asarray(vec, dtype=np.float32).reshape(1, -1)
        scores, indices = self._index.search(query, min(k, self._index.ntotal))
        return [
            (self._metadata[i]["article_id"], float(s))
            for s, i in zip(scores[0], indices[0])
            if 0 <= i < len(self._metadata)
        ]

    def cosine(self, a_id: str, b_id: str) -> Optional[float]:
        vecs = self.vectors_for([a_id, b_id])
        if a_id not in vecs or b_id not in vecs:
            return None
        return float(np.dot(vecs[a_id], vecs[b_id]))

    # ── Writes ───────────────────────────────────────────────

    def add_docs(self, docs: List[Dict]) -> int:
        """
        Embed Mongo article docs ({article_id, title, body, domain, url, source_name, published_at}) with the
        pipeline's recipe f"{title}. {body[:300]}" and append them. Returns rows added (0 if embedding fails).
        """
        docs = [d for d in docs if d.get("article_id")]
        if not docs or self._index is None:
            return 0
        vecs = self._embed_texts([f"{d.get('title') or ''}. {(d.get('body') or '')[:300]}" for d in docs])
        if vecs is None:
            return 0
        start = len(self._metadata)
        self._index.add(vecs)
        for i, d in enumerate(docs):
            self._metadata.append({
                "faiss_idx": start + i,
                "article_id": d["article_id"],
                "title": d.get("title"),
                "domain": d.get("domain"),
                "url": d.get("url"),
                "source": d.get("source_name"),
                "published": d.get("published_at") or "",
            })
        self._rows = None
        return len(docs)

    def save(self):
        """Write to temp files, then rename, so a reader never sees a half-written index."""
        faiss = _get_faiss()
        if faiss is None or self._index is None:
            return
        tmp_index, tmp_meta = f"{self.index_path}.tmp", f"{self.metadata_path}.tmp"
        faiss.write_index(self._index, tmp_index)
        with open(tmp_meta, "wb") as fh:
            pickle.dump(self._metadata, fh)
        os.replace(tmp_index, self.index_path)
        os.replace(tmp_meta, self.metadata_path)
        logger.info(f"[PersFAISS] Saved {self._index.ntotal} vectors to {self.index_path}")

    def sync_from_mongo(self, docs: List[Dict], batch: int = 256) -> int:
        """Add the docs that aren't indexed yet, in batches, and save. Returns rows added."""
        indexed = self.indexed_article_ids()
        todo = [d for d in docs if d.get("article_id") and d["article_id"] not in indexed]
        added = 0
        for i in range(0, len(todo), batch):
            added += self.add_docs(todo[i:i + batch])
        if added:
            self.save()
        return added

    def reset(self) -> None:
        """Empty the in-memory index (the files are replaced on the next save)."""
        faiss = _get_faiss()
        if faiss is not None:
            self._index = faiss.IndexFlatIP(self.EMBEDDING_DIM)
        self._metadata, self._rows = [], None
