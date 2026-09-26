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
workspace and would otherwise silently get another.

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

import os
from pathlib import Path
from typing import TYPE_CHECKING

from vaultspec_core.config import VAULTSPEC_TARGET_DIR, resolve_target

from .config._registry import entry
from .config._types import EnvVar

if TYPE_CHECKING:
    from collections.abc import Mapping

    from vaultspec_core.config import ResolvedTarget

__all__ = ["named_root"]

#: The two names carrying a root, scoped first and framework second.
_ROOT_NAMES = (EnvVar.RAG_ROOT.value, VAULTSPEC_TARGET_DIR.env_name)


def _home_expanded(environ: Mapping[str, str]) -> Mapping[str, str]:
    """Return *environ* with home shorthand expanded in the root names.

    ``~`` reaches a variable from a configuration file or a launcher, never
    from a shell, which expands it before the value is ever exported. Nothing
    downstream would: a leading tilde is not an absolute path, so it would be
    taken against the working directory and then refused as a directory that
    does not exist. Expanding it here keeps a launcher-written root working
    while the order, the chain and the refusal all stay the framework's.
    """
    expanded = {
        name: str(Path(raw.strip()).expanduser())
        for name in _ROOT_NAMES
        if (raw := environ.get(name, "")).strip().startswith("~")
    }
    return {**environ, **expanded} if expanded else environ


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
            exist.
    """
    return resolve_target(
        explicit,
        package_root=entry(EnvVar.RAG_ROOT),
        environ=_home_expanded(os.environ),
    )
