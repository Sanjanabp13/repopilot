"""
Python AST parser for RepoPilot.

Uses Python's built-in :mod:`ast` module — zero external dependencies —
to extract a rich structural summary from a `.py` source file.

Extracted information
---------------------
- **Imports** — both ``import x`` and ``from x import y`` forms, with
  alias support and source line numbers.
- **Classes** — name, base classes, class-level docstring, and a full
  list of methods (args, type annotations, decorators, docstring, line).
- **Top-level functions** — same rich metadata as methods.

All extraction is read-only; the source file is never modified.  Syntax
errors and I/O errors are caught and stored in the ``"error"`` key of
the returned dict so the caller can continue processing other files.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

from .base import BaseParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _annotation_to_str(node: ast.expr | None) -> str | None:
    """Convert an annotation AST node to a human-readable string."""
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _decorator_to_str(node: ast.expr) -> str:
    """Convert a decorator AST node to a human-readable string."""
    try:
        return ast.unparse(node)
    except Exception:
        return repr(node)


def _extract_args(args: ast.arguments) -> tuple[list[str], dict[str, str]]:
    """Return (arg_names, annotations_dict) from a function's argument list.

    *annotations_dict* maps each argument name to its annotation source
    string.  ``"return"`` is included when a return annotation is present.
    """
    all_args = (
        args.posonlyargs
        + args.args
        + ([args.vararg] if args.vararg else [])
        + args.kwonlyargs
        + ([args.kwarg] if args.kwarg else [])
    )
    names: list[str] = []
    annotations: dict[str, str] = {}

    for arg in all_args:
        name = arg.arg
        names.append(name)
        ann = _annotation_to_str(arg.annotation)
        if ann is not None:
            annotations[name] = ann

    return names, annotations


def _extract_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    """Build the function/method summary dict from an AST node."""
    names, annotations = _extract_args(node.args)

    # Return annotation
    ret = _annotation_to_str(node.returns)
    if ret is not None:
        annotations["return"] = ret

    return {
        "name":        node.name,
        "args":        names,
        "annotations": annotations,
        "docstring":   ast.get_docstring(node),
        "line":        node.lineno,
        "decorators":  [_decorator_to_str(d) for d in node.decorator_list],
    }


def _extract_class(node: ast.ClassDef) -> dict:
    """Build the class summary dict (including its methods) from an AST node."""
    bases = []
    for base in node.bases:
        try:
            bases.append(ast.unparse(base))
        except Exception:
            bases.append(repr(base))

    methods: list[dict] = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(_extract_function(item))

    return {
        "name":      node.name,
        "bases":     bases,
        "docstring": ast.get_docstring(node),
        "line":      node.lineno,
        "methods":   methods,
    }


def _extract_import(node: ast.Import) -> list[dict]:
    """Convert a bare ``import x [as y]`` node into import records."""
    records = []
    for alias in node.names:
        records.append({
            "kind":   "import",
            "module": alias.name,
            "names":  [],
            "alias":  alias.asname,
            "line":   node.lineno,
        })
    return records


def _extract_from_import(node: ast.ImportFrom) -> list[dict]:
    """Convert a ``from x import y [as z]`` node into import records."""
    module = node.module or ""
    records = []
    for alias in node.names:
        records.append({
            "kind":   "from",
            "module": module,
            "names":  [alias.name],
            "alias":  alias.asname,
            "line":   node.lineno,
        })
    return records


# ---------------------------------------------------------------------------
# Parser class
# ---------------------------------------------------------------------------

class PythonParser(BaseParser):
    """Concrete AST-based parser for Python source files."""

    language: str = "python"

    def parse(self, file_path: str) -> dict:
        """Parse *file_path* and return a structured summary.

        Parameters
        ----------
        file_path:
            Path to the ``.py`` file to parse.

        Returns
        -------
        dict
            Conforms to the schema defined in :mod:`src.ingestion.parsers.base`.
            On error, ``"error"`` is set and all list fields are empty.
        """
        result = self._empty_result(file_path, self.language)

        # ---- read source ------------------------------------------------
        try:
            source = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            result["error"] = f"IOError: {exc}"
            return result

        # ---- parse AST --------------------------------------------------
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError as exc:
            result["error"] = (
                f"SyntaxError at line {exc.lineno}: {exc.msg}"
            )
            return result
        except Exception as exc:  # pragma: no cover — defensive catch-all
            result["error"] = f"ParseError: {exc}"
            return result

        # ---- walk top-level nodes ---------------------------------------
        imports: list[dict] = []
        classes: list[dict] = []
        functions: list[dict] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                imports.extend(_extract_import(node))

            elif isinstance(node, ast.ImportFrom):
                imports.extend(_extract_from_import(node))

            elif isinstance(node, ast.ClassDef):
                classes.append(_extract_class(node))

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(_extract_function(node))

        result["imports"]   = imports
        result["classes"]   = classes
        result["functions"] = functions
        return result


# ---------------------------------------------------------------------------
# Quick smoke-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import os
    import warnings

    warnings.filterwarnings("ignore", category=RuntimeWarning, module="runpy")

    repo_root = sys.argv[1] if len(sys.argv) > 1 else "."

    # Ensure the project root is on sys.path so absolute imports work when
    # this module is executed via `python3 -m src.ingestion.parsers.python_parser`.
    _here = Path(__file__).resolve()
    for _parent in _here.parents:
        if (_parent / "src").is_dir():
            if str(_parent) not in sys.path:
                sys.path.insert(0, str(_parent))
            break

    from src.ingestion.walker import walk_repository

    print(f"Scanning repository: {os.path.abspath(repo_root)}\n")

    python_files = walk_repository(repo_root, languages={"python"})
    parser = PythonParser()

    summary: list[dict[str, Any]] = []

    for source_file in python_files:
        parsed = parser.parse(source_file.absolute_path)
        summary.append({
            "file":      source_file.relative_path,
            "error":     parsed["error"],
            "imports":   len(parsed["imports"]),
            "classes":   [c["name"] for c in parsed["classes"]],
            "functions": [f["name"] for f in parsed["functions"]],
            # Include full detail for the first file as a sample
            "_detail":   parsed if source_file == python_files[0] else None,
        })

    # Pretty-print a compact summary table
    print(f"{'FILE':<55} {'ERR':>3} {'IMP':>4} {'CLS':>4} {'FNS':>4}")
    print("-" * 75)
    for row in summary:
        err_flag = "✗" if row["error"] else " "
        print(
            f"{row['file']:<55} {err_flag:>3} "
            f"{row['imports']:>4} "
            f"{len(row['classes']):>4} "
            f"{len(row['functions']):>4}"
        )

    # Full JSON of the first file
    if summary:
        print("\n── Full parse result for first file ──────────────────────────────────\n")
        first_full = parser.parse(python_files[0].absolute_path)
        print(json.dumps(first_full, indent=2, default=str))
