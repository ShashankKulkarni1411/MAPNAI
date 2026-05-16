"""
MAPNAI — utils/deduplicator.py
Cross-source deduplication using SimHash (primary) and MinHash LSH (secondary).
SimHash: Charikar 2002 — detects near-duplicate articles (same story, different wording).
MinHash:  Jaccard similarity via datasketch — catches paraphrase duplicates.

Architecture decision:
  - SimHash fingerprint stored per article in DB.
  - In-memory seen_hashes set for current run (fast O(1) lookup).
  - MongoDB index for cross-run deduplication (persistent).
"""

import re
from typing import Set, Optional
from simhash import Simhash
from datasketch import MinHash, MinHashLSH
from utils.logger import logger


# ── Utility ──────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Tokenize text into 3-gram shingles for SimHash."""
    text = re.sub(r"\s+", " ", text.lower()).strip()
    tokens = text.split()
    # Combine unigrams and bigrams for better fingerprint stability
    unigrams = tokens
    bigrams  = [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)]
    return unigrams + bigrams


def compute_simhash(title: str, body: str) -> str:
    """
    Compute a 64-bit SimHash fingerprint of title + first 500 chars of body.
    Returns hex string (16 chars).
    """
    # Use title + first 500 chars to avoid noise from article footers
    content = (title + " " + body[:500]).strip()
    tokens  = _tokenize(content)
    if not tokens:
        return "0000000000000000"
    sh = Simhash(tokens, f=64)
    return format(sh.value, "016x")


def simhash_distance(hash1: str, hash2: str) -> int:
    """
    Hamming distance between two SimHash hex strings.
    Distance ≤ 3 → near-duplicate (very similar content).
    Distance ≤ 6 → probable duplicate.
    """
    try:
        v1 = int(hash1, 16)
        v2 = int(hash2, 16)
        xor = v1 ^ v2
        return bin(xor).count("1")   # Hamming weight
    except ValueError:
        return 64   # max distance on error → treat as unique


def is_near_duplicate_simhash(new_hash: str, seen_hashes: Set[str], threshold: int = 3) -> bool:
    """
    Check if new_hash is within `threshold` Hamming bits of any seen hash.
    O(n) scan — acceptable for in-memory run-level set (< 50k articles).
    For production at scale, use SimHash index or Pinecone ANN.
    """
    for existing in seen_hashes:
        if simhash_distance(new_hash, existing) <= threshold:
            return True
    return False


# ── MinHash LSH (secondary, catch paraphrase dupes) ──────────

class MinHashDeduplicator:
    """
    Uses datasketch MinHash + LSH for Jaccard-similarity-based deduplication.
    Useful for detecting paraphrased articles (same facts, different words).
    Threshold: Jaccard ≥ 0.5 → duplicate.
    """

    def __init__(self, threshold: float = 0.5, num_perm: int = 128):
        self.threshold = threshold
        self.num_perm  = num_perm
        self.lsh        = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self._count     = 0

    def _make_minhash(self, text: str) -> MinHash:
        m = MinHash(num_perm=self.num_perm)
        words = re.sub(r"\W+", " ", text.lower()).split()
        for word in words:
            m.update(word.encode("utf-8"))
        return m

    def is_duplicate(self, article_id: str, title: str, body: str) -> bool:
        """
        Returns True if this article is a near-duplicate of something already indexed.
        Side-effect: inserts the article into LSH if NOT a duplicate.
        """
        text = (title + " " + body[:500]).strip()
        m    = self._make_minhash(text)
        try:
            result = self.lsh.query(m)
            if result:
                logger.debug(f"MinHash duplicate detected: {article_id[:8]} matches {result[0][:8]}")
                return True
            # Not a duplicate — insert
            key = f"{article_id}_{self._count}"
            self.lsh.insert(key, m)
            self._count += 1
            return False
        except Exception as e:
            logger.warning(f"MinHash error for {article_id[:8]}: {e}")
            return False

    def clear(self):
        """Reset LSH index (e.g., between ingestion runs if memory is a concern)."""
        self.lsh    = MinHashLSH(threshold=self.threshold, num_perm=self.num_perm)
        self._count = 0


# ── Composite Deduplicator ───────────────────────────────────

class ArticleDeduplicator:
    """
    Wraps both SimHash (fast exact/near-exact) and MinHash (paraphrase).
    Usage:
        deduper = ArticleDeduplicator()
        deduper.load_existing_hashes(hashes_from_db)   # seed from DB

        hash_val = deduper.compute_hash(title, body)
        if deduper.is_duplicate(article_id, title, body, hash_val):
            skip()
        else:
            deduper.register(hash_val)
    """

    def __init__(self, simhash_threshold: int = 3, minhash_threshold: float = 0.5):
        self._simhash_threshold = simhash_threshold
        self._seen_simhashes: Set[str] = set()
        self._minhash = MinHashDeduplicator(threshold=minhash_threshold)

    def load_existing_hashes(self, hashes: list[str]):
        """Seed from DB on startup to catch cross-run duplicates."""
        self._seen_simhashes.update(hashes)
        logger.info(f"Deduplicator seeded with {len(hashes)} existing hashes from DB.")

    def compute_hash(self, title: str, body: str) -> str:
        return compute_simhash(title, body)

    def is_duplicate(
        self,
        article_id: str,
        title: str,
        body: str,
        sim_hash: Optional[str] = None,
    ) -> bool:
        """Returns True if article should be dropped as a duplicate."""
        if sim_hash is None:
            sim_hash = self.compute_hash(title, body)

        # Stage 1: SimHash near-duplicate
        if is_near_duplicate_simhash(sim_hash, self._seen_simhashes, self._simhash_threshold):
            logger.debug(f"SimHash duplicate: {article_id[:8]}")
            return True

        # Stage 2: MinHash paraphrase duplicate
        if self._minhash.is_duplicate(article_id, title, body):
            return True

        return False

    def register(self, sim_hash: str):
        """Add hash to seen set after storing article."""
        self._seen_simhashes.add(sim_hash)

    @property
    def seen_count(self) -> int:
        return len(self._seen_simhashes)
