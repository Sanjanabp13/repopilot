"""POST /analyze — ingest a repository and build the full analysis session."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.models import AnalyzeRequest, AnalyzeResponse
from src.api import session_store
from src.ingestion.loader import load_repository
from src.ingestion.walker import walk_repository
from src.ingestion.parsers.python_parser import PythonParser
from src.analysis.symbol_index import build_index, SymbolKind
from src.analysis.call_graph import build_call_graph
from src.analysis.dep_graph import build_dep_graph
from src.analysis.impact import ImpactAnalyzer
from src.analysis.path_tracer import PathTracer
from src.knowledge.embedder import Embedder
from src.knowledge.vector_store import VectorStore
from src.knowledge.rag_chain import RAGChain

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    # Load repo
    try:
        ctx = load_repository(req.source)
    except (NotADirectoryError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    languages = set(req.languages or ["python"])
    source_files = walk_repository(ctx.path, languages=languages)
    if not source_files:
        raise HTTPException(status_code=422, detail="No source files found.")

    parser = PythonParser()
    parse_results = [parser.parse(f.absolute_path) for f in source_files]
    parse_errors = sum(1 for r in parse_results if r.get("error"))

    index      = build_index(source_files, parser)
    call_graph = build_call_graph(index, parse_results)
    dep_graph  = build_dep_graph(index, parse_results)
    analyzer   = ImpactAnalyzer(index, call_graph)
    tracer     = PathTracer(call_graph, max_depth=10)

    # RAG indexing (best-effort — runs synchronously)
    vs = VectorStore(persist_dir=".repopilot/chroma")
    vs.clear()
    embedder  = Embedder()
    rag_chain = RAGChain(vector_store=vs, embedder=embedder)
    indexed_chunks = rag_chain.index_repository(index, parse_results)

    analysis_id = session_store.new_session()
    session_store.set_session(analysis_id, {
        "source":        req.source,
        "index":         index,
        "call_graph":    call_graph,
        "dep_graph":     dep_graph,
        "analyzer":      analyzer,
        "tracer":        tracer,
        "parse_results": parse_results,
        "rag_chain":     rag_chain,
    })

    kinds = {k: 0 for k in SymbolKind}
    for sym in index.all_symbols():
        kinds[sym.kind] += 1

    return AnalyzeResponse(
        analysis_id    = analysis_id,
        source         = req.source,
        total_symbols  = len(index),
        modules        = kinds[SymbolKind.MODULE],
        classes        = kinds[SymbolKind.CLASS],
        methods        = kinds[SymbolKind.METHOD],
        functions      = kinds[SymbolKind.FUNCTION],
        parse_errors   = parse_errors,
        indexed_chunks = indexed_chunks,
    )
