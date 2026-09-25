"""
Analysis Engine smoke-test / demo.

Run against this repository::

    python3 -m src.analysis [repo_root] [entry_fqn]

*repo_root* defaults to ``.``
*entry_fqn* defaults to auto-detected entry points (call-graph roots).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
_here = Path(__file__).resolve()
for _parent in _here.parents:
    if (_parent / "src").is_dir():
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        break

from src.ingestion.walker import walk_repository          # noqa: E402
from src.ingestion.parsers.python_parser import PythonParser  # noqa: E402
from src.analysis.symbol_index import build_index         # noqa: E402
from src.analysis.call_graph import build_call_graph      # noqa: E402
from src.analysis.dep_graph import build_dep_graph        # noqa: E402
from src.analysis.path_tracer import PathTracer           # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _header(title: str) -> None:
    bar = "─" * 70
    print(f"\n{bar}")
    print(f"  {title}")
    print(bar)


def _tree_lines(node, prefix: str = "") -> list[str]:
    """Render a PathNode tree as text lines."""
    tag = ""
    if node.is_cycle:
        tag = " ↩ (cycle)"
    elif node.is_unresolved:
        tag = " ?"
    lines = [f"{prefix}{node.fqn}{tag}  (line {node.line})"]
    child_prefix = prefix + "    "
    for child in node.children:
        lines.extend(_tree_lines(child, child_prefix))
    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(repo_root: str = ".", entry_fqn: str | None = None) -> None:
    print(f"RepoPilot — Analysis Engine Demo")
    print(f"Repository : {Path(repo_root).resolve()}")

    # ── 1. Walk & Parse ─────────────────────────────────────────────────────
    _header("Step 1 · Ingestion")
    python_files = walk_repository(repo_root, languages={"python"})
    print(f"  Python files found : {len(python_files)}")

    parser = PythonParser()
    parse_results = [parser.parse(f.absolute_path) for f in python_files]
    errors = [r for r in parse_results if r["error"]]
    print(f"  Parse errors       : {len(errors)}")

    # ── 2. Symbol Index ─────────────────────────────────────────────────────
    _header("Step 2 · Symbol Index")
    index = build_index(python_files, parser)
    from src.analysis.symbol_index import SymbolKind
    kinds = {k: 0 for k in SymbolKind}
    for sym in index.all_symbols():
        kinds[sym.kind] += 1

    print(f"  Total symbols  : {len(index)}")
    for kind, count in kinds.items():
        print(f"    {kind.value:<12} : {count}")

    # Sample: first class found
    classes = [s for s in index.all_symbols() if s.kind == SymbolKind.CLASS]
    if classes:
        c = classes[0]
        print(f"\n  Sample class → {c.fqn}  (line {c.line})")
        print(f"    bases     : {c.bases}")
        print(f"    docstring : {(c.docstring or '')[:80]!r}")

    # ── 3. Dependency Graph ─────────────────────────────────────────────────
    _header("Step 3 · Dependency Graph")
    dep_graph = build_dep_graph(index, parse_results)
    internal  = dep_graph.internal_nodes()
    external  = dep_graph.external_packages()

    print(f"  Nodes (internal) : {len(internal)}")
    print(f"  Edges            : {len(dep_graph)}")
    print(f"  External pkgs    : {len(external)}")
    if external:
        print(f"    {', '.join(external[:10])}" + (" …" if len(external) > 10 else ""))

    print(f"\n  Topological order (first 10):")
    for i, mod in enumerate(dep_graph.topological_sort()[:10]):
        print(f"    {i+1:>2}. {mod}")

    # ── 4. Call Graph ────────────────────────────────────────────────────────
    _header("Step 4 · Call Graph")
    call_graph = build_call_graph(index, parse_results)
    print(f"  Nodes : {len(call_graph.all_nodes())}")
    print(f"  Edges : {len(call_graph)}")

    resolved   = sum(1 for _, _, e in call_graph.edges() if e.resolved)
    unresolved = len(call_graph) - resolved
    print(f"    resolved   : {resolved}")
    print(f"    unresolved : {unresolved}")

    # Top 5 most-called symbols
    nodes_by_in = sorted(
        call_graph.all_nodes(),
        key=lambda n: len(n.called_by),
        reverse=True,
    )[:5]
    if nodes_by_in:
        print(f"\n  Top called symbols:")
        for n in nodes_by_in:
            if n.called_by:
                print(f"    {n.fqn:<60} ← {len(n.called_by)} calls")

    # ── 5. Path Tracer ───────────────────────────────────────────────────────
    _header("Step 5 · Execution Path Tracer")
    tracer = PathTracer(call_graph, max_depth=8, include_external=False)

    if entry_fqn:
        targets = [entry_fqn]
    else:
        # Pick up to 3 call-graph roots (symbols with no callers)
        roots = [n.fqn for n in call_graph.all_nodes() if not n.called_by]
        targets = roots[:3]

    if not targets:
        print("  No entry points found in call graph — run with an explicit entry_fqn.")
    else:
        for target in targets:
            path = tracer.trace(target)
            print(f"\n  Entry : {path.entry}")
            print(f"  Depth reached : {len(set(n.depth for n in path.flat_sequence))-1}")
            print(f"  Total nodes   : {len(path.flat_sequence)}")
            print(f"  Unique symbols: {len(path.unique_fqns())}")
            if path.max_depth_reached:
                print("  ⚠ max_depth reached — tree is truncated")

            print("\n  Call tree:")
            for line in _tree_lines(path.root, "    "):
                print(line)

    # ── 6. Full JSON snapshot of one traced path ─────────────────────────────
    if targets:
        _header("Step 6 · JSON Snapshot (first traced path)")
        path = tracer.trace(targets[0])
        snapshot = {
            "entry":             path.entry,
            "max_depth_reached": path.max_depth_reached,
            "flat_sequence": [
                {"fqn": n.fqn, "depth": n.depth,
                 "is_cycle": n.is_cycle, "is_unresolved": n.is_unresolved}
                for n in path.flat_sequence
            ],
        }
        print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    _repo   = sys.argv[1] if len(sys.argv) > 1 else "."
    _entry  = sys.argv[2] if len(sys.argv) > 2 else None
    main(_repo, _entry)
