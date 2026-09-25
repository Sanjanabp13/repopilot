"""
Mermaid diagram renderer for call graphs, dependency graphs, and blast-radius
impact maps.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from src.analysis.call_graph import CallGraph
from src.analysis.dep_graph import DependencyGraph
from src.analysis.impact import ImpactResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fqn_to_id(fqn: str) -> str:
    """Convert a dotted FQN to a Mermaid-safe node ID (alphanumeric + _)."""
    return re.sub(r"[^A-Za-z0-9_]", "_", fqn)


def _short_name(fqn: str) -> str:
    """Return the last segment of a dotted FQN."""
    return fqn.split(".")[-1] or fqn


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class MermaidRenderer:
    """Renders analysis data structures as Mermaid diagram strings."""

    # ------------------------------------------------------------------
    # Call graph
    # ------------------------------------------------------------------

    def render_call_graph(
        self,
        call_graph: CallGraph,
        title: str = "Call Graph",
    ) -> str:
        """Render *call_graph* as a Mermaid flowchart LR.

        Node shapes by kind
        -------------------
        - function : ``([name])``  — stadium / pill shape
        - class    : ``[[name]]``  — subroutine shape
        - method   : ``(name)``    — rounded rectangle

        Only resolved edges are rendered by default; unresolved edges are
        shown as dashed (``-.->``) to distinguish "dark" call targets.
        """
        lines: List[str] = [f"---", f"title: {title}", f"---", "flowchart LR"]

        nodes = call_graph.all_nodes()
        if not nodes:
            lines.append("    %% empty graph")
            return self._wrap(lines)

        # Emit node declarations with shapes and tooltips
        for node in nodes:
            nid   = _fqn_to_id(node.fqn)
            label = _short_name(node.fqn)
            kind  = node.kind

            if kind == "function":
                shape = f'([{label}])'
            elif kind == "class":
                shape = f'[[{label}]]'
            else:
                # method, module, unknown → rounded rectangle
                shape = f'({label})'

            lines.append(f'    {nid}{shape}')
            lines.append(f'    click {nid} callback "{node.fqn}"')

        lines.append("")

        # Emit edges
        seen_edges: Set[tuple] = set()
        for caller_fqn, callee_fqn, edge in call_graph.edges():
            key = (caller_fqn, callee_fqn)
            if key in seen_edges:
                continue
            seen_edges.add(key)

            src = _fqn_to_id(caller_fqn)
            dst = _fqn_to_id(callee_fqn)
            arrow = "-->" if edge.resolved else "-.->"
            lines.append(f"    {src} {arrow} {dst}")

        return self._wrap(lines)

    # ------------------------------------------------------------------
    # Dependency graph
    # ------------------------------------------------------------------

    def render_dep_graph(
        self,
        dep_graph: DependencyGraph,
        title: str = "Dependencies",
    ) -> str:
        """Render *dep_graph* as a Mermaid flowchart TD.

        Internal modules use solid rectangle nodes; external packages use
        a dashed style applied via ``classDef``.
        """
        lines: List[str] = [f"---", f"title: {title}", f"---", "flowchart TD"]

        nodes = dep_graph.all_nodes()
        if not nodes:
            lines.append("    %% empty graph")
            return self._wrap(lines)

        # classDef for external packages
        lines.append("    classDef external stroke-dasharray:5 5,fill:#f0f0f0,color:#555")
        lines.append("")

        external_ids: List[str] = []

        for node in nodes:
            nid   = _fqn_to_id(node.fqn)
            label = _short_name(node.fqn)
            lines.append(f'    {nid}["{label}"]')
            if not node.is_internal:
                external_ids.append(nid)

        if external_ids:
            lines.append("")
            lines.append("    class " + ",".join(external_ids) + " external")

        lines.append("")

        # Edges: importer --> importee
        seen_edges: Set[tuple] = set()
        for importer, importee, _edge in dep_graph.edges():
            key = (importer, importee)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            src = _fqn_to_id(importer)
            dst = _fqn_to_id(importee)
            lines.append(f"    {src} --> {dst}")

        return self._wrap(lines)

    # ------------------------------------------------------------------
    # Impact / blast-radius
    # ------------------------------------------------------------------

    def render_impact(
        self,
        impact_result: ImpactResult,
        call_graph: CallGraph,
        title: str = "Blast Radius",
    ) -> str:
        """Render *impact_result* as a Mermaid flowchart LR blast-radius map.

        Colour scheme
        -------------
        - Changed symbol   : ``fill:#ff6b6b`` (red)
        - Direct callers   : ``fill:#ffd93d`` (amber)
        - Transitive callers: ``fill:#fff3cd`` (light yellow)
        - Test files       : ``fill:#cce5ff`` (blue) — overrides hop colour
        """
        lines: List[str] = [f"---", f"title: {title}", f"---", "flowchart LR"]

        # --- collect all FQNs in this diagram ---------------------------------
        all_symbols = impact_result.all_impacted()

        # Changed symbol may or may not have a CallNode
        changed_fqn = impact_result.changed_fqn
        changed_id  = _fqn_to_id(changed_fqn)
        changed_label = _short_name(changed_fqn)

        # Build sets for style lookup
        test_fqns: Set[str]        = {s.fqn for s in impact_result.affected_tests}
        direct_fqns: Set[str]      = {s.fqn for s in impact_result.direct_callers}
        transitive_fqns: Set[str]  = {s.fqn for s in impact_result.transitive_callers}

        # --- node declarations ------------------------------------------------
        lines.append(f'    {changed_id}(("{changed_label}"))')  # double circle = changed

        for sym in all_symbols:
            nid   = _fqn_to_id(sym.fqn)
            label = sym.name or _short_name(sym.fqn)
            lines.append(f'    {nid}["{label}"]')

        lines.append("")

        # --- edges from call graph connecting nodes in this diagram -----------
        diagram_fqns: Set[str] = {changed_fqn} | {s.fqn for s in all_symbols}
        seen_edges: Set[tuple] = set()

        for caller_fqn, callee_fqn, edge in call_graph.edges():
            if caller_fqn not in diagram_fqns or callee_fqn not in diagram_fqns:
                continue
            key = (caller_fqn, callee_fqn)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            src   = _fqn_to_id(caller_fqn)
            dst   = _fqn_to_id(callee_fqn)
            arrow = "-->" if edge.resolved else "-.->"
            lines.append(f"    {src} {arrow} {dst}")

        lines.append("")

        # --- styles -----------------------------------------------------------
        lines.append(f"    style {changed_id} fill:#ff6b6b,color:#fff,stroke:#c0392b")

        for sym in all_symbols:
            nid = _fqn_to_id(sym.fqn)
            # Test overrides hop colour
            if sym.fqn in test_fqns:
                lines.append(f"    style {nid} fill:#cce5ff,stroke:#4a90d9")
            elif sym.fqn in direct_fqns:
                lines.append(f"    style {nid} fill:#ffd93d,stroke:#e6b800")
            else:
                lines.append(f"    style {nid} fill:#fff3cd,stroke:#c8a900")

        return self._wrap(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _wrap(lines: List[str]) -> str:
        """Wrap diagram lines in a Mermaid fenced code block."""
        body = "\n".join(lines)
        return f"```mermaid\n{body}\n```"
