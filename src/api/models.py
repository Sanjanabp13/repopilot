"""Pydantic request/response schemas for the RepoPilot API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# /analyze
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    source: str = Field(..., description="Local path or remote Git URL to analyze.")
    languages: Optional[List[str]] = Field(
        default=["python"],
        description="Languages to include. Defaults to python.",
    )


class SymbolSummary(BaseModel):
    fqn: str
    name: str
    kind: str
    file_path: str
    line: int
    docstring: Optional[str] = None


class AnalyzeResponse(BaseModel):
    analysis_id: str
    source: str
    total_symbols: int
    modules: int
    classes: int
    methods: int
    functions: int
    parse_errors: int
    indexed_chunks: int


# ---------------------------------------------------------------------------
# /trace
# ---------------------------------------------------------------------------

class TraceRequest(BaseModel):
    analysis_id: str
    entry_fqn: str = Field(..., description="FQN of the entry-point symbol to trace.")
    max_depth: int = Field(default=10, ge=1, le=30)


class TraceNode(BaseModel):
    fqn: str
    depth: int
    call_text: str
    line: int
    is_cycle: bool
    is_unresolved: bool


class TraceResponse(BaseModel):
    analysis_id: str
    entry_fqn: str
    total_nodes: int
    max_depth_reached: bool
    flat_sequence: List[TraceNode]
    diagram: str  # Mermaid sequence diagram


# ---------------------------------------------------------------------------
# /diagram
# ---------------------------------------------------------------------------

class GraphNodeSchema(BaseModel):
    id: str
    label: str
    kind: str
    file_path: str = ""
    line: int = 0
    is_internal: bool = True


class GraphEdgeSchema(BaseModel):
    id: str
    source: str
    target: str
    label: str = ""
    resolved: bool = True


class DiagramResponse(BaseModel):
    analysis_id: str
    kind: str          # "call_graph" | "dep_graph"
    diagram: str       # Mermaid markdown
    graph: Dict[str, List[Any]] = Field(default_factory=lambda: {"nodes": [], "edges": []})


# ---------------------------------------------------------------------------
# /impact
# ---------------------------------------------------------------------------

class ImpactRequest(BaseModel):
    analysis_id: str
    symbol_fqn: str


class ImpactedSymbolSchema(BaseModel):
    fqn: str
    name: str
    kind: str
    file_path: str
    line: int
    hop: int
    is_test: bool
    parent_fqn: Optional[str] = None


class ImpactResponse(BaseModel):
    analysis_id: str
    changed_fqn: str
    total_impact: int
    direct_callers: List[ImpactedSymbolSchema]
    transitive_callers: List[ImpactedSymbolSchema]
    affected_tests: List[ImpactedSymbolSchema]
    affected_files: List[str]
    diagram: str   # Mermaid impact diagram with highlights


# ---------------------------------------------------------------------------
# /chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    analysis_id: str
    question: str


class Citation(BaseModel):
    fqn: str
    file_path: str
    line: int
    snippet: str


class ChatResponse(BaseModel):
    analysis_id: str
    answer: str
    citations: List[Citation]
    confidence: float
    retrieved_chunks: int


# ---------------------------------------------------------------------------
# /export-onboarding
# ---------------------------------------------------------------------------

class ExportRequest(BaseModel):
    analysis_id: str


class ExportResponse(BaseModel):
    analysis_id: str
    markdown: str
    filename: str = "ONBOARDING.md"
