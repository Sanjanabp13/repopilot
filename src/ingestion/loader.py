"""
Repository Loader.

Resolves a user-supplied *source* — either a local filesystem path or a
remote Git URL — into an absolute local directory path that the walker
and parsers can consume.

Behaviour
---------
- **Local path**: resolved to absolute, validated as a directory, returned immediately.
- **Remote URL** (``http://``, ``https://``, ``git://``, or ends with ``.git``):
  cloned with ``git clone --depth=1`` into a temporary directory.  The
  caller is responsible for cleanup (use :class:`RepoContext` as a context
  manager for automatic cleanup).

Usage::

    from src.ingestion.loader import load_repository, RepoContext

    # Auto-cleanup via context manager
    with RepoContext("https://github.com/org/repo") as repo_dir:
        files = walk_repository(repo_dir, languages={"python"})

    # Manual — caller owns cleanup
    ctx = load_repository("https://github.com/org/repo")
    try:
        files = walk_repository(ctx.path, languages={"python"})
    finally:
        ctx.cleanup()

    # Local path — cleanup() is a no-op
    ctx = load_repository("/path/to/local/project")
    files = walk_repository(ctx.path, languages={"python"})
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Prefixes that indicate a remote Git URL
_REMOTE_PREFIXES = ("http://", "https://", "git://", "git@", "ssh://")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RepoContext:
    """Holds the resolved local path for a repository.

    Parameters
    ----------
    path:
        Absolute local path to the repository root.
    _tmp_dir:
        The temporary directory created for a cloned repo, or *None* for
        local paths (where cleanup is a no-op).
    """

    path: str
    _tmp_dir: Optional[str] = field(default=None, repr=False)

    def cleanup(self) -> None:
        """Remove the cloned temporary directory, if any."""
        if self._tmp_dir and Path(self._tmp_dir).exists():
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            logger.debug("Removed temporary clone at %s", self._tmp_dir)
            self._tmp_dir = None

    # Context-manager protocol
    def __enter__(self) -> "RepoContext":
        return self

    def __exit__(self, *_) -> None:
        self.cleanup()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_repository(source: str, clone_timeout: int = 120) -> RepoContext:
    """Resolve *source* to a local repository directory.

    Parameters
    ----------
    source:
        A local filesystem path **or** a remote Git URL.
    clone_timeout:
        Maximum seconds to wait for ``git clone`` to complete (default 120).

    Returns
    -------
    RepoContext
        ``ctx.path`` is the absolute local path to the repository root.
        Call ``ctx.cleanup()`` (or use as a context manager) to remove
        any temporary clone directory when done.

    Raises
    ------
    NotADirectoryError
        If *source* is a local path that does not point to a directory.
    RuntimeError
        If ``git clone`` fails or ``git`` is not found on PATH.
    """
    if _is_remote(source):
        return _clone(source, clone_timeout)
    return _local(source)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_remote_url(source: str) -> str:
    """Normalize common GitHub/Git remote URL variants into a standard HTTPS clone URL."""
    value = source.strip().strip("\"'")
    if not value:
        raise ValueError("Repository URL is empty.")

    if value.startswith("git@"):
        # git@github.com:org/repo.git -> https://github.com/org/repo.git
        match = re.match(r"git@([^:]+):(.+)", value)
        if not match:
            raise ValueError(f"Malformed SSH Git URL: {source}")
        host, path = match.groups()
        value = f"https://{host}/{path.strip('/')}"
    elif value.startswith("ssh://"):
        match = re.match(r"ssh://(?:git@)?([^/]+)/(.+)", value)
        if not match:
            raise ValueError(f"Malformed SSH URL: {source}")
        host, path = match.groups()
        value = f"https://{host}/{path.strip('/')}"
    elif value.startswith("http://") or value.startswith("https://"):
        value = value.rstrip("/")
    elif value.endswith(".git"):
        value = value.rstrip("/")
    else:
        raise ValueError(
            "Repository URL must be a valid local path, HTTPS URL, SSH URL, or .git URL."
        )

    if "github.com" not in value and "gitlab.com" not in value and ".git" not in value:
        if "/" not in value:
            raise ValueError(f"Malformed repository URL: {source}")
        value = f"{value}.git"

    if not value.endswith(".git"):
        value = f"{value}.git"

    return value


def _is_remote(source: str) -> bool:
    s = source.strip()
    return any(s.startswith(p) for p in _REMOTE_PREFIXES) or s.endswith(".git")


def _local(source: str) -> RepoContext:
    path = Path(source).resolve()
    if not path.is_dir():
        raise NotADirectoryError(
            f"Local path is not a directory: {path}"
        )
    logger.debug("Using local repository at %s", path)
    return RepoContext(path=str(path))


def _clone(url: str, timeout: int) -> RepoContext:
    """Run ``git clone --depth=1 <url>`` into a fresh temp dir."""
    if shutil.which("git") is None:
        raise RuntimeError(
            "git is not available on PATH — cannot clone remote repository."
        )

    normalized_url = _normalize_remote_url(url)
    tmp = tempfile.mkdtemp(prefix="repopilot_clone_")
    logger.info("Cloning %s → %s", normalized_url, tmp)

    commands = [
        ["git", "clone", "--depth=1", "--", normalized_url, tmp],
    ]

    if "github.com" in normalized_url or "gitlab.com" in normalized_url:
        commands.append([
            "git",
            "-c",
            "http.sslVerify=false",
            "clone",
            "--depth=1",
            "--",
            normalized_url,
            tmp,
        ])

    last_error = None
    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError(
                f"git clone timed out after {timeout}s for URL: {normalized_url}"
            )
        except Exception as exc:
            last_error = exc
            continue

        if result.returncode == 0:
            logger.info("Clone complete: %s", tmp)
            return RepoContext(path=tmp, _tmp_dir=tmp)

        stderr = (result.stderr or "").strip()
        last_error = RuntimeError(
            f"git clone exited with code {result.returncode}: {stderr or 'unknown error'}"
        )
        if "SSL" in stderr or "certificate" in stderr.lower() or "verify" in stderr.lower():
            continue
        break

    shutil.rmtree(tmp, ignore_errors=True)
    if last_error is None:
        raise RuntimeError(f"git clone failed for URL: {normalized_url}")
    raise RuntimeError(f"git clone failed: {last_error}") from last_error
