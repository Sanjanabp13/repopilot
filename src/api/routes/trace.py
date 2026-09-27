"""POST /trace — trace execution path from a given entry-point FQN."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.models import TraceRequest, TraceResponse, TraceNode
from src.api import session_store
from src.diagrams.sequence_renderer import SequenceRenderer

router = APIRouter()
_renderer = SequenceRenderer()


@router.post("/trace", response_model=TraceResponse)
def trace(req: TraceRequest) -> TraceResponse:
    session = session_store.get(req.analysis_id)
    if not session:
        raise HTTPException(status_code=404, detail="analysis_id not found")

    tracer = session["tracer"]
    cg_node = session["call_graph"].node(req.entry_fqn)
    if cg_node is None:
        raise HTTPException(
            status_code=404,
            detail=f"Symbol '{req.entry_fqn}' not found in call graph.",
        )

    tracer._max_depth = req.max_depth
    traced = tracer.trace(req.entry_fqn)
    diagram = _renderer.render_execution_trace(traced, title=f"Trace: {req.entry_fqn}")

    return TraceResponse(
        analysis_id      = req.analysis_id,
        entry_fqn        = req.entry_fqn,
        total_nodes      = len(traced.flat_sequence),
        max_depth_reached= traced.max_depth_reached,
        flat_sequence    = [
            TraceNode(
                fqn           = n.fqn,
                depth         = n.depth,
                call_text     = n.call_text,
                line          = n.line,
                is_cycle      = n.is_cycle,
                is_unresolved = n.is_unresolved,
            )
            for n in traced.flat_sequence
        ],
        diagram = diagram,
    )
