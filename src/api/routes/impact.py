"""POST /impact — blast-radius analysis with highlighted Mermaid diagram."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.models import ImpactRequest, ImpactResponse, ImpactedSymbolSchema
from src.api import session_store
from src.diagrams.mermaid_renderer import MermaidRenderer

router = APIRouter()
_renderer = MermaidRenderer()


def _resolve_fqn(symbol_fqn: str, index, call_graph=None) -> str:
    """Resolve symbol_fqn: try exact match first, then suffix match, then short-name fallback."""
    # 1. Exact match in index
    if index.lookup(symbol_fqn):
        return symbol_fqn

    # 2. Exact match in call graph
    if call_graph and call_graph.node(symbol_fqn):
        return symbol_fqn

    # 3. Suffix match (e.g. "UserService.get_user" or "services.UserService.get_user")
    if "." in symbol_fqn:
        suffix = f".{symbol_fqn}"
        if call_graph:
            matches_cg = [
                n.fqn for n in call_graph.all_nodes()
                if n.fqn == symbol_fqn or n.fqn.endswith(suffix)
            ]
            if matches_cg:
                with_callers = [f for f in matches_cg if len(call_graph.callers_of(f)) > 0]
                return with_callers[0] if with_callers else matches_cg[0]
        for sym in index.all_symbols():
            if sym.fqn.endswith(suffix):
                return sym.fqn

    # 4. Short-name lookup (e.g. "get_user" → method/function match)
    simple_name = symbol_fqn.split(".")[-1]
    matches = index.find_by_name(simple_name)
    if matches:
        if call_graph:
            with_callers = [
                m.fqn for m in matches
                if call_graph.node(m.fqn) and len(call_graph.callers_of(m.fqn)) > 0
            ]
            if with_callers:
                return with_callers[0]
            in_cg = [m.fqn for m in matches if call_graph.node(m.fqn)]
            if in_cg:
                return in_cg[0]
        from src.analysis.symbol_index import SymbolKind
        methods = [m for m in matches if m.kind == SymbolKind.METHOD]
        return (methods[0] if methods else matches[0]).fqn

    # 5. Check call graph nodes directly
    if call_graph:
        cg_nodes = [
            n for n in call_graph.all_nodes()
            if n.fqn.split(".")[-1] == simple_name or n.fqn.endswith(f".{simple_name}")
        ]
        if cg_nodes:
            with_callers = [n.fqn for n in cg_nodes if len(n.called_by) > 0]
            return with_callers[0] if with_callers else cg_nodes[0].fqn

    return symbol_fqn


@router.post("/impact", response_model=ImpactResponse)
def impact(req: ImpactRequest) -> ImpactResponse:
    session = session_store.get(req.analysis_id)
    if not session:
        raise HTTPException(status_code=404, detail="analysis_id not found")

    analyzer   = session["analyzer"]
    call_graph = session["call_graph"]
    index      = session["index"]

    resolved_fqn = _resolve_fqn(req.symbol_fqn, index, call_graph)
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
