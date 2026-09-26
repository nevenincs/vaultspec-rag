"""Where this package's credentials come from, and who may supply them.

Two of the registered names hold secrets a workspace may legitimately supply:
the hosted-classifier key and the Hugging Face token. Everything about how
they are found belongs to the framework - the process environment first, then
the workspace-root ``.env``, and that file only when the running interpreter
lives inside the workspace and this package is resolved there as a project
dependency. This module is only the list of which names are asked for and the
one place that asks, so a second call site cannot quietly widen the set.

**Only a command-line process may call this.** The resident daemon serves many
roots at once and holds no single workspace, so a file belonging to one of
them must never configure it. It is handed the values the command line
resolved, through the environment of the child it spawns, and reads no file of
its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from vaultspec_core.config import resolve_credential

from ._registry import entry
from ._types import EnvVar

if TYPE_CHECKING:
    from pathlib import Path

    from vaultspec_core.config import ConfigVariable, Credential

__all__ = ["DAEMON_CREDENTIALS", "credential_assignments", "workspace_credential"]

#: The credentials a spawned daemon needs in order to serve requests: the
#: hosted classifier it may be asked to call, and the token a gated model
#: repository requires. The Qdrant key is absent because it is not eligible
#: for a workspace ``.env`` at all, so the daemon's inherited environment is
#: already the whole of its resolution.
DAEMON_CREDENTIALS: Final = (EnvVar.TYPESAFE_API_KEY, EnvVar.HF_TOKEN)


def workspace_credential(
    var: EnvVar, root: Path, *, interpreter_prefix: Path | None = None
) -> Credential | None:
    """Resolve the credential *var* declares for the workspace at *root*.

    Args:
        var: A registered secret of this package.
        root: The resolved workspace root, whose ``.env`` may supply the key
            under the framework's gate.
        interpreter_prefix: Where the running interpreter lives, the half of
            the gate a process cannot change about itself. ``None`` reads the
            real one, which is what production always does.

    Returns:
        The key and where it came from, or ``None`` when no source has one.
    """
    return resolve_credential(entry(var), root, interpreter_prefix=interpreter_prefix)


def credential_assignments(
    root: Path | None, *, interpreter_prefix: Path | None = None
) -> tuple[tuple[ConfigVariable, str], ...]:
    """Return the credential assignments a child process should be given.

    A child spawned by a command-line process inherits that process's
    environment, which already carries any key the session exported. What it
    cannot inherit is a key that came from the workspace ``.env``, because the
    file is never read twice: the gate is about the process that opened it.
    Assigning the resolved values closes that gap without the child reading
    anything.

    Args:
        root: The resolved workspace root, or ``None`` when no workspace was
            resolved, in which case the process environment is the only
            source and inheritance already covers it.
        interpreter_prefix: Where the running interpreter lives; ``None``
            reads the real one.

    Returns:
        ``(variable, value)`` pairs for the framework's child-environment
        builder, empty when nothing is resolvable.
    """
    if root is None:
        return ()
    resolved: list[tuple[ConfigVariable, str]] = []
    for var in DAEMON_CREDENTIALS:
        credential = workspace_credential(
            var, root, interpreter_prefix=interpreter_prefix
        )
        if credential is not None:
            resolved.append((entry(var), credential.key))
    return tuple(resolved)
