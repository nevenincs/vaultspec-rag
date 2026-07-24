"""Scaffolding for the world a test runs in: the project tree and the env.

Two things tests keep needing and kept re-writing: a directory that the CLI
will accept as a workspace, and a way to set one environment knob and put it
back. Both live here so the definition of "a workspace" is in one place, and so
a restore is never half-written.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from ..config import EnvVar


def make_workspace(root: Path) -> Path:
    """Create the marker directories that make *root* a vaultspec workspace.

    The CLI decides whether a directory is a project by looking for these two,
    so a test that wants its commands to route normally has to create both.
    Returns *root* for use inline.
    """
    (root / ".vault").mkdir()
    (root / ".vaultspec").mkdir()
    return root


def set_env(var: EnvVar, value: str) -> str | None:
    """Set one environment knob, returning the previous value for restoring.

    ``None`` means the variable was unset, which :func:`restore_env` reverses by
    removing it rather than writing an empty string - the two are different
    inputs to config resolution.
    """
    prev = os.environ.get(var.value)
    os.environ[var.value] = value
    return prev


def restore_env(var: EnvVar, prev: str | None) -> None:
    """Put one environment knob back to the value :func:`set_env` returned."""
    if prev is None:
        os.environ.pop(var.value, None)
    else:
        os.environ[var.value] = prev
