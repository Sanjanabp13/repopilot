"""
Execution Path Tracer.

Given an entry-point symbol FQN and a populated :class:`CallGraph`, the
tracer performs a depth-first traversal and returns a structured
:class:`TracedPath` that describes the complete reachable call tree.

Features
--------
- **DFS traversal** with configurable maximum depth to avoid runaway
  recursion in deeply nested or cyclic codebases.
- **Cycle detection** — revisited nodes are marked ``is_cycle=True``
  rather than expanding again, so the tree stays finite and acyclic.
- **Unresolved call tracking** — calls that couldn't be resolved to a
  known symbol are still included so the caller can see "dark" edges.
- **Filtered traversal** — optional ``include_external`` flag to skip
  unresolved/external callees.
- Produces both a **tree representation** (nested :class:`PathNode`) and
  a **flat ordered list** of FQNs in visitation order for quick display.

Usage
-----
::

    from src.analysis.path_tracer import PathTracer

    tracer = PathTracer(call_graph, max_depth=10)
    path   = tracer.trace("src.api.routes.analyze.run_analysis")

    print(path.entry)
    for step in path.flat_sequence:
        print("  " * step.depth, step.fqn)

    # Mermaid-ready edge list
    for parent, child in path.edges():
        print(f"  {parent} --> {child}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .call_graph import CallGraph


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PathNode:
    """A single node in the traced call tree.

    Attributes
    ----------
    fqn:
        Fully-qualified name of the symbol at this position.
    depth:
        Distance from the entry point (root = 0).
    call_text:
        Raw source text of the call expression that reached this node
        (empty string for the root entry point).
    line:
        Source line in the *caller* file where the call appears (0 for root).
    is_cycle:
        True when this node was already visited on the current path —
        children are not expanded to avoid infinite recursion.
    is_unresolved:
        True when *fqn* was not found in the symbol index (dark edge).
    children:
        Callee nodes reached from this symbol.
    """
    fqn:           str
    depth:         int
    call_text:     str               = ""
    line:          int               = 0
    is_cycle:      bool              = False
    is_unresolved: bool              = False
    children:      List["PathNode"]  = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "fqn":           self.fqn,
            "depth":         self.depth,
            "call_text":     self.call_text,
            "line":          self.line,
            "is_cycle":      self.is_cycle,
            "is_unresolved": self.is_unresolved,
            "children":      [c.as_dict() for c in self.children],
        }


@dataclass
class TracedPath:
    """Result of a single :meth:`PathTracer.trace` call.

    Attributes
    ----------
    entry:
        FQN of the entry-point symbol.
    root:
        Root :class:`PathNode` of the call tree.
    flat_sequence:
        All nodes in DFS pre-order, including the root.
    max_depth_reached:
        True when the traversal hit *max_depth* — the tree may be incomplete.
    """
    entry:             str
    root:              PathNode
    flat_sequence:     List[PathNode]
    max_depth_reached: bool = False

    def edges(self) -> List[Tuple[str, str]]:
        """Return all parent→child FQN pairs in the tree (DFS order)."""
        result: List[Tuple[str, str]] = []
        _collect_edges(self.root, result)
        return result

    def unique_fqns(self) -> List[str]:
        """Return deduplicated list of all FQNs that appear in the tree."""
        seen: Set[str] = set()
        out: List[str] = []
        for node in self.flat_sequence:
            if node.fqn not in seen:
                seen.add(node.fqn)
                out.append(node.fqn)
        return out

    def as_dict(self) -> dict:
        return {
            "entry":             self.entry,
            "max_depth_reached": self.max_depth_reached,
            "tree":              self.root.as_dict(),
            "flat_sequence": [
                {
                    "fqn":           n.fqn,
                    "depth":         n.depth,
                    "call_text":     n.call_text,
                    "line":          n.line,
                    "is_cycle":      n.is_cycle,
                    "is_unresolved": n.is_unresolved,
                }
                for n in self.flat_sequence
            ],
        }


def _collect_edges(node: PathNode, acc: List[Tuple[str, str]]) -> None:
    for child in node.children:
        acc.append((node.fqn, child.fqn))
        if not child.is_cycle:
            _collect_edges(child, acc)


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------

DEFAULT_MAX_DEPTH = 15


class PathTracer:
    """Traces execution paths through a :class:`CallGraph`.

    Parameters
    ----------
    call_graph:
        A populated :class:`~src.analysis.call_graph.CallGraph`.
    max_depth:
        Maximum traversal depth (default 15).  Nodes beyond this depth
        are not expanded; ``TracedPath.max_depth_reached`` is set to True.
    include_external:
        When *False* (default), unresolved / external callee nodes are
        included as leaf nodes but not traversed further.
        When *True*, they are still leaf nodes (no call-graph data for them)
        but they appear in the tree with ``is_unresolved=True``.
    """

    def __init__(
        self,
        call_graph: CallGraph,
        max_depth: int = DEFAULT_MAX_DEPTH,
        include_external: bool = True,
    ) -> None:
        self._graph           = call_graph
        self._max_depth       = max_depth
        self._include_external = include_external

    def trace(self, entry_fqn: str) -> TracedPath:
        """Trace the call tree rooted at *entry_fqn*.

        Parameters
        ----------
        entry_fqn:
            FQN of the entry-point symbol (must be a key in the call graph).

        Returns
        -------
        TracedPath
            Structured call tree + flat sequence.

        Raises
        ------
        KeyError
            If *entry_fqn* is not present in the call graph.
        """
        flat:              List[PathNode] = []
        max_depth_reached: bool           = False

        def _dfs(fqn: str, depth: int, ancestors: Set[str], call_text: str, line: int) -> PathNode:
            nonlocal max_depth_reached

            node_entry = self._graph.node(fqn)
            is_unresolved = (node_entry is None) or (
                node_entry.kind == "unknown"
            )

            is_cycle = fqn in ancestors

            pnode = PathNode(
                fqn           = fqn,
                depth         = depth,
                call_text     = call_text,
                line          = line,
                is_cycle      = is_cycle,
                is_unresolved = is_unresolved,
            )
            flat.append(pnode)

            # Stop expanding under these conditions
            if is_cycle or depth >= self._max_depth:
                if depth >= self._max_depth and not is_cycle:
                    max_depth_reached = True
                return pnode

            if is_unresolved and not self._include_external:
                return pnode

            # Expand children
            new_ancestors = ancestors | {fqn}
            if node_entry:
                for edge in node_entry.calls:
                    if not self._include_external and not edge.resolved:
                        continue
                    child = _dfs(
                        edge.callee_fqn,
                        depth + 1,
                        new_ancestors,
                        edge.call_text,
                        edge.line,
                    )
                    pnode.children.append(child)

            return pnode

        root = _dfs(entry_fqn, 0, set(), "", 0)

        return TracedPath(
            entry             = entry_fqn,
            root              = root,
            flat_sequence     = flat,
            max_depth_reached = max_depth_reached,
        )

    def trace_all_entry_points(
        self,
        entry_fqns: Optional[List[str]] = None,
    ) -> Dict[str, TracedPath]:
        """Trace multiple entry points and return a mapping fqn → TracedPath.

        If *entry_fqns* is None, auto-detects entry points as all nodes
        in the call graph that have no *incoming* edges (i.e. nothing calls
        them — they are roots).
        """
        if entry_fqns is None:
            entry_fqns = [
                node.fqn
                for node in self._graph.all_nodes()
                if not node.called_by
            ]

        return {fqn: self.trace(fqn) for fqn in entry_fqns}
