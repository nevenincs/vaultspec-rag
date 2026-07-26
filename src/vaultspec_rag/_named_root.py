"""The project root named through the environment.

Every entry point lets its caller name the root outright - the CLI's
``--target``, the MCP tool's ``project_root`` argument. ``VAULTSPEC_RAG_ROOT``
is that same statement made by the process that launched this one, and it
outranks the working directory for exactly that reason: whoever exported it
chose a project as deliberately as an operator typing the flag, while the
working directory is only where the process happened to start.

Reading it lives here because three entry points honour it - the CLI's root
callback, the MCP adapter's root resolution, and the stdio server route's
in-process default. A second reader spelling the rule slightly differently is
how one directory starts resolving to two different projects.

The resident HTTP daemon is the one process that must not honour it. It serves
every root at once and each request names its own, so the variable is stripped
from the daemon's environment when it is spawned rather than read here.
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import EnvVar

__all__ = ["env_named_root"]


def env_named_root() -> Path | None:
    """Return the root named in the environment, or ``None`` if none is.

    Returns:
        The user-expanded path held in ``VAULTSPEC_RAG_ROOT``, or ``None``
        when the variable is unset or holds only whitespace. A blank value
        counts as absent, so an exported-but-empty variable resolves the way
        an unset one does instead of naming the process's own directory.
    """
    raw = os.environ.get(EnvVar.RAG_ROOT)
    if raw is None or not raw.strip():
        return None
    return Path(raw.strip()).expanduser()
