"""
Entry point for:  python3 -m src.ingestion.parsers.python_parser [repo_root]

Runs the PythonParser smoke-test against *repo_root* (defaults to ".").
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path.
_here = Path(__file__).resolve()
for _parent in _here.parents:
    if (_parent / "src").is_dir():
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        break

from src.ingestion.parsers.python_parser import PythonParser  # noqa: E402
from src.ingestion.walker import walk_repository               # noqa: E402


def main(repo_root: str = ".") -> None:
    print(f"Scanning repository: {os.path.abspath(repo_root)}\n")

    python_files = walk_repository(repo_root, languages={"python"})
    if not python_files:
        print("No Python files found.")
        return

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
        })

    # ---- compact summary table ----------------------------------------
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

    # ---- full JSON detail for the first file --------------------------
    print("\n── Full parse result for first file ──────────────────────────────────\n")
    first_full = parser.parse(python_files[0].absolute_path)
    print(json.dumps(first_full, indent=2, default=str))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
