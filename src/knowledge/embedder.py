"""
embedder.py — chunk symbols from the SymbolIndex and embed them as float vectors.

Two classes:
  CodeChunker  — converts Symbol objects into text chunks ready for embedding.
  Embedder     — wraps ibm-watsonx-ai (primary) or sentence-transformers (fallback)
                 to produce dense embedding vectors.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from src.analysis.symbol_index import SymbolIndex

from src.analysis.symbol_index import SymbolKind

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CodeChunker
# ---------------------------------------------------------------------------

_CHUNKABLE_KINDS = {SymbolKind.CLASS, SymbolKind.METHOD, SymbolKind.FUNCTION}


class CodeChunker:
    """Convert a :class:`~src.analysis.symbol_index.SymbolIndex` into text chunks."""

    def chunk_symbols(
        self,
        index: "SymbolIndex",
        parse_results: list[dict],  # noqa: ARG002  (reserved for future import context)
    ) -> list[dict]:
        """Return one chunk dict per function / method / class in *index*.

        Parameters
        ----------
        index:
            Fully-populated :class:`~src.analysis.symbol_index.SymbolIndex`.
        parse_results:
            Raw parser result dicts (reserved for future import-context enrichment).

        Returns
        -------
        list[dict]
            Each element::

                {
                    "id":       str,   # symbol.fqn — unique chunk ID
                    "text":     str,   # human-readable text to embed
                    "metadata": dict,  # file_path, line, kind, …
                }
        """
        chunks: list[dict] = []

        for symbol in index.all_symbols():
            if symbol.kind not in _CHUNKABLE_KINDS:
                continue

            return_annotation = symbol.annotations.get("return", "unknown")

            text_lines = [
                f"# {symbol.kind.value}: {symbol.fqn}",
                f"# File: {symbol.file_path}:{symbol.line}",
                symbol.docstring or "",
                f"Args: {symbol.args}",
                f"Returns: {return_annotation}",
            ]
            text = "\n".join(text_lines)

            chunk: dict = {
                "id": symbol.fqn,
                "text": text,
                "metadata": {
                    "fqn":        symbol.fqn,
                    "file_path":  symbol.file_path,
                    "line":       symbol.line,
                    "kind":       symbol.kind.value,
                    "name":       symbol.name,
                    "module_fqn": symbol.module_fqn,
                },
            }
            chunks.append(chunk)

        return chunks


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------

class Embedder:
    """Produce dense float embedding vectors for text chunks.

    Primary backend: ``ibm-watsonx-ai`` Embeddings API (Slate model).
    Fallback backend: ``sentence-transformers`` ``all-MiniLM-L6-v2`` (offline).

    The backend is selected once on the first call to :meth:`embed`.
    """

    def __init__(self, model_name: str = "ibm/slate-30m-english-rtrvr") -> None:
        self._model_name = model_name
        self._client = None          # lazy-initialised
        self._backend: str | None = None  # "watsonx" | "sentence_transformers"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_watsonx(self) -> bool:
        """Try to initialise the watsonx Embeddings client. Return True on success."""
        url    = os.environ.get("WATSONX_URL")
        apikey = os.environ.get("WATSONX_APIKEY")
        proj   = os.environ.get("WATSONX_PROJECT_ID")

        if not (url and apikey and proj):
            logger.debug("Watsonx credentials not found in env; skipping watsonx backend.")
            return False

        try:
            from ibm_watsonx_ai import APIClient, Credentials
            from ibm_watsonx_ai.foundation_models.embeddings import Embeddings

            creds = Credentials(url=url, api_key=apikey)
            client = APIClient(credentials=creds, project_id=proj)
            self._client = Embeddings(
                model_id=self._model_name,
                api_client=client,
            )
            self._backend = "watsonx"
            logger.info("Embedder: using watsonx backend (model=%s)", self._model_name)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to initialise watsonx Embeddings: %s", exc)
            return False

    def _init_sentence_transformers(self) -> bool:
        """Try to initialise a sentence-transformers model. Return True on success."""
        try:
            from sentence_transformers import SentenceTransformer

            self._client = SentenceTransformer("all-MiniLM-L6-v2")
            self._backend = "sentence_transformers"
            logger.info("Embedder: using sentence-transformers fallback backend.")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to initialise sentence-transformers: %s", exc)
            return False

    def _ensure_client(self) -> None:
        """Lazy-initialise the embedding backend (called on first use)."""
        if self._client is not None:
            return
        if not self._init_watsonx():
            if not self._init_sentence_transformers():
                raise RuntimeError(
                    "No embedding backend available. "
                    "Install ibm-watsonx-ai or sentence-transformers."
                )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of *texts* and return a list of float vectors.

        On partial failure the failed batch is skipped (logged) and an
        empty list is returned for the whole call.
        """
        if not texts:
            return []

        self._ensure_client()

        try:
            if self._backend == "watsonx":
                response = self._client.embed_documents(texts)
                # ibm-watsonx-ai returns list of EmbeddingResult; each has .embeddings
                if hasattr(response, "results"):
                    return [r.embedding for r in response.results]
                # Older SDK versions return list directly
                return list(response)

            elif self._backend == "sentence_transformers":
                vectors = self._client.encode(texts, convert_to_numpy=True)
                return [v.tolist() for v in vectors]

        except Exception as exc:  # noqa: BLE001
            logger.error("Embedding batch failed: %s", exc)
            return []

        return []
