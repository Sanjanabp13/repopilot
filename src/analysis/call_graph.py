"""
Call Graph — directed graph of caller → callee relationships.

Each node is a symbol FQN (function, method, or module).
Each directed edge ``(caller_fqn, callee_fqn)`` records that *caller*
contains a call expression that resolves to *callee*.

Call resolution strategy
------------------------
Python call resolution at static-analysis time is intentionally **best-
effort**:

1. A call like ``walk_repository(...)`` is matched against names imported
   into the calling module's import list.
2. A call like ``self.parse(...)`` is matched against methods of the
   current class (and its declared bases).
3. Attribute chains (``obj.method()``) fall back to name-only matching
   across all symbols with that simple name.
4. Calls that cannot be resolved are recorded as *unresolved* edges with
   the raw call text as the callee FQN so no information is lost.

Building the call graph
-----------------------
::

    from src.analysis.call_graph import build_call_graph
    graph = build_call_graph(index, parse_results)

    for caller, callee, meta in graph.edges():
        print(caller, "→", callee, meta)
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .symbol_index import Symbol, SymbolIndex, SymbolKind


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CallEdge:
    """A directed call relationship between two symbols."""
    caller_fqn:  str
    callee_fqn:  str
    call_text:   str        # raw source text of the call expression
    line:        int        # line in the *caller* file
    resolved:    bool       # True → callee_fqn is a known symbol FQN


@dataclass
class CallNode:
    """A node in the call graph."""
    fqn:         str
    kind:        str        # SymbolKind value string
    file_path:   str
    line:        int
    # outgoing edges (calls this node makes)
    calls:       List[CallEdge] = field(default_factory=list)
    # incoming edges (who calls this node)
    called_by:   List[CallEdge] = field(default_factory=list)


# ---------------------------------------------------------------------------
# AST visitor: extracts call expressions from a function/method body
# ---------------------------------------------------------------------------

class _CallExtractor(ast.NodeVisitor):
    """Collects all Call nodes within a subtree."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, int]] = []   # (call_text, line)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        try:
            call_text = ast.unparse(node.func)
        except Exception:
            call_text = "<unknown>"
        self.calls.append((call_text, node.lineno))
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------

def _build_import_map(parse_result: dict) -> Dict[str, str]:
    """Return a mapping of local name → module FQN from a file's imports.

    Examples
    --------
    ``import os``               → ``{"os": "os"}``
    ``from pathlib import Path`` → ``{"Path": "pathlib.Path"}``
    ``import numpy as np``       → ``{"np": "numpy"}``
    """
    mapping: Dict[str, str] = {}
    for imp in parse_result.get("imports", []):
        if imp["kind"] == "import":
            local = imp.get("alias") or imp["module"].split(".")[0]
            mapping[local] = imp["module"]
        else:  # "from"
            module = imp["module"]
            for name in imp.get("names", []):
                local = imp.get("alias") or name
                mapping[local] = f"{module}.{name}" if module else name
    return mapping


def _resolve_call(
    call_text: str,
    caller_fqn: str,
    import_map: Dict[str, str],
    class_fqn: Optional[str],
    index: SymbolIndex,
) -> Tuple[str, bool]:
    """Attempt to resolve *call_text* to a known symbol FQN.

    Returns
    -------
    (resolved_fqn, is_resolved)
        *is_resolved* is True when the FQN is in the symbol index.
    """
    # Strip trailing parens if present (won't be, but defensive)
    name = call_text.strip()

    # ---- self.method(...) or cls.method(...)  --------------------------
    if name.startswith("self.") or name.startswith("cls."):
        method_name = name.split(".", 1)[1]
        if class_fqn:
            candidate = f"{class_fqn}.{method_name}"
            if candidate in index:
                return candidate, True
        # fall through to name-only search
        name = method_name

    # ---- attribute chain: a.b.c  ---------------------------------------
    parts = name.split(".")
    if len(parts) > 1:
        root = parts[0]
        tail = ".".join(parts[1:])
        # root may be an import alias
        if root in import_map:
            candidate = f"{import_map[root]}.{tail}"
            if candidate in index:
                return candidate, True
        # try the full dotted name as a FQN directly
        if name in index:
            return name, True
        # ---- instance variable: root not in import map -----------------
        # e.g. `_svc.get_user` where `_svc` is a module-level instance.
        # Fall back to searching for the method/function name (tail).
        method_matches = index.find_by_name(tail)
        if len(method_matches) == 1:
            return method_matches[0].fqn, True
        if len(method_matches) > 1:
            # Prefer methods (not functions) to avoid matching standalone fns
            method_only = [m for m in method_matches
                           if m.kind.value == "method"]
            if len(method_only) == 1:
                return method_only[0].fqn, True
            # Prefer same-module match
            caller_module = ".".join(caller_fqn.split(".")[:-1])
            for m in method_matches:
                if m.module_fqn == caller_module:
                    return m.fqn, True
            return method_matches[0].fqn, True

    # ---- simple name: check import map first ---------------------------
    if name in import_map:
        candidate = import_map[name]
        if candidate in index:
            return candidate, True

    # ---- simple name: search index by name ----------------------------
    matches = index.find_by_name(name)
    if len(matches) == 1:
        return matches[0].fqn, True
    if len(matches) > 1:
        # Prefer a match in the same module as the caller
        caller_module = ".".join(caller_fqn.split(".")[:-1])
        for m in matches:
            if m.module_fqn == caller_module:
                return m.fqn, True
        # Fallback: first match
        return matches[0].fqn, True

    # ---- unresolved ---------------------------------------------------
    return call_text, False


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

class CallGraph:
    """Directed call graph over symbol FQNs.

    Nodes are added automatically when edges are added.  The graph stores
    both *outgoing* (calls) and *incoming* (called_by) edge lists on each
    node for efficient traversal in either direction.
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, CallNode] = {}
        self._edges: List[CallEdge] = []

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def _get_or_create(self, fqn: str, index: SymbolIndex) -> CallNode:
        if fqn not in self._nodes:
            sym: Optional[Symbol] = index.lookup(fqn)
            self._nodes[fqn] = CallNode(
                fqn       = fqn,
                kind      = sym.kind.value if sym else "unknown",
                file_path = sym.file_path  if sym else "",
                line      = sym.line       if sym else 0,
            )
        return self._nodes[fqn]

    def add_edge(self, edge: CallEdge, index: SymbolIndex) -> None:
        """Register a :class:`CallEdge` and update both node edge lists."""
        self._edges.append(edge)
        caller_node = self._get_or_create(edge.caller_fqn, index)
        callee_node = self._get_or_create(edge.callee_fqn, index)
        caller_node.calls.append(edge)
        callee_node.called_by.append(edge)

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def node(self, fqn: str) -> Optional[CallNode]:
        """Return the :class:`CallNode` for *fqn*, or *None*."""
        return self._nodes.get(fqn)

    def callees_of(self, fqn: str) -> List[str]:
        """Return FQNs of all symbols called by *fqn*."""
        node = self._nodes.get(fqn)
        return [e.callee_fqn for e in node.calls] if node else []

    def callers_of(self, fqn: str) -> List[str]:
        """Return FQNs of all symbols that call *fqn*."""
        node = self._nodes.get(fqn)
        return [e.caller_fqn for e in node.called_by] if node else []

    def edges(self) -> List[Tuple[str, str, CallEdge]]:
        """Return all edges as (caller_fqn, callee_fqn, edge) tuples."""
        return [(e.caller_fqn, e.callee_fqn, e) for e in self._edges]

    def all_nodes(self) -> List[CallNode]:
        return list(self._nodes.values())

    def __len__(self) -> int:
        return len(self._edges)

    def __repr__(self) -> str:
        return f"<CallGraph nodes={len(self._nodes)} edges={len(self._edges)}>"


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def _extract_calls_from_body(
    body: list,
    caller_fqn: str,
    import_map: Dict[str, str],
    class_fqn: Optional[str],
    index: SymbolIndex,
    graph: CallGraph,
) -> None:
    """Walk the AST body of a function/method and register call edges."""
    extractor = _CallExtractor()
    for node in body:
        extractor.visit(node)

    for call_text, line in extractor.calls:
        callee_fqn, resolved = _resolve_call(
            call_text, caller_fqn, import_map, class_fqn, index
        )
        edge = CallEdge(
            caller_fqn = caller_fqn,
            callee_fqn = callee_fqn,
            call_text  = call_text,
            line       = line,
            resolved   = resolved,
        )
        graph.add_edge(edge, index)


def build_call_graph(
    index: SymbolIndex,
    parse_results: Iterable[dict],
) -> CallGraph:
    """Build and return a :class:`CallGraph` from parsed source files.

    Parameters
    ----------
    index:
        A fully populated :class:`~src.analysis.symbol_index.SymbolIndex`.
    parse_results:
        Iterable of parser result dicts (one per file) conforming to the
        schema in :mod:`src.ingestion.parsers.base`.

    Returns
    -------
    CallGraph
    """
    graph = CallGraph()

    for result in parse_results:
        if result.get("error"):
            continue

        file_path  = result["file_path"]
        import_map = _build_import_map(result)

        # Re-parse the file's AST so we can walk function bodies.
        # We keep this separate from the symbol-extraction pass so the
        # two concerns stay independent.
        try:
            source = open(file_path, encoding="utf-8", errors="replace").read()
            tree   = ast.parse(source, filename=file_path)
        except (OSError, SyntaxError):
            continue

        from .symbol_index import _file_path_to_module_fqn  # local import avoids cycle
        module_fqn = _file_path_to_module_fqn(file_path)

        # Index top-level AST nodes by name for fast lookup
        top_level: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = {}
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                top_level[node.name] = node

        # ---- top-level functions -------------------------------------
        for fn_info in result.get("functions", []):
            fn_name    = fn_info["name"]
            caller_fqn = f"{module_fqn}.{fn_name}"
            ast_node   = top_level.get(fn_name)
            if ast_node is None:
                continue
            _extract_calls_from_body(
                ast_node.body, caller_fqn, import_map, None, index, graph
            )

        # ---- classes and methods -------------------------------------
        for cls_info in result.get("classes", []):
            cls_name   = cls_info["name"]
            cls_fqn    = f"{module_fqn}.{cls_name}"
            cls_node   = top_level.get(cls_name)
            if not isinstance(cls_node, ast.ClassDef):
                continue

            method_nodes: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
            for item in cls_node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_nodes[item.name] = item

            for method_info in cls_info.get("methods", []):
                m_name     = method_info["name"]
                caller_fqn = f"{cls_fqn}.{m_name}"
                m_node     = method_nodes.get(m_name)
                if m_node is None:
                    continue
                _extract_calls_from_body(
                    m_node.body, caller_fqn, import_map, cls_fqn, index, graph
                )

    return graph
