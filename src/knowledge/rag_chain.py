"""
rag_chain.py — Retrieval-Augmented Generation over the RepoPilot symbol index.

Class: RAGChain
  Orchestrates CodeChunker → Embedder → VectorStore → Google Gemini LLM to
  answer natural-language questions about a codebase, with exact file-path +
  line citations.  No LangChain is used; everything is hand-rolled.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.analysis.symbol_index import SymbolIndex

from src.knowledge.embedder import CodeChunker, Embedder
from src.knowledge.vector_store import VectorStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template (hand-rolled, no LangChain)
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """\
You are an expert code documentation assistant for the RepoPilot project.
Answer the question based ONLY on the provided code context.
Always cite the exact file path and line number for any claim you make.
If the context does not contain enough information, say "I don't have enough context to answer."
Do not guess or make up information about the code.
Be concise but thorough. Use Markdown formatting.

Context:
{context_block}

Question: {question}

Answer (with citations):"""

# ---------------------------------------------------------------------------
# RAGChain
# ---------------------------------------------------------------------------


class RAGChain:
    """End-to-end RAG pipeline for codebase Q&A.

    Parameters
    ----------
    vector_store:
        Pre-initialised :class:`~src.knowledge.vector_store.VectorStore`.
    embedder:
        Pre-initialised :class:`~src.knowledge.embedder.Embedder`.
    confidence_threshold:
        If the best retrieval score is below this value the chain falls
        back to a keyword search against the symbol index rather than
        returning "No confident answer found."  Set to 0.0 to always use
        retrieved chunks.
    top_k:
        Number of chunks to retrieve per question.
    model_id:
        Google Gemini model identifier used for generation.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedder: Embedder,
        confidence_threshold: float = 0.15,
        top_k: int = 5,
        model_id: str = "gemini-1.5-flash",
    ) -> None:
        self._vs = vector_store
        self._embedder = embedder
        self._confidence_threshold = confidence_threshold
        self._top_k = top_k
        self._model_id = model_id
        self._llm = self._init_llm(model_id)
        self._index: "SymbolIndex | None" = None  # set by index_repository

    # ------------------------------------------------------------------
    # LLM initialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _init_llm(model_id: str):
        """Initialise the Google Gemini GenerativeModel client.

        Returns ``None`` (graceful degradation) if credentials are absent
        or the SDK is not installed.
        """
        apikey = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")

        if not apikey:
            logger.warning(
                "GOOGLE_API_KEY / GEMINI_API_KEY not set; "
                "LLM generation disabled (context-only mode)."
            )
            return None

        try:
            import google.generativeai as genai

            genai.configure(api_key=apikey)
            model = genai.GenerativeModel(
                model_name=model_id,
                generation_config={
                    "temperature": 0.2,
                    "max_output_tokens": 1024,
                },
            )
            logger.info("RAGChain: Gemini LLM initialised (model=%s)", model_id)
            return model
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to initialise Gemini LLM: %s — running without LLM.", exc
            )
            return None

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_repository(
        self,
        index: "SymbolIndex",
        parse_results: list[dict],
    ) -> int:
        """Chunk, embed, and store every chunkable symbol in *index*."""
        self._index = index  # keep reference for keyword fallback
        chunker = CodeChunker()
        chunks = chunker.chunk_symbols(index, parse_results)

        if not chunks:
            logger.warning("No chunkable symbols found in index.")
            return 0

        texts = [c["text"] for c in chunks]
        embeddings = self._embedder.embed(texts)

        if not embeddings:
            logger.error("Embedding step returned no vectors; aborting indexing.")
            return 0

        if len(embeddings) != len(chunks):
            logger.error(
                "Embedding count mismatch (chunks=%d, embeddings=%d); aborting.",
                len(chunks),
                len(embeddings),
            )
            return 0

        self._vs.add_chunks(chunks, embeddings)
        logger.info("Indexed %d symbol chunks.", len(chunks))
        return len(chunks)

    # ------------------------------------------------------------------
    # Q&A
    # ------------------------------------------------------------------

    def answer(self, question: str) -> dict:
        """Answer *question* using RAG over the symbol vector store.

        Returns
        -------
        dict::

            {
                "answer":           str,
                "citations":        [{"fqn": str, "file_path": str,
                                      "line": int, "snippet": str}],
                "confidence":       float,   # max retrieval score
                "retrieved_chunks": int,
            }
        """
        # 1. Embed the question
        q_embeddings = self._embedder.embed([question])
        if not q_embeddings:
            return self._no_answer("Embedding the question failed.")

        query_vector = q_embeddings[0]

        # 2. Retrieve nearest neighbours
        results = self._vs.query(query_vector, top_k=self._top_k)

        if not results:
            return self._keyword_fallback(question)

        max_score = max(r["score"] for r in results)

        # 3. Low-confidence: supplement with keyword fallback chunks
        if max_score < self._confidence_threshold:
            results = self._keyword_fallback_chunks(question) or results

        # 4. Build structured context block (Markdown headers + code)
        context_parts = []
        for r in results:
            meta = r["metadata"]
            fqn = meta.get("fqn", "")
            fp = meta.get("file_path", "")
            ln = meta.get("line", 0)
            kind = meta.get("kind", "symbol")
            context_parts.append(
                f"### `{fqn}` ({kind})\n"
                f"**File:** `{fp}:{ln}`\n\n"
                f"```python\n{r['text']}\n```"
            )
        context_block = "\n\n".join(context_parts)

        # 5. Build citations
        citations = [
            {
                "fqn": r["metadata"].get("fqn", ""),
                "file_path": r["metadata"].get("file_path", ""),
                "line": int(r["metadata"].get("line", 0)),
                "snippet": r["text"][:200],
            }
            for r in results
        ]

        # 6. Generate answer (or fall back to structured context summary)
        if self._llm is None:
            bullets = []
            for r in results[:3]:
                meta = r["metadata"]
                doc_line = (
                    r["text"].split("\n")[2]
                    if len(r["text"].split("\n")) > 2
                    else ""
                )
                bullets.append(
                    f"- **`{meta.get('fqn','')}`** "
                    f"(`{meta.get('file_path','').split('/')[-1]}:{meta.get('line',0)}`)"
                    + (f"\n  > {doc_line.strip()}" if doc_line.strip() else "")
                )
            answer_text = (
                "**Top matches** (LLM not configured — showing retrieved symbols):\n\n"
                + "\n".join(bullets)
            )
        else:
            prompt = _PROMPT_TEMPLATE.format(
                context_block=context_block,
                question=question,
            )
            try:
                response = self._llm.generate_content(prompt)
                answer_text = (
                    response.text if hasattr(response, "text") else str(response)
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Gemini LLM generation failed: %s", exc)
                answer_text = (
                    "**LLM generation failed.** Top matches:\n\n"
                    + "\n".join(
                        f"- `{r['metadata'].get('fqn','')}` — "
                        f"`{r['metadata'].get('file_path','').split('/')[-1]}"
                        f":{r['metadata'].get('line',0)}`"
                        for r in results[:3]
                    )
                )

        return {
            "answer": answer_text,
            "citations": citations,
            "confidence": round(max_score, 4),
            "retrieved_chunks": len(results),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _keyword_fallback_chunks(self, question: str) -> list[dict]:
        """Return pseudo-chunks for symbols whose name appears in *question*."""
        if self._index is None:
            return []
        tokens = set(question.lower().split())
        hits = []
        for sym in self._index.all_symbols():
            if sym.name.lower() in tokens or any(
                t in sym.name.lower() for t in tokens if len(t) > 3
            ):
                hits.append(
                    {
                        "id": sym.fqn,
                        "text": (
                            f"# {sym.kind.value}: {sym.fqn}\n"
                            f"# File: {sym.file_path}:{sym.line}\n"
                            f"{sym.docstring or ''}"
                        ),
                        "metadata": {
                            "fqn": sym.fqn,
                            "file_path": sym.file_path,
                            "line": sym.line,
                            "kind": sym.kind.value,
                            "name": sym.name,
                        },
                        "distance": 0.5,
                        "score": 0.5,
                    }
                )
        return hits[: self._top_k]

    def _keyword_fallback(self, question: str) -> dict:
        """Full fallback when vector store has no results at all."""
        chunks = self._keyword_fallback_chunks(question)
        if not chunks:
            return self._no_answer("No matching symbols found.")
        context_block = "\n\n---\n\n".join(c["text"] for c in chunks)
        citations = [
            {
                "fqn": c["metadata"]["fqn"],
                "file_path": c["metadata"]["file_path"],
                "line": int(c["metadata"]["line"]),
                "snippet": c["text"][:200],
            }
            for c in chunks
        ]
        if self._llm is None:
            bullets = []
            for c in chunks[:3]:
                meta = c["metadata"]
                doc_line = (
                    c["text"].split("\n")[2]
                    if len(c["text"].split("\n")) > 2
                    else ""
                )
                bullets.append(
                    f"- **`{meta.get('fqn','')}`** "
                    f"(`{meta.get('file_path','').split('/')[-1]}:{meta.get('line',0)}`)"
                    + (f"\n  > {doc_line.strip()}" if doc_line.strip() else "")
                )
            answer_text = (
                "**Top keyword matches** (LLM not configured):\n\n"
                + "\n".join(bullets)
            )
        else:
            prompt = _PROMPT_TEMPLATE.format(
                context_block=context_block, question=question
            )
            try:
                response = self._llm.generate_content(prompt)
                answer_text = (
                    response.text if hasattr(response, "text") else str(response)
                )
            except Exception as exc:
                logger.error("Gemini LLM generation failed: %s", exc)
                answer_text = (
                    "LLM generation failed. Top keyword matches:\n\n"
                    + context_block[:1000]
                )
        return {
            "answer": answer_text,
            "citations": citations,
            "confidence": 0.5,
            "retrieved_chunks": len(chunks),
        }

    @staticmethod
    def _no_answer(reason: str) -> dict:
        logger.warning("RAGChain: no answer — %s", reason)
        return {
            "answer": "No confident answer found for this question.",
            "citations": [],
            "confidence": 0.0,
            "retrieved_chunks": 0,
        }


# ---------------------------------------------------------------------------
# __main__ — quick smoke test against the sample fixture project
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from src.analysis.symbol_index import SymbolIndex
    from src.ingestion.parsers.python_parser import PythonParser  # type: ignore[import]

    fixture_dir = repo_root / "tests" / "fixtures" / "sample_project"
    parser = PythonParser()

    parse_results: list[dict] = []
    index = SymbolIndex()

    for py_file in sorted(fixture_dir.glob("*.py")):
        result = parser.parse(str(py_file))
        parse_results.append(result)
        index.add_from_parse_result(result)

    print(f"[main] Symbol index built: {len(index)} symbols")

    embedder = Embedder()
    vs = VectorStore(persist_dir=".repopilot/chroma_demo")
    vs.clear()

    chain = RAGChain(vector_store=vs, embedder=embedder)
    n = chain.index_repository(index, parse_results)
    print(f"[main] Indexed {n} chunks")

    question = "What does UserService.get_user do?"
    print(f"\n[main] Question: {question}")

    result = chain.answer(question)
    print(json.dumps(result, indent=2))
