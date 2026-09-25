"""
Symbol Index — central registry for every named symbol discovered during analysis.

A *symbol* is any named entity in the codebase: a module, class, method,
or function.  Every other analysis module (call graph, dep graph, path
tracer) references symbols by their **fully-qualified name** (FQN), which
is the dotted path from the module root to the symbol, e.g.::

    src.ingestion.walker.walk_repository
    src.ingestion.parsers.python_parser.PythonParser.parse

Building the index
------------------
Feed parsed file results (from :class:`~src.ingestion.parsers.base.BaseParser`)
into :meth:`SymbolIndex.add_from_parse_result` for each file, or use the
convenience function :func:`build_index` to process an entire repository in
one call::

    from src.analysis.symbol_index import build_index
    from src.ingestion import walk_repository
    from src.ingestion.parsers import PythonParser

    files  = walk_repository(".", languages={"python"})
    parser = PythonParser()
    index  = build_index(files, parser)

    sym = index.lookup("src.analysis.symbol_index.SymbolIndex")
    print(sym.kind, sym.line)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class SymbolKind(str, enum.Enum):
    """Coarse-grained classification of a symbol."""
    MODULE   = "module"
    CLASS    = "class"
    METHOD   = "method"
    FUNCTION = "function"


@dataclass
class Symbol:
    """A single named entity in the codebase.

    Attributes
    ----------
    fqn:
        Fully-qualified name, e.g. ``src.analysis.symbol_index.SymbolIndex``.
    name:
        Simple (unqualified) name, e.g. ``SymbolIndex``.
    kind:
        Coarse classification: module / class / method / function.
    module_fqn:
        FQN of the module that contains this symbol.
    file_path:
        Absolute path of the source file.
    line:
        1-based source line number where the symbol is defined.
    docstring:
        Extracted docstring, or *None* if absent.
    bases:
        For classes — list of base class name strings.
    args:
        For functions/methods — list of parameter name strings.
    annotations:
        For functions/methods — ``{param: annotation_str}`` dict.
    decorators:
        For functions/methods — list of decorator source strings.
    parent_fqn:
        FQN of the enclosing class (for methods), or *None*.
    """

    fqn:         str
    name:        str
    kind:        SymbolKind
    module_fqn:  str
    file_path:   str
    line:        int
    docstring:   Optional[str]        = None
    bases:       List[str]            = field(default_factory=list)
    args:        List[str]            = field(default_factory=list)
    annotations: Dict[str, str]       = field(default_factory=dict)
    decorators:  List[str]            = field(default_factory=list)
    parent_fqn:  Optional[str]        = None

    def as_dict(self) -> dict:
        return {
            "fqn":         self.fqn,
            "name":        self.name,
            "kind":        self.kind.value,
            "module_fqn":  self.module_fqn,
            "file_path":   self.file_path,
            "line":        self.line,
            "docstring":   self.docstring,
            "bases":       self.bases,
            "args":        self.args,
            "annotations": self.annotations,
            "decorators":  self.decorators,
            "parent_fqn":  self.parent_fqn,
        }


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

class SymbolIndex:
    """In-memory registry mapping FQNs → :class:`Symbol` objects.

    Thread safety: not thread-safe; build once, then treat as read-only.
    """

    def __init__(self) -> None:
        self._by_fqn:  Dict[str, Symbol]        = {}
        # name → list of symbols (multiple files can define the same name)
        self._by_name: Dict[str, List[Symbol]]  = {}
        # module_fqn → list of symbols defined in that module
        self._by_module: Dict[str, List[Symbol]] = {}

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def add_symbol(self, symbol: Symbol) -> None:
        """Register a single :class:`Symbol`."""
        self._by_fqn[symbol.fqn] = symbol

        self._by_name.setdefault(symbol.name, []).append(symbol)
        self._by_module.setdefault(symbol.module_fqn, []).append(symbol)

    def add_from_parse_result(self, result: dict) -> None:
        """Populate the index from one parser result dict.

        Parameters
        ----------
        result:
            Dict conforming to the schema in
            :mod:`src.ingestion.parsers.base`.
        """
        if result.get("error"):
            return  # skip unparseable files

        file_path  = result["file_path"]
        module_fqn = _file_path_to_module_fqn(file_path)

        # ---- module symbol -------------------------------------------
        module_name = module_fqn.split(".")[-1]
        self.add_symbol(Symbol(
            fqn        = module_fqn,
            name       = module_name,
            kind       = SymbolKind.MODULE,
            module_fqn = module_fqn,
            file_path  = file_path,
            line       = 1,
        ))

        # ---- top-level functions -------------------------------------
        for fn in result.get("functions", []):
            fqn = f"{module_fqn}.{fn['name']}"
            self.add_symbol(Symbol(
                fqn        = fqn,
                name       = fn["name"],
                kind       = SymbolKind.FUNCTION,
                module_fqn = module_fqn,
                file_path  = file_path,
                line       = fn["line"],
                docstring  = fn.get("docstring"),
                args       = fn.get("args", []),
                annotations= fn.get("annotations", {}),
                decorators = fn.get("decorators", []),
            ))

        # ---- classes + their methods ---------------------------------
        for cls in result.get("classes", []):
            cls_fqn = f"{module_fqn}.{cls['name']}"
            self.add_symbol(Symbol(
                fqn        = cls_fqn,
                name       = cls["name"],
                kind       = SymbolKind.CLASS,
                module_fqn = module_fqn,
                file_path  = file_path,
                line       = cls["line"],
                docstring  = cls.get("docstring"),
                bases      = cls.get("bases", []),
            ))

            for method in cls.get("methods", []):
                m_fqn = f"{cls_fqn}.{method['name']}"
                self.add_symbol(Symbol(
                    fqn        = m_fqn,
                    name       = method["name"],
                    kind       = SymbolKind.METHOD,
                    module_fqn = module_fqn,
                    file_path  = file_path,
                    line       = method["line"],
                    docstring  = method.get("docstring"),
                    args       = method.get("args", []),
                    annotations= method.get("annotations", {}),
                    decorators = method.get("decorators", []),
                    parent_fqn = cls_fqn,
                ))

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def lookup(self, fqn: str) -> Optional[Symbol]:
        """Return the symbol for *fqn*, or *None* if not found."""
        return self._by_fqn.get(fqn)

    def find_by_name(self, name: str) -> List[Symbol]:
        """Return all symbols whose simple name equals *name*."""
        return list(self._by_name.get(name, []))

    def symbols_in_module(self, module_fqn: str) -> List[Symbol]:
        """Return all symbols defined in *module_fqn*."""
        return list(self._by_module.get(module_fqn, []))

    def all_symbols(self) -> List[Symbol]:
        """Return every registered symbol."""
        return list(self._by_fqn.values())

    def all_modules(self) -> List[Symbol]:
        """Return only MODULE-kind symbols."""
        return [s for s in self._by_fqn.values() if s.kind == SymbolKind.MODULE]

    def __len__(self) -> int:
        return len(self._by_fqn)

    def __contains__(self, fqn: str) -> bool:
        return fqn in self._by_fqn

    def __repr__(self) -> str:
        return f"<SymbolIndex symbols={len(self)}>"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_path_to_module_fqn(file_path: str) -> str:
    """Derive a dotted module FQN from an absolute or relative file path.

    Strategy: walk up from the file until a directory without ``__init__.py``
    is found — that boundary is the package root.  If no package boundary is
    found, use the stem of the filename alone.

    Examples
    --------
    ``/project/src/analysis/symbol_index.py``  →  ``src.analysis.symbol_index``
    ``/project/standalone.py``                  →  ``standalone``
    """
    path = Path(file_path).resolve()
    parts: list[str] = [path.stem]  # start with filename stem

    current = path.parent
    while (current / "__init__.py").exists():
        parts.append(current.name)
        current = current.parent

    parts.reverse()
    return ".".join(parts)


# ---------------------------------------------------------------------------
# Convenience builder
# ---------------------------------------------------------------------------

def build_index(
    source_files: Iterable,
    parser,
) -> SymbolIndex:
    """Walk *source_files*, parse each one, and return a populated :class:`SymbolIndex`.

    Parameters
    ----------
    source_files:
        An iterable of :class:`~src.ingestion.walker.SourceFile` objects
        (or any object with an ``absolute_path`` attribute).
    parser:
        Any :class:`~src.ingestion.parsers.base.BaseParser` instance.

    Returns
    -------
    SymbolIndex
        Fully populated index ready for graph building.
    """
    index = SymbolIndex()
    for sf in source_files:
        result = parser.parse(sf.absolute_path)
        index.add_from_parse_result(result)
    return index
