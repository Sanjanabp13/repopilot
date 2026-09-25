---
name: add-language-parser
description: >-
  Use when extending RepoPilot to support a new programming language parser.
  Walks through the BaseParser interface contract, the SymbolIndex schema,
  and a step-by-step implementation checklist for a conforming parser
  (e.g. js_parser.py, java_parser.py). Activate before writing any new
  language parser file.
---

# Add a Language Parser to RepoPilot

This skill guides you through adding a new language parser that integrates
correctly with the ingestion pipeline, symbol index, call graph, and impact
analyzer — without modifying any existing code.

---

## Step 1 — Understand the Contract

Read `src/ingestion/parsers/base.py` first. Every parser:

1. Inherits from `BaseParser` (ABC).
2. Sets a class-level `language: str` attribute (canonical name, e.g. `"javascript"`).
3. Implements exactly one abstract method: `parse(file_path: str) -> dict`.
4. **Never raises** — all errors go into `result["error"]`, all list fields remain present.
5. Uses `self._empty_result(file_path, self.language, error=...)` for error returns.

---

## Step 2 — Know the Required Output Schema

`parse()` must return a dict matching this exact schema (from `base.py` docstring):

```python
{
    "file_path":  str,
    "language":   str,
    "error":      str | None,
    "imports": [
        {
            "kind":   "import" | "from",
            "module": str,
            "names":  list[str],
            "alias":  str | None,
            "line":   int,       # 1-based source line — REQUIRED
        }
    ],
    "classes": [
        {
            "name":       str,
            "bases":      list[str],
            "docstring":  str | None,
            "line":       int,    # 1-based source line — REQUIRED
            "methods": [
                {
                    "name":        str,
                    "args":        list[str],
                    "annotations": dict[str, str],
                    "docstring":   str | None,
                    "line":        int,
                    "decorators":  list[str],
                }
            ]
        }
    ],
    "functions": [
        {
            "name":        str,
            "args":        list[str],
            "annotations": dict[str, str],
            "docstring":   str | None,
            "line":        int,
            "decorators":  list[str],
        }
    ]
}
```

**Critical:** Line numbers must be 1-based integers. The symbol index stores them directly. The RAG citation system surfaces `file_path:line` to end users — wrong line numbers break citations.

---

## Step 3 — Choose a Parsing Strategy

| Language | Recommended approach |
|---|---|
| JavaScript / TypeScript | `tree-sitter-javascript` via `py-tree-sitter` |
| Java | `javalang` (pure Python AST) or tree-sitter |
| Go, Rust, C/C++ | `tree-sitter-<lang>` via `py-tree-sitter` |
| Generic / unknown | `src/ingestion/parsers/generic_parser.py` regex fallback |

For tree-sitter parsers, the general pattern is:
1. Install: `pip install tree-sitter tree-sitter-<language>`
2. Load language grammar
3. Walk the parse tree with a visitor; map node types to schema fields
4. Extract `start_point[0] + 1` for 1-based line numbers (tree-sitter uses 0-based rows)

---

## Step 4 — Implementation Checklist

Use `apply_diff` or `write_file` to create `src/ingestion/parsers/<lang>_parser.py`.

- [ ] File imports `BaseParser` from `.base`
- [ ] Class named `<Lang>Parser` (e.g. `JavaScriptParser`)
- [ ] `language: str = "<canonical_name>"` class attribute set (must match `walker.py`'s `EXTENSION_TO_LANGUAGE` value)
- [ ] `parse(self, file_path: str) -> dict` implemented
- [ ] Method opens the file with `encoding="utf-8", errors="replace"`
- [ ] `OSError` caught, returns `_empty_result(..., error="IOError: ...")`
- [ ] Parse / syntax errors caught, returns `_empty_result(..., error="SyntaxError ...")`
- [ ] All four top-level keys present in return dict: `imports`, `classes`, `functions`, `error`
- [ ] All line numbers are 1-based integers (not 0-based, not None)
- [ ] `annotations` dict is always present (may be empty `{}`) on functions and methods
- [ ] `decorators` list is always present (may be empty `[]`) on functions and methods
- [ ] `bases` list is always present (may be empty `[]`) on classes

---

## Step 5 — Register the Extension

In `src/ingestion/walker.py`, add the file extension(s) to `EXTENSION_TO_LANGUAGE`:

```python
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    # ... existing entries ...
    ".js":   "javascript",   # already present
    ".ts":   "typescript",   # already present — add new ones below
    ".java": "java",
}
```

The canonical name must match the parser's `language` attribute exactly.

---

## Step 6 — Register the Parser

In `src/ingestion/parsers/__init__.py`, add the import and `__all__` entry:

```python
from .js_parser import JavaScriptParser   # example
__all__ = [..., "JavaScriptParser"]
```

---

## Step 7 — Write a Conformance Test

Add a test in `tests/` that:
1. Creates a small `<lang>` source file as a string fixture (inline, no external file).
2. Calls `parser.parse(tmp_path / "fixture.<ext>")`.
3. Asserts: `result["error"] is None`.
4. Asserts all expected symbols, line numbers, docstrings, and import records are present.
5. Asserts a deliberately broken file returns `result["error"] != None` and all lists are `[]`.

Look at `tests/test_impact.py` for the project's test style (pytest, session-scoped fixtures, class-based grouping).

---

## Step 8 — Verify End-to-End Integration

Run the analysis smoke-test against a real repo containing the new language:

```bash
python3 -m src.analysis /path/to/repo-with-js 2>&1
```

Confirm:
- Symbol count increases to include JS/TS symbols.
- No parse errors in Step 1 output.
- Call graph edges resolve cross-language (function → imported JS function) if applicable.

---

## Reference: Python parser as canonical example

`src/ingestion/parsers/python_parser.py` is the gold-standard reference implementation. It covers:
- Import extraction with aliases and line numbers
- Class extraction with bases, docstrings, line numbers
- Method extraction with positional/keyword/vararg args, return annotations, decorators
- Graceful error handling (SyntaxError, OSError)

Read it before writing any new parser.
