"""
Ingestion layer — repository loading, file walking, and source parsing.

Public re-exports for convenience::

    from src.ingestion import load_repository, RepoContext
    from src.ingestion import walk_repository
    from src.ingestion import PythonParser
"""

from .loader import load_repository, RepoContext
from .walker import walk_repository
from .parsers.python_parser import PythonParser

__all__ = ["load_repository", "RepoContext", "walk_repository", "PythonParser"]
