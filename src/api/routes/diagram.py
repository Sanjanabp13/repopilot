"""GET /diagram?analysis_id=…&kind=call_graph|dep_graph"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.api.models import DiagramResponse, GraphEdgeSchema, GraphNodeSchema
from src.api import session_store
from src.diagrams.mermaid_renderer import MermaidRenderer

router = APIRouter()
_renderer = MermaidRenderer()


def _build_graph_payload(kind: str, session: dict) -> dict:
    if kind == "call_graph":
        graph = session["call_graph"]
        nodes = [
            GraphNodeSchema(
                id=node.fqn,
                label=node.fqn.split(".")[-1],
                kind=node.kind,
                file_path=node.file_path,
                line=node.line,
                is_internal=bool(node.file_path),
            )
            for node in graph.all_nodes()
        ]
        edges = [
            GraphEdgeSchema(
                id=f"{caller}->{callee}",
                source=caller,
                target=callee,
                label=edge.call_text,
                resolved=edge.resolved,
            )
            for caller, callee, edge in graph.edges()
        ]
        return {"nodes": [n.model_dump() for n in nodes], "edges": [e.model_dump() for e in edges]}

    if kind == "dep_graph":
        graph = session["dep_graph"]
        nodes = [
            GraphNodeSchema(
                id=node.fqn,
                label=node.fqn.split(".")[-1],
                kind="module",
                file_path=node.file_path,
                line=1,
                is_internal=node.is_internal,
            )
            for node in graph.all_nodes()
        ]
        edges = [
            GraphEdgeSchema(
                id=f"{importer}->{importee}",
                source=importer,
                target=importee,
                label=", ".join(edge.names) if edge.names else "import",
                resolved=edge.is_internal,
            )
            for importer, importee, edge in graph.edges()
        ]
        return {"nodes": [n.model_dump() for n in nodes], "edges": [e.model_dump() for e in edges]}

    raise ValueError("kind must be call_graph or dep_graph")


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

    graph = _build_graph_payload(kind, session)
    return DiagramResponse(analysis_id=analysis_id, kind=kind, diagram=mermaid, graph=graph)
