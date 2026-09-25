"""
vector_store.py — ChromaDB-backed vector store for RepoPilot symbol chunks.

Class: VectorStore
  Wraps a local ChromaDB PersistentClient and exposes upsert / query / clear
  operations over a single "repopilot_symbols" collection.
"""

from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------

try:
    import chromadb  # noqa: F401 — checked at import time
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False


# ---------------------------------------------------------------------------
# VectorStore
# ---------------------------------------------------------------------------

class VectorStore:
    """Local ChromaDB vector store for symbol chunks.

    Parameters
    ----------
    persist_dir:
        Directory on disk where ChromaDB will persist its data.
        Created automatically if it does not exist.
    """

    COLLECTION_NAME = "repopilot_symbols"

    def __init__(self, persist_dir: str = ".repopilot/chroma") -> None:
        if not _CHROMA_AVAILABLE:
            raise ImportError(
                "chromadb is not installed. "
                "Run: pip install chromadb"
            )

        import chromadb as _chromadb

        self._client = _chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.debug(
            "VectorStore initialised (persist_dir=%s, collection=%s)",
            persist_dir,
            self.COLLECTION_NAME,
        )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add_chunks(
        self,
        chunks: list[dict],
        embeddings: list[list[float]],
    ) -> None:
        """Upsert *chunks* with their pre-computed *embeddings*.

        Parameters
        ----------
        chunks:
            List of chunk dicts with keys ``id``, ``text``, ``metadata``.
        embeddings:
            Parallel list of float vectors (one per chunk).
        """
        if not chunks:
            return

        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks length ({len(chunks)}) != embeddings length ({len(embeddings)})"
            )

        ids        = [c["id"]       for c in chunks]
        documents  = [c["text"]     for c in chunks]
        metadatas  = [c["metadata"] for c in chunks]

        # ChromaDB upsert handles both insert and update (idempotent).
        self._collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        logger.debug("Upserted %d chunks into collection.", len(chunks))

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def query(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[dict]:
        """Return the top-*k* nearest neighbours for *query_embedding*.

        Returns
        -------
        list[dict]
            Each element::

                {
                    "id":       str,
                    "text":     str,
                    "metadata": dict,
                    "distance": float,   # lower = more similar (cosine distance)
                    "score":    float,   # 1 - distance, clamped to [0, 1]
                }
        """
        if self.collection_size() == 0:
            return []

        effective_k = min(top_k, self.collection_size())
        raw = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=effective_k,
            include=["documents", "metadatas", "distances"],
        )

        results: list[dict] = []
        for idx in range(len(raw["ids"][0])):
            distance = float(raw["distances"][0][idx])
            # Cosine distance ∈ [0, 2]; normalise score to [0, 1].
            score = max(0.0, min(1.0, 1.0 - distance))
            results.append(
                {
                    "id":       raw["ids"][0][idx],
                    "text":     raw["documents"][0][idx],
                    "metadata": raw["metadatas"][0][idx],
                    "distance": distance,
                    "score":    score,
                }
            )

        return results

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def collection_size(self) -> int:
        """Return the number of documents currently in the collection."""
        return self._collection.count()

    def clear(self) -> None:
        """Delete and recreate the collection (for full re-indexing)."""
        self._client.delete_collection(self.COLLECTION_NAME)
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Collection '%s' cleared and recreated.", self.COLLECTION_NAME)
