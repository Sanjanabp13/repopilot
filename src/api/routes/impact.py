"""POST /impact — blast-radius analysis with highlighted Mermaid diagram."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.models import ImpactRequest, ImpactResponse, ImpactedSymbolSchema
from src.api import session_store
from src.diagrams.mermaid_renderer import MermaidRenderer

router = APIRouter()
_renderer = MermaidRenderer()


def _resolve_fqn(symbol_fqn: str, index) -> str:
    """Resolve symbol_fqn: try exact match first, then short-name fallback."""
    # Exact match
    if index.lookup(symbol_fqn):
        return symbol_fqn
    # Short-name lookup (e.g. "get_user" → first method match)
    matches = index.find_by_name(symbol_fqn)
    if not matches:
        return symbol_fqn   # return as-is; impact will be empty but won't crash
    # Prefer methods over functions to avoid collisions
    from src.analysis.symbol_index import SymbolKind
    methods = [m for m in matches if m.kind == SymbolKind.METHOD]
    return (methods[0] if methods else matches[0]).fqn


@router.post("/impact", response_model=ImpactResponse)
def impact(req: ImpactRequest) -> ImpactResponse:
    session = session_store.get(req.analysis_id)
    if not session:
        raise HTTPException(status_code=404, detail="analysis_id not found")

    analyzer   = session["analyzer"]
    call_graph = session["call_graph"]
    index      = session["index"]

    resolved_fqn = _resolve_fqn(req.symbol_fqn, index)
    result = analyzer.get_downstream_impact(resolved_fqn)
    diagram = _renderer.render_impact(result, call_graph, title=f"Blast Radius: {req.symbol_fqn}")

    def _to_schema(sym) -> ImpactedSymbolSchema:
        return ImpactedSymbolSchema(
            fqn        = sym.fqn,
            name       = sym.name,
            kind       = sym.kind,
            file_path  = sym.file_path,
            line       = sym.line,
            hop        = sym.hop,
            is_test    = sym.is_test,
            parent_fqn = sym.parent_fqn,
        )

    return ImpactResponse(
        analysis_id       = req.analysis_id,
        changed_fqn       = result.changed_fqn,
        total_impact      = result.total_impact,
        direct_callers    = [_to_schema(s) for s in result.direct_callers],
        transitive_callers= [_to_schema(s) for s in result.transitive_callers],
        affected_tests    = [_to_schema(s) for s in result.affected_tests],
        affected_files    = result.affected_files,
        diagram           = diagram,
    )
