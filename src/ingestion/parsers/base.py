"""
Abstract base class for all language parsers.

Every concrete parser must implement :meth:`BaseParser.parse` and return a
dictionary that conforms to the schema documented below.

Expected return schema
----------------------
::

    {
        "file_path":  str,          # absolute path that was parsed
        "language":   str,          # canonical language name
        "error":      str | None,   # set on parse failure, rest may be empty
        "imports": [
            {
                "kind":   "import" | "from",   # import x  vs  from x import y
                "module": str,                 # top-level module name
                "names":  list[str],           # imported names (empty for bare import)
                "alias":  str | None,          # alias from `as` clause
                "line":   int,                 # 1-based source line
            },
            ...
        ],
        "classes": [
            {
                "name":       str,
                "bases":      list[str],       # parent class names
                "docstring":  str | None,
                "line":       int,
                "methods": [
                    {
                        "name":        str,
                        "args":        list[str],          # parameter names
                        "annotations": dict[str, str],     # name → annotation source
                        "docstring":   str | None,
                        "line":        int,
                        "decorators":  list[str],
                    },
                    ...
                ],
            },
            ...
        ],
        "functions": [
            {
                "name":        str,
                "args":        list[str],
                "annotations": dict[str, str],
                "docstring":   str | None,
                "line":        int,
                "decorators":  list[str],
            },
            ...
        ],
    }
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseParser(ABC):
    """Abstract base parser.  Subclass and implement :meth:`parse`."""

    # Subclasses set this to their canonical language name (e.g. "python").
    language: str = "unknown"

    @abstractmethod
    def parse(self, file_path: str) -> dict:
        """Parse *file_path* and return a structured summary dictionary.

        Parameters
        ----------
        file_path:
            Absolute (or relative) path to the source file to parse.

        Returns
        -------
        dict
            A dictionary conforming to the schema described in the module
            docstring.  On unrecoverable error the ``"error"`` key is set
            to an error message string; all other list fields are still
            present but empty so callers never need to guard against
            missing keys.
        """

    # ------------------------------------------------------------------
    # Helpers available to all subclasses
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_result(file_path: str, language: str, error: str | None = None) -> dict:
        """Return a well-formed but empty result dict."""
        return {
            "file_path": file_path,
            "language":  language,
            "error":     error,
            "imports":   [],
            "classes":   [],
            "functions": [],
        }
