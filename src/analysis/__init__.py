"""
Analysis Engine — symbol indexing, call graph, dependency graph, path tracing, and impact analysis.

Public re-exports::

    from src.analysis import SymbolIndex, CallGraph, DependencyGraph, PathTracer
    from src.analysis import ImpactAnalyzer, ImpactResult, ImpactedSymbol
"""

from .symbol_index import Symbol, SymbolKind, SymbolIndex
from .call_graph import CallGraph
from .dep_graph import DependencyGraph
from .path_tracer import PathTracer, TracedPath
from .impact import ImpactAnalyzer, ImpactResult, ImpactedSymbol

__all__ = [
    "Symbol",
    "SymbolKind",
    "SymbolIndex",
    "CallGraph",
    "DependencyGraph",
    "PathTracer",
    "TracedPath",
    "ImpactAnalyzer",
    "ImpactResult",
    "ImpactedSymbol",
]
