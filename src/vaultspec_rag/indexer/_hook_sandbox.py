"""Direct launch helpers for project-supplied preprocess hooks.

A root's ``.vaultragpreprocess.toml`` is repo-authored code: running it is the
same act of trust as building that repo, so hooks run directly with the
operator's privileges: there is no sandbox. What remains here is
the cheap, load-bearing hygiene: the child gets a curated, secret-free
environment (no daemon tokens, no ``VAULTSPEC_RAG_*`` knobs). The caller runs
the hook with the project root as its cwd - project-launcher commands
(``uv run``, ``npm exec``, ``make``) resolve their project from the cwd, so any
other directory silently breaks them. The subprocess boundary itself is a
CPU/CUDA-correctness requirement, not a security measure.

The module is stdlib-only so it stays importable from the CPU-only spawn chunk
worker without loading torch.
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

__all__ = [
    "curated_child_env",
    "default_popen_handle",
]

#: The child gets a minimal, secret-free environment built from an ALLOW-list:
#: only the names below are forwarded, so no credential, token, or
#: ``VAULTSPEC_RAG_*`` knob can reach a hook child regardless of what the
#: daemon's environment holds. The names carry paths and locale data a child
#: interpreter legitimately needs to start; everything else is dropped.
#: Matched case-insensitively.
_ENV_ALLOW_NAMES: frozenset[str] = frozenset(
    name.upper()
    for name in {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "SYSTEMDRIVE",
        "COMSPEC",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "TEMP",
        "TMP",
        "PATHEXT",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "LANG",
        "LC_ALL",
        "TZ",
    }
)


def curated_child_env() -> dict[str, str]:
    """Return a minimal, secret-free environment for a hook child.

    Drops every credential-bearing and ``VAULTSPEC_RAG_*`` variable (so the
    child cannot read the daemon's tokens or be redirected at managed state)
    and keeps only the small allow-list a child interpreter needs to start.
    """
    curated: dict[str, str] = {}
    for name, value in os.environ.items():
        upper = name.upper()
        if upper in _ENV_ALLOW_NAMES:
            curated[name] = value
    return curated


def default_popen_handle(
    argv: Sequence[str],
    *,
    cwd: pathlib.Path,
    env: dict[str, str],
) -> subprocess.Popen[bytes]:
    """Launch a hook child with the curated env and the caller-supplied cwd.

    Pipes are captured; the caller drains them on threads and enforces the
    wall-clock timeout.
    """
    return subprocess.Popen(
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),
        env=env,
    )
