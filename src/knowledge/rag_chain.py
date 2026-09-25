"""
rag_chain.py — Retrieval-Augmented Generation over the RepoPilot symbol index.

Class: RAGChain
  Orchestrates CodeChunker → Embedder → VectorStore → IBM Granite LLM to answer
  natural-language questions about a codebase, with exact file-path + line
  citations.  No LangChain is used; everything is hand-rolled.
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
You are a code documentation assistant for the RepoPilot project.
Answer the question based ONLY on the provided code context.
Always cite the exact file path and line number for any claim you make.
If the context does not contain enough information, say "I don't have enough context to answer."
Do not guess or make up information about the code.

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
        Minimum retrieval score (0–1) needed before calling the LLM.
        Below this value, the chain returns "No confident answer found."
    top_k:
        Number of chunks to retrieve per question.
    model_id:
        IBM Granite model identifier used for generation.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedder: Embedder,
        confidence_threshold: float = 0.35,
        top_k: int = 5,
        model_id: str = "ibm/granite-3-8b-instruct",
    ) -> None:
        self._vs                  = vector_store
        self._embedder            = embedder
        self._confidence_threshold = confidence_threshold
        self._top_k               = top_k
        self._model_id            = model_id
        self._llm                 = self._init_llm(model_id)

    # ------------------------------------------------------------------
    # LLM initialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _init_llm(model_id: str):
        """Initialise the watsonx.ai ModelInference client.

        Returns ``None`` (graceful degradation) if credentials are absent
        or the SDK is not installed.
        """
        url    = os.environ.get("WATSONX_URL")
        apikey = os.environ.get("WATSONX_APIKEY")
        proj   = os.environ.get("WATSONX_PROJECT_ID")

        if not (url and apikey and proj):
            logger.warning(
                "WATSONX_URL / WATSONX_APIKEY / WATSONX_PROJECT_ID not set; "
                "LLM generation disabled (context-only mode)."
            )
            return None

        try:
            from ibm_watsonx_ai import APIClient, Credentials
            from ibm_watsonx_ai.foundation_models import ModelInference

            creds  = Credentials(url=url, api_key=apikey)
            client = APIClient(credentials=creds, project_id=proj)
            llm = ModelInference(
                model_id=model_id,
                api_client=client,
                params={
                    "max_new_tokens": 512,
                    "temperature":    0.0,
                },
            )
            logger.info("RAGChain: LLM initialised (model=%s)", model_id)
            return llm
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to initialise watsonx LLM: %s — running without LLM.", exc)
            return None

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_repository(
        self,
        index: "SymbolIndex",
        parse_results: list[dict],
    ) -> int:
        """Chunk, embed, and store every chunkable symbol in *index*.

        Parameters
        ----------
        index:
            Populated :class:`~src.analysis.symbol_index.SymbolIndex`.
        parse_results:
            Raw parser result dicts (forwarded to :class:`CodeChunker`).

        Returns
        -------
        int
            Number of chunks successfully indexed.
        """
        chunker = CodeChunker()
        chunks  = chunker.chunk_symbols(index, parse_results)

        if not chunks:
            logger.warning("No chunkable symbols found in index.")
            return 0

        texts      = [c["text"] for c in chunks]
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
            return self._no_answer("Vector store returned no results.")

        max_score = max(r["score"] for r in results)

        # 3. Confidence gate
        if max_score < self._confidence_threshold:
            return {
                "answer":           "No confident answer found for this question.",
                "citations":        [],
                "confidence":       0.0,
                "retrieved_chunks": len(results),
            }

        # 4. Build context block
        context_block = "\n\n---\n\n".join(r["text"] for r in results)

        # 5. Build citations
        citations = [
            {
                "fqn":       r["metadata"].get("fqn", ""),
                "file_path": r["metadata"].get("file_path", ""),
                "line":      int(r["metadata"].get("line", 0)),
                "snippet":   r["text"][:200],
            }
            for r in results
        ]

        # 6. Generate answer (or fall back to context-only)
        if self._llm is None:
            answer_text = (
                "LLM not configured. Top retrieved context:\n\n"
                + context_block[:1000]
            )
        else:
            prompt = _PROMPT_TEMPLATE.format(
                context_block=context_block,
                question=question,
            )
            try:
                response   = self._llm.generate_text(prompt=prompt)
                answer_text = response if isinstance(response, str) else str(response)
            except Exception as exc:  # noqa: BLE001
                logger.error("LLM generation failed: %s", exc)
                answer_text = (
                    "LLM generation failed. Top retrieved context:\n\n"
                    + context_block[:1000]
                )

        return {
            "answer":           answer_text,
            "citations":        citations,
            "confidence":       round(max_score, 4),
            "retrieved_chunks": len(results),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _no_answer(reason: str) -> dict:
        logger.warning("RAGChain: no answer — %s", reason)
        return {
            "answer":           "No confident answer found for this question.",
            "citations":        [],
            "confidence":       0.0,
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

    # Ensure src/ is importable
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from src.analysis.symbol_index import SymbolIndex
    from src.ingestion.parsers.python_parser import PythonParser  # type: ignore[import]

    fixture_dir = repo_root / "tests" / "fixtures" / "sample_project"
    parser      = PythonParser()

    parse_results: list[dict] = []
    index = SymbolIndex()

    for py_file in sorted(fixture_dir.glob("*.py")):
        result = parser.parse(str(py_file))
        parse_results.append(result)
        index.add_from_parse_result(result)

    print(f"[main] Symbol index built: {len(index)} symbols")

    embedder = Embedder()
    vs       = VectorStore(persist_dir=".repopilot/chroma_demo")
    vs.clear()

    chain = RAGChain(vector_store=vs, embedder=embedder)
    n     = chain.index_repository(index, parse_results)
    print(f"[main] Indexed {n} chunks")

    question = "What does UserService.get_user do?"
    print(f"\n[main] Question: {question}")

    result = chain.answer(question)
    print(json.dumps(result, indent=2))
