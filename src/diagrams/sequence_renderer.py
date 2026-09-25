"""
Sequence diagram renderer for execution path traces.
"""

from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple

from src.analysis.path_tracer import PathNode, TracedPath


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fqn_to_participant(fqn: str) -> str:
    """Convert a FQN to a Mermaid-safe participant alias (alphanumeric + _)."""
    return re.sub(r"[^A-Za-z0-9_]", "_", fqn)


def _short_name(fqn: str) -> str:
    """Return the last segment of a dotted FQN."""
    return fqn.split(".")[-1] or fqn


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class SequenceRenderer:
    """Renders a :class:`~src.analysis.path_tracer.TracedPath` as a Mermaid
    sequence diagram."""

    def render_execution_trace(
        self,
        traced_path: TracedPath,
        title: str = "Execution Trace",
    ) -> str:
        """Convert *traced_path* into a Mermaid sequence diagram.

        - Participants are declared in DFS pre-order (deduped).
        - Each parent→child edge in the tree becomes a message arrow:
          ``caller ->> callee: call_text``
        - Cycle nodes get a ``Note over`` annotation.
        - Unresolved nodes get a ``Note over`` annotation.

        Returns
        -------
        str
            Complete Mermaid markdown string starting with triple-backtick mermaid.
        """
        lines: List[str] = [
            f"---",
            f"title: {title}",
            f"---",
            "sequenceDiagram",
        ]

        # --- collect participants in DFS pre-order (deduped) ------------------
        seen_fqns: Set[str] = set()
        participants: List[str] = []  # ordered FQNs

        def _collect_participants(node: PathNode) -> None:
            if node.fqn not in seen_fqns:
                seen_fqns.add(node.fqn)
                participants.append(node.fqn)
            # Always recurse so we capture all tree nodes in DFS order
            for child in node.children:
                _collect_participants(child)

        _collect_participants(traced_path.root)

        # Declare participants with short aliases
        for fqn in participants:
            alias = _fqn_to_participant(fqn)
            label = _short_name(fqn)
            lines.append(f"    participant {alias} as {label}")

        lines.append("")

        # --- collect per-FQN annotations (cycle / unresolved) -----------------
        # Walk flat_sequence; first occurrence wins for annotation purposes.
        annotated: Set[str] = set()
        annotations: Dict[str, str] = {}  # fqn → annotation text
        for node in traced_path.flat_sequence:
            if node.fqn in annotated:
                continue
            if node.is_cycle:
                annotated.add(node.fqn)
                annotations[node.fqn] = "cycle detected"
            elif node.is_unresolved:
                annotated.add(node.fqn)
                annotations[node.fqn] = "external/unresolved"

        # --- emit message arrows using tree edges (DFS order) -----------------
        def _emit_edges(node: PathNode) -> None:
            for child in node.children:
                src  = _fqn_to_participant(node.fqn)
                dst  = _fqn_to_participant(child.fqn)
                # Use call_text if available, else short name of callee
                msg  = child.call_text if child.call_text else _short_name(child.fqn)
                lines.append(f"    {src} ->> {dst}: {msg}")

                # Annotations immediately after the arrow that introduces the node
                if child.fqn in annotations:
                    note_alias = _fqn_to_participant(child.fqn)
                    note_text  = annotations.pop(child.fqn)
                    lines.append(f"    Note over {note_alias}: {note_text}")

                # Don't recurse into cycle nodes (children not expanded)
                if not child.is_cycle:
                    _emit_edges(child)

        _emit_edges(traced_path.root)

        # Annotate root if it is itself unresolved (edge case)
        if traced_path.root.fqn in annotations:
            alias     = _fqn_to_participant(traced_path.root.fqn)
            note_text = annotations.pop(traced_path.root.fqn)
            lines.insert(
                lines.index("") + 1,
                f"    Note over {alias}: {note_text}",
            )

        return self._wrap(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _wrap(lines: List[str]) -> str:
        """Wrap diagram lines in a Mermaid fenced code block."""
        body = "\n".join(lines)
        return f"```mermaid\n{body}\n```"
