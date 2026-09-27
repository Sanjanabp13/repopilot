"""
In-memory session store for analysis state.

Keyed by analysis_id (UUID string). Each entry holds:
  - index, call_graph, dep_graph, rag_chain, parse_results
"""

from __future__ import annotations

import uuid
from typing import Dict, Any

_SESSIONS: Dict[str, Dict[str, Any]] = {}


def new_session() -> str:
    sid = str(uuid.uuid4())
    _SESSIONS[sid] = {}
    return sid


def get(analysis_id: str) -> Dict[str, Any]:
    return _SESSIONS.get(analysis_id, {})


def set_session(analysis_id: str, data: Dict[str, Any]) -> None:
    _SESSIONS[analysis_id] = data


def exists(analysis_id: str) -> bool:
    return analysis_id in _SESSIONS
