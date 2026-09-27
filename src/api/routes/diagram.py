"""GET /diagram?analysis_id=…&kind=call_graph|dep_graph"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.api.models import DiagramResponse
from src.api import session_store
from src.diagrams.mermaid_renderer import MermaidRenderer

router = APIRouter()
_renderer = MermaidRenderer()


@router.get("/diagram", response_model=DiagramResponse)
def diagram(
    analysis_id: str = Query(...),
    kind: str = Query(default="call_graph"),
) -> DiagramResponse:
    session = session_store.get(analysis_id)
    if not session:
        raise HTTPException(status_code=404, detail="analysis_id not found")

    if kind == "call_graph":
        mermaid = _renderer.render_call_graph(session["call_graph"])
    elif kind == "dep_graph":
        mermaid = _renderer.render_dep_graph(session["dep_graph"])
    else:
        raise HTTPException(status_code=400, detail="kind must be call_graph or dep_graph")

    return DiagramResponse(analysis_id=analysis_id, kind=kind, diagram=mermaid)
