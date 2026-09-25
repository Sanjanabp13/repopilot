"""
Dependency Graph — module-level import relationship graph.

Each node is a **module FQN**.
Each directed edge ``(importer, importee)`` records that *importer*
contains an import statement that references *importee*.

Additional metadata on each edge captures:
- the names actually imported (``[]`` for bare ``import x``)
- whether the importee is a known internal module or an external package
- the source line number

Building the dependency graph
------------------------------
::

    from src.analysis.dep_graph import build_dep_graph
    dep_graph = build_dep_graph(index, parse_results)

    # Find everything that directly depends on walker
    dependents = dep_graph.dependents_of("src.ingestion.walker")

    # Topological order for a build/load plan
    order = dep_graph.topological_sort()
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DepEdge:
    """A directed import dependency between two modules."""
    importer:   str            # module FQN of the file that imports
    importee:   str            # module FQN of what is imported
    names:      List[str]      # specific names imported (empty = bare import)
    line:       int            # 1-based source line in the importer
    is_internal: bool          # True if importee is in the known symbol index


@dataclass
class DepNode:
    """A node in the dependency graph (one per module FQN)."""
    fqn:         str
    is_internal: bool                         # known to the symbol index?
    file_path:   str                          # empty for external packages
    imports:     List[DepEdge] = field(default_factory=list)   # outgoing
    imported_by: List[DepEdge] = field(default_factory=list)   # incoming


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

class DependencyGraph:
    """Directed module dependency graph.

    Nodes are module FQNs.  Edges are import statements.
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, DepNode] = {}
        self._edges: List[DepEdge]      = []

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def _get_or_create(self, fqn: str, is_internal: bool, file_path: str = "") -> DepNode:
        if fqn not in self._nodes:
            self._nodes[fqn] = DepNode(
                fqn         = fqn,
                is_internal = is_internal,
                file_path   = file_path,
            )
        return self._nodes[fqn]

    def add_edge(self, edge: DepEdge) -> None:
        """Register a :class:`DepEdge` and update both node edge lists."""
        self._edges.append(edge)
        imp_node  = self._get_or_create(edge.importer, True)
        importee  = self._get_or_create(edge.importee, edge.is_internal)
        imp_node.imports.append(edge)
        importee.imported_by.append(edge)

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def node(self, fqn: str) -> Optional[DepNode]:
        return self._nodes.get(fqn)

    def dependencies_of(self, module_fqn: str) -> List[str]:
        """Return module FQNs that *module_fqn* directly depends on."""
        n = self._nodes.get(module_fqn)
        return [e.importee for e in n.imports] if n else []

    def dependents_of(self, module_fqn: str) -> List[str]:
        """Return module FQNs that directly depend on *module_fqn*."""
        n = self._nodes.get(module_fqn)
        return [e.importer for e in n.imported_by] if n else []

    def transitive_dependencies_of(self, module_fqn: str) -> Set[str]:
        """BFS — return all transitive dependencies of *module_fqn*."""
        visited: Set[str] = set()
        queue = deque([module_fqn])
        while queue:
            current = queue.popleft()
            for dep in self.dependencies_of(current):
                if dep not in visited:
                    visited.add(dep)
                    queue.append(dep)
        visited.discard(module_fqn)
        return visited

    def transitive_dependents_of(self, module_fqn: str) -> Set[str]:
        """BFS — return all modules that transitively depend on *module_fqn*."""
        visited: Set[str] = set()
        queue = deque([module_fqn])
        while queue:
            current = queue.popleft()
            for dep in self.dependents_of(current):
                if dep not in visited:
                    visited.add(dep)
                    queue.append(dep)
        visited.discard(module_fqn)
        return visited

    def topological_sort(self) -> List[str]:
        """Return internal modules in dependency order (leaves first).

        Uses Kahn's algorithm.  Cycles are broken by omitting back-edges;
        cyclic nodes appear at the end of the list.
        """
        # Only consider internal nodes
        internal = {fqn for fqn, n in self._nodes.items() if n.is_internal}
        in_degree: Dict[str, int] = {fqn: 0 for fqn in internal}
        adjacency: Dict[str, List[str]] = {fqn: [] for fqn in internal}

        for edge in self._edges:
            if edge.importer in internal and edge.importee in internal:
                if edge.importee not in adjacency[edge.importer]:
                    adjacency[edge.importer].append(edge.importee)
                    in_degree[edge.importee] += 1

        queue = deque(fqn for fqn, deg in in_degree.items() if deg == 0)
        result: List[str] = []
        while queue:
            fqn = queue.popleft()
            result.append(fqn)
            for neighbour in adjacency[fqn]:
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)

        # Append any remaining nodes that are part of cycles
        remaining = [fqn for fqn in internal if fqn not in result]
        result.extend(sorted(remaining))
        return result

    def edges(self) -> List[Tuple[str, str, DepEdge]]:
        """Return all edges as (importer, importee, edge) tuples."""
        return [(e.importer, e.importee, e) for e in self._edges]

    def all_nodes(self) -> List[DepNode]:
        return list(self._nodes.values())

    def internal_nodes(self) -> List[DepNode]:
        return [n for n in self._nodes.values() if n.is_internal]

    def external_packages(self) -> List[str]:
        """Return sorted list of external package FQNs referenced."""
        return sorted(
            fqn for fqn, n in self._nodes.items() if not n.is_internal
        )

    def __len__(self) -> int:
        return len(self._edges)

    def __repr__(self) -> str:
        return (
            f"<DependencyGraph "
            f"nodes={len(self._nodes)} "
            f"edges={len(self._edges)}>"
        )


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_dep_graph(
    index,           # SymbolIndex — avoid circular import with string hint
    parse_results: Iterable[dict],
) -> DependencyGraph:
    """Build a :class:`DependencyGraph` from parsed source files.

    Parameters
    ----------
    index:
        A populated :class:`~src.analysis.symbol_index.SymbolIndex`.
        Used to decide whether each importee is an *internal* module.
    parse_results:
        Iterable of parser result dicts.

    Returns
    -------
    DependencyGraph
    """
    from .symbol_index import _file_path_to_module_fqn  # local to avoid cycle

    graph = DependencyGraph()

    # Register all known internal modules upfront so is_internal is accurate.
    known_modules: Set[str] = {
        sym.module_fqn for sym in index.all_modules()
    }

    for result in parse_results:
        if result.get("error"):
            continue

        file_path   = result["file_path"]
        importer    = _file_path_to_module_fqn(file_path)

        # Ensure the importer node exists with correct file path
        graph._get_or_create(importer, True, file_path)

        for imp in result.get("imports", []):
            module = imp.get("module", "")
            if not module:
                continue

            # Normalise: "from .sibling import X" has a relative module name;
            # resolve against the importer's package.
            importee = _resolve_importee(module, importer)

            is_internal = (
                importee in known_modules
                or any(m.startswith(importee + ".") for m in known_modules)
                or any(m == importee for m in known_modules)
            )

            edge = DepEdge(
                importer    = importer,
                importee    = importee,
                names       = list(imp.get("names", [])),
                line        = imp.get("line", 0),
                is_internal = is_internal,
            )
            graph.add_edge(edge)

    return graph


def _resolve_importee(module: str, importer_fqn: str) -> str:
    """Resolve a (possibly relative) module name to an absolute FQN.

    Relative imports like ``..sibling`` are resolved against *importer_fqn*.
    Absolute imports are returned as-is.
    """
    if not module.startswith("."):
        return module

    # Count leading dots
    dots = len(module) - len(module.lstrip("."))
    rel  = module.lstrip(".")

    parts = importer_fqn.split(".")
    # Go up `dots` levels from the current package
    base_parts = parts[: max(0, len(parts) - dots)]
    if rel:
        base_parts.append(rel)
    return ".".join(base_parts) if base_parts else rel
