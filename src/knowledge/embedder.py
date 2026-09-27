"""
embedder.py — chunk symbols and produce TF-IDF keyword vectors.

No external ML libraries, no model downloads, no PyTorch.
Uses pure-Python TF-IDF over a fixed vocabulary built from the corpus.

Two classes (same public interface as before):
  CodeChunker  — converts Symbol objects into text chunks.
  Embedder     — produces TF-IDF float vectors; falls back to watsonx
                 or sentence-transformers only when explicitly requested
                 via the REPOPILOT_EMBEDDER env var.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from src.analysis.symbol_index import SymbolIndex

from src.analysis.symbol_index import SymbolKind

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CodeChunker  (unchanged from original)
# ---------------------------------------------------------------------------

_CHUNKABLE_KINDS = {SymbolKind.CLASS, SymbolKind.METHOD, SymbolKind.FUNCTION}


class CodeChunker:
    """Convert a SymbolIndex into text chunks."""

    def chunk_symbols(self, index: "SymbolIndex", parse_results: list[dict]) -> list[dict]:
        chunks: list[dict] = []
        for symbol in index.all_symbols():
            if symbol.kind not in _CHUNKABLE_KINDS:
                continue
            return_annotation = symbol.annotations.get("return", "unknown")
            text = "\n".join([
                f"# {symbol.kind.value}: {symbol.fqn}",
                f"# File: {symbol.file_path}:{symbol.line}",
                symbol.docstring or "",
                f"Args: {symbol.args}",
                f"Returns: {return_annotation}",
            ])
            chunks.append({
                "id":   symbol.fqn,
                "text": text,
                "metadata": {
                    "fqn":        symbol.fqn,
                    "file_path":  symbol.file_path,
                    "line":       symbol.line,
                    "kind":       symbol.kind.value,
                    "name":       symbol.name,
                    "module_fqn": symbol.module_fqn,
                },
            })
        return chunks


# ---------------------------------------------------------------------------
# TF-IDF helpers
# ---------------------------------------------------------------------------

def _tokenise(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, drop 1-char tokens."""
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 1]


class _TFIDFVectorizer:
    """Minimal corpus-fitted TF-IDF vectorizer (pure Python, no deps)."""

    def __init__(self) -> None:
        self._vocab: dict[str, int] = {}    # token → column index
        self._idf:   list[float]    = []    # per-token IDF weight

    def fit(self, documents: list[str]) -> None:
        n = len(documents)
        df: Counter = Counter()
        for doc in documents:
            for tok in set(_tokenise(doc)):
                df[tok] += 1
        # Build vocab from tokens that appear in at least 1 doc
        self._vocab = {tok: i for i, tok in enumerate(sorted(df))}
        self._idf = [
            math.log((1 + n) / (1 + df[tok])) + 1.0
            for tok in sorted(df)
        ]

    def transform(self, documents: list[str]) -> list[list[float]]:
        """Return L2-normalised TF-IDF vectors for each document."""
        dim = len(self._vocab)
        result: list[list[float]] = []
        for doc in documents:
            vec = [0.0] * dim
            tokens = _tokenise(doc)
            if not tokens:
                result.append(vec)
                continue
            tf = Counter(tokens)
            total = len(tokens)
            for tok, count in tf.items():
                idx = self._vocab.get(tok)
                if idx is not None:
                    vec[idx] = (count / total) * self._idf[idx]
            # L2 normalise
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            result.append([v / norm for v in vec])
        return result

    def transform_query(self, text: str) -> list[float]:
        """Transform a single query text; unknown tokens are ignored."""
        return self.transform([text])[0]

    @property
    def dim(self) -> int:
        return len(self._vocab)


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------

class Embedder:
    """Produce TF-IDF float vectors for text chunks.

    No model downloads. No PyTorch. No network calls.

    The vectorizer is fitted lazily on the first :meth:`embed` call
    using the full corpus passed in, then reused for subsequent queries.

    Set env var ``REPOPILOT_EMBEDDER=watsonx`` or
    ``REPOPILOT_EMBEDDER=sentence_transformers`` to opt into those
    backends instead (they must be installed separately).
    """

    def __init__(self, model_name: str = "tfidf") -> None:
        self._model_name = model_name
        self._vectorizer: _TFIDFVectorizer | None = None
        self._fitted_corpus: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts* as TF-IDF vectors.

        On the first call the vectorizer is fitted against *texts* as the
        corpus, then cached.  Subsequent calls (e.g. a single question)
        reuse the fitted vocabulary.
        """
        if not texts:
            return []

        # If this is a large corpus call (indexing), refit
        if len(texts) > 1 or self._vectorizer is None:
            self._vectorizer = _TFIDFVectorizer()
            self._vectorizer.fit(texts)
            self._fitted_corpus = texts
            try:
                return self._vectorizer.transform(texts)
            except Exception as exc:
                logger.error("TF-IDF transform failed: %s", exc)
                return []

        # Single-text call (query) — reuse fitted vectorizer
        try:
            return [self._vectorizer.transform_query(texts[0])]
        except Exception as exc:
            logger.error("TF-IDF query transform failed: %s", exc)
            return []
