"""Project-root resolution for the MCP adapter.

The daemon is a machine-global multi-root service with no meaningful working
directory of its own, so every request must name the root it addresses; a
server-side default would silently resolve one root's query against another
root's index. The stdio MCP server is the opposite case - its host launches one
per project, so the root is already known to this process. Resolving it here is
what makes ``project_root`` genuinely optional on the tool surface instead of
advertising an optionality no caller can reach.

Precedence is explicit argument, then ``VAULTSPEC_RAG_ROOT``, then the working
directory. The env var comes second because a host that sets it has named the
root as deliberately as a caller passing the argument, and this process is the
one it was set for. The working directory is resolved through the same workspace
resolver the CLI's ``--target`` uses, so one directory yields one root on both
adapters and neither drifts into addressing a different project than the other.

This is not the server's ``_default_root``. That one is the *route's* in-process
default for stdio mode, gated on transport mode and validating only ``.vault/``;
this one decides which root a client request addresses, and validates the full
workspace exactly as an operator's ``--target`` is validated.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["_resolve_project_root"]

#: Structured error prefix for an unresolvable root, matching the
#: ``code: message`` shape the rest of this package's tool errors carry.
_ROOT_UNRESOLVED = "project_root_unresolved"


def _requested_root(project_root: str | None) -> Path | None:
    """Return the explicitly named root, from the argument or the env var."""
    from .._named_root import env_named_root

    if project_root and project_root.strip():
        return Path(project_root.strip()).expanduser()
    return env_named_root()


def _resolve_project_root(project_root: str | None) -> str:
    """Return the absolute project root a tool call addresses.

    A named root - passed by the caller or set by the launching host in
    ``VAULTSPEC_RAG_ROOT`` - is resolved and validated exactly as the CLI
    validates ``--target``; absent both, this process's working directory is
    resolved. Either way the daemon receives an absolute root, never the empty
    string its routes reject.

    Args:
        project_root: Caller-supplied root, or ``None``/blank to fall through
            to the env var and then the working directory.

    Returns:
        The absolute project root as a string.

    Raises:
        RuntimeError: When no vaultspec workspace resolves, carrying the
            resolver's own account of what was missing plus the remediation.
    """
    from vaultspec_core.config.workspace import (  # pyright: ignore[reportMissingTypeStubs]
        WorkspaceError,
        resolve_workspace,
    )

    override = _requested_root(project_root)
    try:
        layout = resolve_workspace(target_override=override)
    except WorkspaceError as exc:
        named = str(override) if override is not None else "the working directory"
        raise RuntimeError(
            f"{_ROOT_UNRESOLVED}: no vaultspec project resolves from {named}: "
            f"{exc} Pass an explicit project_root, or enroll the project with "
            f"`vaultspec-rag install`."
        ) from None
    return str(layout.target_dir)
