"""
vector_store.py — in-memory keyword/TF-IDF store for RepoPilot symbol chunks.

Keeps the exact same public interface as the original ChromaDB-backed version
so rag_chain.py requires zero changes.  Uses pure-Python cosine similarity
over the TF-IDF vectors produced by embedder.py.

ChromaDB is no longer required at runtime.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# VectorStore
# ---------------------------------------------------------------------------

class VectorStore:
    """In-memory vector store using dot-product cosine similarity.

    Parameters
    ----------
    persist_dir:
        Accepted for API compatibility; ignored (no disk persistence).
    """

    COLLECTION_NAME = "repopilot_symbols"

    def __init__(self, persist_dir: str = ".repopilot/chroma") -> None:
        # persist_dir kept for interface compatibility — not used
        self._ids:        list[str]         = []
        self._documents:  list[str]         = []
        self._metadatas:  list[dict]        = []
        self._embeddings: list[list[float]] = []
        logger.debug("VectorStore initialised (in-memory, no ChromaDB)")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add_chunks(
        self,
        chunks: list[dict],
        embeddings: list[list[float]],
    ) -> None:
        """Upsert chunks with their pre-computed embeddings.

        Existing entries with the same ``id`` are replaced.
        """
        if not chunks:
            return
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks length ({len(chunks)}) != embeddings length ({len(embeddings)})"
            )

        # Build an index map for O(1) upsert lookups
        existing = {cid: i for i, cid in enumerate(self._ids)}

        for chunk, vec in zip(chunks, embeddings):
            cid = chunk["id"]
            if cid in existing:
                idx = existing[cid]
                self._documents[idx]  = chunk["text"]
                self._metadatas[idx]  = chunk["metadata"]
                self._embeddings[idx] = vec
            else:
                self._ids.append(cid)
                self._documents.append(chunk["text"])
                self._metadatas.append(chunk["metadata"])
                self._embeddings.append(vec)

        logger.debug("Upserted %d chunks (total=%d).", len(chunks), len(self._ids))

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def query(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[dict]:
        """Return the top-*k* nearest chunks by cosine similarity.

        Returns
        -------
        list[dict]
            Each element::

                {
                    "id":       str,
                    "text":     str,
                    "metadata": dict,
                    "distance": float,   # 1 - cosine_similarity
                    "score":    float,   # cosine_similarity, clamped [0, 1]
                }
        """
        if not self._embeddings:
            return []

        q = query_embedding
        q_norm = math.sqrt(sum(v * v for v in q)) or 1.0

        scores: list[tuple[float, int]] = []
        for idx, vec in enumerate(self._embeddings):
            dot = sum(a * b for a, b in zip(q, vec))
            v_norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            cosine = dot / (q_norm * v_norm)
            scores.append((cosine, idx))

        scores.sort(key=lambda x: x[0], reverse=True)
        top = scores[: min(top_k, len(scores))]

        return [
            {
                "id":       self._ids[idx],
                "text":     self._documents[idx],
                "metadata": self._metadatas[idx],
                "distance": float(max(0.0, 1.0 - cosine)),
                "score":    float(max(0.0, min(1.0, cosine))),
            }
            for cosine, idx in top
        ]

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def collection_size(self) -> int:
        """Return the number of documents currently stored."""
        return len(self._ids)

    def clear(self) -> None:
        """Remove all stored chunks (for full re-indexing)."""
        self._ids        = []
        self._documents  = []
        self._metadatas  = []
        self._embeddings = []
        logger.info("VectorStore cleared.")
