"""
MAPNAI — utils/deduplicator.py
Cross-source deduplication using SimHash (primary) and MinHash LSH (secondary).
SimHash: Charikar 2002 — detects near-duplicate articles (same story, different wording).
MinHash:  Jaccard similarity via datasketch — catches paraphrase duplicates.

Architecture decision:
  - SimHash fingerprint stored per article in DB.
  - Banded in-memory index of the fingerprints (Manku et al. 2007): the 64 bits are split into threshold + 1
    bands; two fingerprints within `threshold` bits of each other agree exactly on at least one band (pigeonhole),
    so a lookup compares only the fingerprints sharing a band with the new one. Same answer as a linear scan, in
    near-constant time (the linear scan cost 63 ms per article at 100k fingerprints).
  - Seeded from the DB (recent fingerprints) for cross-run deduplication.
  - A duplicate lookup can say *which* article it matched (find_duplicate), so the caller can record the
    duplicate as a sighting of the original instead of losing the coverage signal (continousexplanation.md §5.5).
"""

import re
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union
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
    O(n) linear scan — kept as the reference implementation; ArticleDeduplicator uses SimHashIndex.
    """
    for existing in seen_hashes:
        if simhash_distance(new_hash, existing) <= threshold:
            return True
    return False


def _parse_hash(value: str) -> Optional[int]:
    try:
        v = int(value, 16)
    except (TypeError, ValueError):
        return None
    return v if 0 <= v < (1 << 64) else None


class SimHashIndex:
    """
    Exact near-duplicate lookup over 64-bit SimHash fingerprints: find a stored fingerprint within `threshold`
    bits of a query. The fingerprint is split into threshold + 1 contiguous bands; if two fingerprints differ in at
    most `threshold` bits, those bits fall into at most `threshold` bands, so at least one band is identical.
    Only fingerprints sharing a band with the query are compared. Fingerprints that aren't valid 64-bit hex are
    ignored (a linear scan would never match them either).
    """

    def __init__(self, threshold: int = 3):
        self.threshold = max(0, int(threshold))
        n = self.threshold + 1
        width, extra = divmod(64, n)
        self._bands: List[Tuple[int, int]] = []        # (shift, mask) per band
        shift = 0
        for i in range(n):
            w = width + (1 if i < extra else 0)
            self._bands.append((shift, (1 << w) - 1))
            shift += w
        self._buckets: Dict[Tuple[int, int], Set[int]] = {}
        self._hex: Dict[int, str] = {}

    def __len__(self) -> int:
        return len(self._hex)

    def _keys(self, v: int):
        for i, (shift, mask) in enumerate(self._bands):
            yield (i, (v >> shift) & mask)

    def add(self, value: str) -> bool:
        v = _parse_hash(value)
        if v is None or v in self._hex:
            return False
        self._hex[v] = value
        for key in self._keys(v):
            self._buckets.setdefault(key, set()).add(v)
        return True

    def find(self, value: str) -> Optional[str]:
        """A stored fingerprint within threshold bits of `value` (the closest; ties → the smallest), else None."""
        v = _parse_hash(value)
        if v is None:
            return None
        candidates: Set[int] = set()
        for key in self._keys(v):
            candidates |= self._buckets.get(key, set())
        best = None
        for c in candidates:
            d = bin(v ^ c).count("1")
            if d <= self.threshold and (best is None or (d, c) < best):
                best = (d, c)
        return self._hex[best[1]] if best else None


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

    def find(self, article_id: str, title: str, body: str) -> Optional[str]:
        """
        The article_id of an indexed near-duplicate, else None. Side-effect: inserts the article into the LSH
        when it is NOT a duplicate. A lookup error counts as "not a duplicate".
        """
        text = (title + " " + body[:500]).strip()
        m    = self._make_minhash(text)
        try:
            result = self.lsh.query(m)
            if result:
                match = sorted(result)[0].rsplit("_", 1)[0]
                logger.debug(f"MinHash duplicate detected: {article_id[:8]} matches {match[:8]}")
                return match
            # Not a duplicate — insert
            key = f"{article_id}_{self._count}"
            self.lsh.insert(key, m)
            self._count += 1
            return None
        except Exception as e:
            logger.warning(f"MinHash error for {article_id[:8]}: {e}")
            return None

    def is_duplicate(self, article_id: str, title: str, body: str) -> bool:
        """
        Returns True if this article is a near-duplicate of something already indexed.
        Side-effect: inserts the article into LSH if NOT a duplicate.
        """
        return self.find(article_id, title, body) is not None

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
        deduper.load_existing_hashes(docs_from_db)    # hash strings, or {dedup_hash, article_id, source_name}

        hash_val = deduper.compute_hash(title, body)
        match = deduper.find_duplicate(article_id, title, body, hash_val)
        if match:
            record_sighting(match["article_id"], source)   # or skip()
        else:
            deduper.register(hash_val, article_id, source)
    """

    def __init__(self, simhash_threshold: int = 3, minhash_threshold: float = 0.5):
        self._simhash_threshold = simhash_threshold
        self._seen_simhashes: Set[str] = set()
        self._index = SimHashIndex(simhash_threshold)
        self._owner: Dict[str, str] = {}          # fingerprint → article_id of the first article that had it
        self._sources: Dict[str, str] = {}        # article_id → source_name
        self._minhash = MinHashDeduplicator(threshold=minhash_threshold)

    def __len__(self) -> int:
        return len(self._seen_simhashes)

    def load_existing_hashes(self, hashes: Iterable[Union[str, Dict]]):
        """Seed from DB on startup to catch cross-run duplicates. Accepts hash strings or stored docs."""
        n = 0
        for item in hashes:
            if isinstance(item, dict):
                if item.get("dedup_hash"):
                    self.register(item["dedup_hash"], item.get("article_id"), item.get("source_name"))
                    n += 1
            elif item:
                self.register(item)
                n += 1
        logger.info(f"Deduplicator seeded with {n} existing hashes from DB.")

    def compute_hash(self, title: str, body: str) -> str:
        return compute_simhash(title, body)

    def find_duplicate(
        self,
        article_id: str,
        title: str,
        body: str,
        sim_hash: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        {"article_id": the matched article (None when the fingerprint came without an id), "source": its source
        (None if unknown), "method": "simhash" | "minhash"} when the article is a duplicate, else None.
        Side-effect (MinHash stage): a non-duplicate is inserted into the LSH index.
        """
        if sim_hash is None:
            sim_hash = self.compute_hash(title, body)

        # Stage 1: SimHash near-duplicate
        hit = self._index.find(sim_hash)
        if hit is not None:
            logger.debug(f"SimHash duplicate: {article_id[:8]}")
            owner = self._owner.get(hit)
            return {"article_id": owner, "source": self._sources.get(owner) if owner else None, "method": "simhash"}

        # Stage 2: MinHash paraphrase duplicate
        owner = self._minhash.find(article_id, title, body)
        if owner is not None:
            return {"article_id": owner, "source": self._sources.get(owner), "method": "minhash"}
        return None

    def is_duplicate(
        self,
        article_id: str,
        title: str,
        body: str,
        sim_hash: Optional[str] = None,
    ) -> bool:
        """Returns True if article should be dropped as a duplicate."""
        return self.find_duplicate(article_id, title, body, sim_hash) is not None

    def register(self, sim_hash: str, article_id: Optional[str] = None, source: Optional[str] = None):
        """Add hash to seen set after storing article (with the article and its source, for sightings)."""
        self._seen_simhashes.add(sim_hash)
        self._index.add(sim_hash)
        if article_id:
            self._owner.setdefault(sim_hash, article_id)
            if source:
                self._sources.setdefault(article_id, source)

    def source_of(self, article_id: str) -> Optional[str]:
        return self._sources.get(article_id)
