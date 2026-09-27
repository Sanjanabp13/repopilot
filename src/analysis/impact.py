"""
Impact / Blast-Radius Analyzer.

Given a symbol FQN (a function, method, or class), answers the question:

    "If this symbol's signature or behaviour changes, what else in the
     codebase would break or need review?"

This is the core value proposition of RepoPilot.  Every other module
feeds data into this one.

Algorithm
---------
1. Start from *symbol_fqn* in the :class:`~src.analysis.call_graph.CallGraph`.
2. **Reverse-BFS** over ``called_by`` edges: collect every symbol that
   (transitively) calls the changed symbol.
3. Classify each hit as DIRECT (one hop) or TRANSITIVE (two or more hops).
4. Cross-reference the :class:`~src.analysis.symbol_index.SymbolIndex` to
   enrich each impacted symbol with file path, line, kind, and docstring.
5. Detect test files (path contains ``test``) and tag them separately so
   the caller can highlight "tests that must be re-run."
6. Return a structured :class:`ImpactResult` that is independently
   serialisable to JSON — no graph objects leak out.

Usage::

    from src.analysis.impact import ImpactAnalyzer, ImpactResult

    analyzer = ImpactAnalyzer(index, call_graph)
    result   = analyzer.get_downstream_impact("src.payments.processor.charge")

    print(result.summary())
    for sym in result.direct_callers:
        print(" direct:", sym.fqn, sym.file_path, sym.line)
    for sym in result.transitive_callers:
        print(" transitive:", sym.fqn)
    for sym in result.affected_tests:
        print(" test:", sym.fqn)
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .symbol_index import Symbol, SymbolIndex, SymbolKind
from .call_graph import CallGraph


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ImpactedSymbol:
    """Enriched record for a single symbol in the blast radius.

    Attributes
    ----------
    fqn:
        Fully-qualified name of the impacted symbol.
    name:
        Simple name.
    kind:
        Symbol kind (function / method / class / module).
    file_path:
        Absolute source file path.
    line:
        1-based definition line.
    docstring:
        Symbol docstring, or *None*.
    hop:
        Distance (in call-graph hops) from the changed symbol.
        ``1`` = direct caller, ``2+`` = transitive.
    is_test:
        True when the file path looks like a test file.
    parent_fqn:
        FQN of the enclosing class for methods, or *None*.
    """

    fqn:        str
    name:       str
    kind:       str           # SymbolKind.value string
    file_path:  str
    line:       int
    docstring:  Optional[str] = None
    hop:        int           = 1
    is_test:    bool          = False
    parent_fqn: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "fqn":        self.fqn,
            "name":       self.name,
            "kind":       self.kind,
            "file_path":  self.file_path,
            "line":       self.line,
            "docstring":  self.docstring,
            "hop":        self.hop,
            "is_test":    self.is_test,
            "parent_fqn": self.parent_fqn,
        }


@dataclass
class ImpactResult:
    """Full blast-radius report for a single changed symbol.

    Attributes
    ----------
    changed_fqn:
        The symbol whose change triggered this analysis.
    changed_symbol:
        Enriched metadata for the changed symbol itself (may be *None*
        if the FQN is not in the symbol index — e.g. an external callee).
    direct_callers:
        Symbols that call *changed_fqn* directly (hop == 1).
    transitive_callers:
        Symbols reachable via two or more hops (hop >= 2).
    affected_tests:
        Subset of all impacted symbols whose file path indicates a test.
    affected_files:
        Deduplicated sorted list of file paths containing any impacted symbol.
    total_impact:
        Total count of impacted symbols (direct + transitive).
    """

    changed_fqn:         str
    changed_symbol:      Optional[ImpactedSymbol]
    direct_callers:      List[ImpactedSymbol] = field(default_factory=list)
    transitive_callers:  List[ImpactedSymbol] = field(default_factory=list)
    affected_tests:      List[ImpactedSymbol] = field(default_factory=list)
    affected_files:      List[str]            = field(default_factory=list)

    @property
    def total_impact(self) -> int:
        return len(self.direct_callers) + len(self.transitive_callers)

    def all_impacted(self) -> List[ImpactedSymbol]:
        """Return direct + transitive callers merged, sorted by hop then fqn."""
        return sorted(
            self.direct_callers + self.transitive_callers,
            key=lambda s: (s.hop, s.fqn),
        )

    def summary(self) -> str:
        lines = [
            f"Impact report for: {self.changed_fqn}",
            f"  Direct callers    : {len(self.direct_callers)}",
            f"  Transitive callers: {len(self.transitive_callers)}",
            f"  Affected tests    : {len(self.affected_tests)}",
            f"  Affected files    : {len(self.affected_files)}",
        ]
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "changed_fqn":        self.changed_fqn,
            "changed_symbol":     self.changed_symbol.as_dict() if self.changed_symbol else None,
            "total_impact":       self.total_impact,
            "direct_callers":     [s.as_dict() for s in self.direct_callers],
            "transitive_callers": [s.as_dict() for s in self.transitive_callers],
            "affected_tests":     [s.as_dict() for s in self.affected_tests],
            "affected_files":     self.affected_files,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, default=str)


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

def _is_test_path(file_path: str) -> bool:
    """Heuristic: check whether the file path or symbol name indicates a test."""
    from pathlib import Path
    p = Path(file_path)
    name = p.name.lower()
    if name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py":
        return True
    if "test" in p.stem.lower():
        return True
    for part in p.parts[-3:-1]:
        if part.lower() in ("test", "tests", "testing"):
            return True
    return False


def _make_impacted(symbol: Symbol, hop: int) -> ImpactedSymbol:
    return ImpactedSymbol(
        fqn        = symbol.fqn,
        name       = symbol.name,
        kind       = symbol.kind.value,
        file_path  = symbol.file_path,
        line       = symbol.line,
        docstring  = symbol.docstring,
        hop        = hop,
        is_test    = _is_test_path(symbol.file_path),
        parent_fqn = symbol.parent_fqn,
    )


def _make_impacted_unknown(fqn: str, hop: int) -> ImpactedSymbol:
    """Fallback for a caller FQN that isn't in the symbol index."""
    name = fqn.split(".")[-1]
    return ImpactedSymbol(
        fqn       = fqn,
        name      = name,
        kind      = SymbolKind.FUNCTION.value,
        file_path = "",
        line      = 0,
        hop       = hop,
        is_test   = _is_test_path(fqn),
    )


class ImpactAnalyzer:
    """Computes the downstream blast radius for any symbol in the codebase.

    Parameters
    ----------
    index:
        Populated :class:`~src.analysis.symbol_index.SymbolIndex`.
    call_graph:
        Populated :class:`~src.analysis.call_graph.CallGraph`.
    max_hops:
        Maximum number of call-graph hops to traverse (default unlimited,
        pass an integer to cap at that depth).  Set to ``1`` to get only
        direct callers.
    """

    def __init__(
        self,
        index: SymbolIndex,
        call_graph: CallGraph,
        max_hops: int = 0,          # 0 = unlimited
    ) -> None:
        self._index      = index
        self._graph      = call_graph
        self._max_hops   = max_hops

    def _resolve_symbol_fqn(self, symbol_fqn: str) -> str:
        """Resolve a short name, partial FQN, or symbol name to a known node FQN."""
        # 1. Exact match in call graph
        if self._graph.node(symbol_fqn) is not None:
            return symbol_fqn

        # 2. Exact match in symbol index
        sym = self._index.lookup(symbol_fqn)
        if sym and self._graph.node(sym.fqn) is not None:
            return sym.fqn

        # 3. If symbol_fqn has dots (e.g. UserService.get_user), check suffix match
        if "." in symbol_fqn:
            suffix = f".{symbol_fqn}"
            graph_matches = [
                n.fqn for n in self._graph.all_nodes()
                if n.fqn == symbol_fqn or n.fqn.endswith(suffix)
            ]
            if graph_matches:
                with_callers = [
                    fqn for fqn in graph_matches
                    if len(self._graph.callers_of(fqn)) > 0
                ]
                return with_callers[0] if with_callers else graph_matches[0]

        # 4. Short-name lookup via index
        simple_name = symbol_fqn.split(".")[-1]
        matches = self._index.find_by_name(simple_name)
        if matches:
            graph_matched = [
                m.fqn for m in matches
                if self._graph.node(m.fqn) is not None
            ]
            with_callers = [
                fqn for fqn in graph_matched
                if len(self._graph.callers_of(fqn)) > 0
            ]
            if with_callers:
                return with_callers[0]
            if graph_matched:
                return graph_matched[0]
            methods = [m for m in matches if m.kind == SymbolKind.METHOD]
            return (methods[0] if methods else matches[0]).fqn

        # 5. Check call graph nodes by simple name
        nodes_by_name = [
            n for n in self._graph.all_nodes()
            if n.fqn.split(".")[-1] == simple_name or n.fqn.endswith(f".{simple_name}")
        ]
        if nodes_by_name:
            with_callers = [n.fqn for n in nodes_by_name if len(n.called_by) > 0]
            return with_callers[0] if with_callers else nodes_by_name[0].fqn

        return symbol_fqn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _compute_bfs(self, target_fqn: str) -> ImpactResult:
        """Run reverse BFS starting from a single resolved symbol FQN."""
        changed_sym_raw = self._index.lookup(target_fqn)
        changed_symbol = (
            _make_impacted(changed_sym_raw, 0) if changed_sym_raw else None
        )

        visited: Dict[str, int] = {}   # fqn → first-seen hop count
        queue: deque[tuple[str, int]] = deque([(target_fqn, 0)])

        while queue:
            current_fqn, hop = queue.popleft()

            node = self._graph.node(current_fqn)
            if node is None:
                continue

            for edge in node.called_by:
                caller_fqn = edge.caller_fqn
                if caller_fqn == target_fqn:
                    continue                    # skip self-reference
                next_hop = hop + 1
                if caller_fqn in visited:
                    continue                    # already reached via shorter path
                if self._max_hops and next_hop > self._max_hops:
                    continue                    # depth cap
                visited[caller_fqn] = next_hop
                queue.append((caller_fqn, next_hop))

        # ---- classify results -------------------------------------------
        direct_callers:     List[ImpactedSymbol] = []
        transitive_callers: List[ImpactedSymbol] = []
        affected_tests:     List[ImpactedSymbol] = []
        affected_files:     Set[str]             = set()

        for caller_fqn, hop in visited.items():
            raw = self._index.lookup(caller_fqn)
            impacted = (
                _make_impacted(raw, hop)
                if raw
                else _make_impacted_unknown(caller_fqn, hop)
            )

            if hop == 1:
                direct_callers.append(impacted)
            else:
                transitive_callers.append(impacted)

            if impacted.is_test:
                affected_tests.append(impacted)

            if impacted.file_path:
                affected_files.add(impacted.file_path)

        # Stable sort: by hop, then fqn
        direct_callers.sort(key=lambda s: s.fqn)
        transitive_callers.sort(key=lambda s: (s.hop, s.fqn))
        affected_tests.sort(key=lambda s: s.fqn)

        return ImpactResult(
            changed_fqn        = target_fqn,
            changed_symbol     = changed_symbol,
            direct_callers     = direct_callers,
            transitive_callers = transitive_callers,
            affected_tests     = affected_tests,
            affected_files     = sorted(affected_files),
        )

    def get_downstream_impact(self, symbol_fqn: str) -> ImpactResult:
        """Return the full blast-radius report for *symbol_fqn*.

        Parameters
        ----------
        symbol_fqn:
            Fully-qualified name or short name of the symbol that is changing.

        Returns
        -------
        ImpactResult
            Structured, JSON-serialisable impact report.
        """
        resolved_fqn = self._resolve_symbol_fqn(symbol_fqn)

        # Delegate class refactor to get_impact_for_class
        resolved_sym = self._index.lookup(resolved_fqn)
        if resolved_sym and resolved_sym.kind == SymbolKind.CLASS:
            return self.get_impact_for_class(resolved_fqn)

        return self._compute_bfs(resolved_fqn)

    def get_impact_for_class(self, class_fqn: str) -> ImpactResult:
        """Return the union impact for a class *and* all its methods.

        Useful when an entire class is being refactored: every caller of
        every method is included in one report.
        """
        resolved_class_fqn = self._resolve_symbol_fqn(class_fqn)
        class_sym = self._index.lookup(resolved_class_fqn)
        if class_sym is None or class_sym.kind != SymbolKind.CLASS:
            return self._compute_bfs(resolved_class_fqn)

        # Collect method FQNs
        method_fqns = [
            s.fqn
            for s in self._index.symbols_in_module(class_sym.module_fqn)
            if s.kind == SymbolKind.METHOD and s.parent_fqn == resolved_class_fqn
        ]

        # Union BFS across class + all methods
        merged: Dict[str, ImpactedSymbol] = {}
        for fqn in [resolved_class_fqn] + method_fqns:
            sub = self._compute_bfs(fqn)
            for sym in sub.all_impacted():
                if sym.fqn not in merged or sym.hop < merged[sym.fqn].hop:
                    merged[sym.fqn] = sym

        direct_callers     = [s for s in merged.values() if s.hop == 1]
        transitive_callers = [s for s in merged.values() if s.hop > 1]
        affected_tests     = [s for s in merged.values() if s.is_test]
        affected_files     = sorted({s.file_path for s in merged.values() if s.file_path})

        changed_sym_raw = self._index.lookup(resolved_class_fqn)
        return ImpactResult(
            changed_fqn        = resolved_class_fqn,
            changed_symbol     = _make_impacted(changed_sym_raw, 0) if changed_sym_raw else None,
            direct_callers     = sorted(direct_callers, key=lambda s: s.fqn),
            transitive_callers = sorted(transitive_callers, key=lambda s: (s.hop, s.fqn)),
            affected_tests     = sorted(affected_tests, key=lambda s: s.fqn),
            affected_files     = affected_files,
        )
