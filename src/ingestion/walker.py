"""
Repository file walker.

Walks a repository root recursively and returns structured metadata for
every source file that passes the ignore filters.  Supports:

  - Hard-coded ignore list for common non-source directories.
  - `.gitignore` rule parsing via the `pathspec` library (falls back to
    ignore-list-only mode if `pathspec` is not installed).
  - Language detection by file extension.
  - Optional filtering to a specific set of languages.

Usage::

    from src.ingestion.walker import walk_repository

    files = walk_repository("/path/to/repo", languages={"python"})
    for f in files:
        print(f["relative_path"], f["language"])
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Set

# ---------------------------------------------------------------------------
# Optional dependency: pathspec (pip install pathspec)
# ---------------------------------------------------------------------------
try:
    import pathspec  # type: ignore
    _PATHSPEC_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PATHSPEC_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Directories that are *always* skipped regardless of .gitignore.
HARD_IGNORE_DIRS: Set[str] = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".env",
    "dist",
    "build",
    "target",       # Rust / Java Maven
    ".tox",
    "htmlcov",
    "site-packages",
    ".idea",
    ".vscode",
}

#: File extensions → canonical language name.
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py":    "python",
    ".js":    "javascript",
    ".ts":    "typescript",
    ".jsx":   "javascript",
    ".tsx":   "typescript",
    ".java":  "java",
    ".go":    "go",
    ".rb":    "ruby",
    ".rs":    "rust",
    ".cpp":   "cpp",
    ".cc":    "cpp",
    ".cxx":   "cpp",
    ".c":     "c",
    ".h":     "c",
    ".cs":    "csharp",
    ".php":   "php",
    ".swift": "swift",
    ".kt":    "kotlin",
    ".scala": "scala",
    ".sh":    "shell",
    ".bash":  "shell",
    ".yaml":  "yaml",
    ".yml":   "yaml",
    ".toml":  "toml",
    ".json":  "json",
    ".md":    "markdown",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SourceFile:
    """Metadata record for a single source file discovered during a walk."""

    absolute_path: str
    relative_path: str      # relative to the repository root
    language: str           # canonical language name, e.g. "python"
    size_bytes: int
    extension: str

    def as_dict(self) -> dict:
        return {
            "absolute_path": self.absolute_path,
            "relative_path": self.relative_path,
            "language": self.language,
            "size_bytes": self.size_bytes,
            "extension": self.extension,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_gitignore_spec(root: Path) -> "pathspec.PathSpec | None":
    """Parse the top-level .gitignore and return a PathSpec, or None."""
    if not _PATHSPEC_AVAILABLE:
        return None
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return None
    lines = gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def _is_gitignored(
    spec: "pathspec.PathSpec | None",
    rel_path: str,
) -> bool:
    """Return True if *rel_path* is matched by the gitignore spec."""
    if spec is None:
        return False
    return spec.match_file(rel_path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def walk_repository(
    root: str | os.PathLike,
    languages: Optional[Set[str]] = None,
) -> List[SourceFile]:
    """Walk *root* recursively and return a list of :class:`SourceFile`.

    Parameters
    ----------
    root:
        Absolute or relative path to the repository root directory.
    languages:
        Optional set of language names to include (e.g. ``{"python"}``).
        If *None*, all detected languages are returned.

    Returns
    -------
    list[SourceFile]
        Sorted by ``relative_path`` for deterministic output.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Repository root is not a directory: {root}")

    spec = _load_gitignore_spec(root)
    results: List[SourceFile] = []

    for source_file in _walk(root, root, spec, languages):
        results.append(source_file)

    results.sort(key=lambda f: f.relative_path)
    return results


def _walk(
    root: Path,
    current: Path,
    spec: "pathspec.PathSpec | None",
    languages: Optional[Set[str]],
) -> Iterator[SourceFile]:
    """Recursive generator yielding :class:`SourceFile` objects."""
    try:
        entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
    except PermissionError:
        return

    for entry in entries:
        # ---- directory -------------------------------------------------------
        if entry.is_dir():
            if entry.name in HARD_IGNORE_DIRS:
                continue
            rel = entry.relative_to(root).as_posix() + "/"
            if _is_gitignored(spec, rel):
                continue
            yield from _walk(root, entry, spec, languages)

        # ---- file ------------------------------------------------------------
        elif entry.is_file():
            ext = entry.suffix.lower()
            language = EXTENSION_TO_LANGUAGE.get(ext)
            if language is None:
                continue                          # skip unknown types
            if languages is not None and language not in languages:
                continue                          # filtered out by caller

            rel = entry.relative_to(root).as_posix()
            if _is_gitignored(spec, rel):
                continue

            try:
                size = entry.stat().st_size
            except OSError:
                size = 0

            yield SourceFile(
                absolute_path=str(entry),
                relative_path=rel,
                language=language,
                size_bytes=size,
                extension=ext,
            )
