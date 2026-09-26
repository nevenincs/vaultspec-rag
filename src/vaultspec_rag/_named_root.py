"""The project root named by the invocation or the session environment.

Every entry point lets its caller name the root outright - the CLI's
``--target``, the MCP tool's ``project_root`` argument. The environment is
that same statement made by the process that launched this one, and it
outranks the working directory for exactly that reason: whoever exported it
chose a project as deliberately as an operator typing the flag, while the
working directory is only where the process happened to start.

Two names carry it, in order: ``VAULTSPEC_RAG_ROOT`` first, and the
framework-wide ``VAULTSPEC_TARGET_DIR`` behind it. The chain is what lets a
session name one workspace for every vaultspec tool at once while still
letting an operator point this one somewhere else. Neither is discovered from
the filesystem, and a name that points at a directory which is not there is
refused rather than quietly discovered past - the operator asked for one
workspace and would otherwise silently get another. Home shorthand (``~``,
``~user``) in either name is expanded by core's own resolver, against the
running process's own home directory, with the failure to determine one
raised naming the variable.

The resolution itself belongs to the framework, so the order is one order
across every package rather than this package's reading of it. What lives
here is which entry to resolve against, because three entry points honour it -
the CLI's root callback, the MCP adapter's root resolution, and the stdio
server route's in-process default - and a second caller spelling the rule
slightly differently is how one directory starts resolving to two projects.

The resident daemon is the one process that must not honour any of it. It
serves every root at once and each request names its own, so both names are
stripped from its environment when it is spawned rather than read here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vaultspec_core.config import resolve_target

from .config._registry import entry
from .config._types import EnvVar

if TYPE_CHECKING:
    from pathlib import Path

    from vaultspec_core.config import ResolvedTarget

__all__ = ["named_root"]


def named_root(explicit: Path | None = None) -> ResolvedTarget:
    """Return the root the invocation or the environment names, and from where.

    Args:
        explicit: The root the invocation named - a flag or a tool argument -
            or ``None`` when it named none.

    Returns:
        The resolved root paired with the rung that supplied it. A ``path`` of
        ``None`` means no rung named one, which is not a failure: it means the
        caller discovers a root from the working directory. ``variable`` names
        whichever of the two names actually carried the value, so a diagnostic
        can name the one the operator set.

    Raises:
        ConfigurationError: If a name points at a directory that does not
            exist, or at a home-relative path this process cannot expand.
    """
    return resolve_target(explicit, package_root=entry(EnvVar.RAG_ROOT))
