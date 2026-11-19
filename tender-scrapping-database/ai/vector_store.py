"""
FAISS-backed vector store for tender descriptions.

- Builds an index on startup from the AI service's SQLite store.
- Provides top-k similarity search by embedding.
- Rebuilds incrementally when new tenders are added.

If FAISS is not installed (e.g. ARM64 pip issues), falls back to a
pure-Python cosine similarity search. Slower but always works.
"""
import logging
import threading
from typing import Iterable

import numpy as np

logger = logging.getLogger("tender.ai.vector_store")

try:
    import faiss  # type: ignore
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False
    logger.warning("FAISS not installed — using pure-Python fallback.")


class VectorStore:
    def __init__(self, dim: int = 768):
        self.dim = dim
        self._ids: list[int] = []
        self._vectors: list[list[float]] = []
        self._lock = threading.Lock()
        self._index = None
        if HAS_FAISS:
            self._index = faiss.IndexFlatIP(dim)  # inner product (cosine if normalised)

    @property
    def size(self) -> int:
        return len(self._ids)

    def _normalise(self, vec: Iterable[float]) -> np.ndarray:
        arr = np.asarray(list(vec), dtype="float32")
        norm = np.linalg.norm(arr)
        if norm == 0:
            return arr
        return arr / norm

    def add(self, tender_id: int, vector: list[float]) -> None:
        if not vector:
            return
        with self._lock:
            if tender_id in self._ids:
                # replace: FAISS FlatIP doesn't support replace cleanly — skip for simplicity
                return
            vec = self._normalise(vector)
            self._ids.append(tender_id)
            self._vectors.append(vec.tolist())
            if HAS_FAISS and self._index is not None:
                self._index.add(vec.reshape(1, -1))

    def add_batch(self, items: list[tuple[int, list[float]]]) -> None:
        for tid, vec in items:
            self.add(tid, vec)

    def search(self, query_vector: list[float], k: int = 20) -> list[tuple[int, float]]:
        """Return [(tender_id, similarity_score), ...] sorted desc."""
        if not self._ids or not query_vector:
            return []

        q = self._normalise(query_vector)

        if HAS_FAISS and self._index is not None:
            sims, idxs = self._index.search(q.reshape(1, -1), min(k, len(self._ids)))
            out = []
            for sim, idx in zip(sims[0], idxs[0]):
                if idx < 0 or idx >= len(self._ids):
                    continue
                out.append((self._ids[idx], float(sim)))
            return out

        # Fallback: pure-python cosine
        scored = []
        for tid, vec in zip(self._ids, self._vectors):
            v = np.asarray(vec, dtype="float32")
            sim = float(np.dot(q, v))
            scored.append((tid, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def clear(self) -> None:
        with self._lock:
            self._ids = []
            self._vectors = []
            if HAS_FAISS:
                self._index = faiss.IndexFlatIP(self.dim)


_store: VectorStore | None = None


def get_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store