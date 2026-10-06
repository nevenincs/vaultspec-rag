"""Validation, clamping, root resolution, and structured-error helpers.

Split out of the original ``server.py`` monolith. The transport mode is read at call
time through the package alias; request route registry access is explicit.
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse

__all__ = [
    "_BAD_REQUEST_MISSING_ROOT",
    "ProjectRootRequiredError",
    "_clamp_top_k",
    "_default_root",
    "_is_sensitive_path",
    "_local_store_locked_error_dict",
    "_registry_full_error_dict",
    "_resolve_root",
    "_validate_query",
    "_validate_vault_root",
]

import vaultspec_rag.server as _m

from .._workspace_layout import (
    VAULT_DIR,
)
from ..capabilities import backend_capabilities_dict
from ._state import (
    _MAX_QUERY_LEN,
    _SENSITIVE_PATTERNS,
)

if TYPE_CHECKING:
    from .._store_locks import VaultStoreLockedError
    from ..service import RegistryFullError, ServiceRegistry

logger = logging.getLogger("vaultspec_rag.server")

_BAD_REQUEST_MISSING_ROOT = JSONResponse(
    {
        "ok": False,
        "error": "bad_request",
        "message": (
            "project_root is required - "
            "supply it in the request body (POST) or as a query parameter (GET)."
        ),
    },
    status_code=400,
)


class ProjectRootRequiredError(ValueError):
    """Raised when a route requires ``project_root`` but none was supplied.

    Distinct from plain :class:`ValueError` so route handlers can catch
    it precisely and return HTTP 400 rather than leaking a 500.
    """


def _registry_full_error_dict(
    exc: RegistryFullError, registry: ServiceRegistry
) -> dict[str, Any]:
    """Build the structured error dict for registry-full errors."""
    return {
        "ok": False,
        "error": "registry_full",
        "message": str(exc),
        "max_projects": registry.max_projects,
        "busy_projects": [str(p) for p in registry.busy_roots()],
    }


def _local_store_locked_error_dict(exc: VaultStoreLockedError) -> dict[str, Any]:
    """Build a structured error for local Qdrant file-lock contention.

    Renders what the exception proved rather than restating the old
    unconditional "another process" claim: the lock table can now confirm
    when the blocker is a store this same process already opened.
    """
    if exc.held_in_process:
        message = (
            "The local Qdrant index is already open by a store this process "
            "opened earlier. Reuse that store rather than opening a second "
            "one on the same root."
        )
    else:
        message = (
            "The local Qdrant index could not be locked, and no store this "
            "process opened holds it, so the holder is unidentified. Route "
            "concurrent searches through one resident vaultspec-rag "
            "service, or retry after the holder exits."
        )
    return {
        "ok": False,
        "error": "local_store_locked",
        "message": message,
        "db_path": exc.db_path,
        "backend_capabilities": backend_capabilities_dict(),
    }


def _validate_vault_root(root: Path) -> Path:
    """Ensure *root* contains a ``.vault/`` directory.

    Args:
        root: Resolved project root path.

    Returns:
        The validated path (unchanged).

    Raises:
        ValueError: If *root* has no ``.vault/`` subdirectory.
    """
    if not (root / VAULT_DIR).is_dir():
        msg = f"not a vaultspec project (no .vault/ directory): {root}"
        raise ValueError(msg)
    return root


def _default_root() -> Path:
    """Resolve the default project root from env or cwd.

    Only used in stdio mode.  HTTP mode must always provide an
    explicit ``project_root`` - see ``_resolve_root()``.

    Returns:
        Resolved ``Path`` from ``VAULTSPEC_RAG_ROOT`` env var, falling
        back to the current working directory.

    Raises:
        ProjectRootRequiredError: If called in HTTP mode (should never
            happen - ``_resolve_root`` guards this).
    """
    if _m._http_mode:
        msg = (
            "project_root is required in HTTP service mode - "
            "the multi-tenant service has no default project"
        )
        raise ProjectRootRequiredError(msg)
    from .._named_root import named_root

    return _validate_vault_root((named_root().path or Path.cwd()).resolve())


def _is_sensitive_path(rel_path: str) -> bool:
    """Check whether *rel_path* names a hidden location or a sensitive file.

    Uses forward-slash normalized paths for cross-platform consistency.
    Any dot-prefixed path component is sensitive by default, and the
    filename is checked against ``_SENSITIVE_PATTERNS`` without regard to
    case, so a case-insensitive filesystem cannot alias past a pattern.

    Args:
        rel_path: File path relative to the workspace root.

    Returns:
        True if the path is hidden or matches any sensitive pattern.
    """
    parts = rel_path.replace("\\", "/").split("/")
    # The relative-navigation components are not names; containment and
    # canonicalization own them.
    if any(part.startswith(".") and part not in (".", "..") for part in parts):
        return True
    filename = parts[-1].lower()
    return any(fnmatch.fnmatchcase(filename, pat) for pat in _SENSITIVE_PATTERNS)


def _clamp_top_k(top_k: int) -> int:
    """Clamp top_k to the range [1, 100].

    Args:
        top_k: Requested number of results.

    Returns:
        The clamped value, at least 1 and at most 100.
    """
    return max(1, min(top_k, 100))


def _validate_query(query: str) -> str:
    """Truncate query to _MAX_QUERY_LEN characters.

    Args:
        query: Raw user query string.

    Returns:
        The original query, or a truncated copy if it
        exceeded the maximum length.
    """
    if len(query) > _MAX_QUERY_LEN:
        logger.warning(
            "Query truncated from %d to %d characters",
            len(query),
            _MAX_QUERY_LEN,
        )
        return query[:_MAX_QUERY_LEN]
    return query


def _resolve_root(project_root: str | None) -> Path:
    """Resolve a project root path from an optional string.

    In HTTP service mode, ``project_root`` is required - the
    multi-tenant daemon has no default project.  In stdio mode,
    falls back to ``VAULTSPEC_RAG_ROOT`` env var or cwd.

    Args:
        project_root: Explicit project root path, or ``None``
            to use the default (stdio only).

    Returns:
        Resolved ``Path`` for the project root.

    Raises:
        ProjectRootRequiredError: If ``project_root`` is omitted in
            HTTP mode.
        ValueError: If the resolved path has no ``.vault/``
            subdirectory, or ``project_root`` is an empty/whitespace
            string.
    """
    if project_root is not None:
        if not project_root.strip():
            msg = "project_root must not be empty"
            raise ProjectRootRequiredError(msg)
        return _validate_vault_root(Path(project_root).resolve())
    return _default_root()
