"""
Ingestion layer — repository loading, file walking, and source parsing.

Public re-exports for convenience:
    from src.ingestion import walk_repository
    from src.ingestion import PythonParser
"""

from .walker import walk_repository
from .parsers.python_parser import PythonParser

__all__ = ["walk_repository", "PythonParser"]
