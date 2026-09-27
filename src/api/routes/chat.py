"""POST /chat — RAG Q&A wired to rag_chain.py."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.models import ChatRequest, ChatResponse, Citation
from src.api import session_store

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    session = session_store.get(req.analysis_id)
    if not session:
        raise HTTPException(status_code=404, detail="analysis_id not found")

    rag = session.get("rag_chain")
    if rag is None:
        raise HTTPException(status_code=503, detail="RAG chain not initialised for this session.")

    result = rag.answer(req.question)

    return ChatResponse(
        analysis_id     = req.analysis_id,
        answer          = result["answer"],
        citations       = [
            Citation(
                fqn       = c["fqn"],
                file_path = c["file_path"],
                line      = c["line"],
                snippet   = c["snippet"],
            )
            for c in result.get("citations", [])
        ],
        confidence      = result.get("confidence", 0.0),
        retrieved_chunks= result.get("retrieved_chunks", 0),
    )
