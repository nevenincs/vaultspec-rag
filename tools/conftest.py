"""Fixtures shared by every test package under ``tools``.

The instruments in this tree - the release binary builder and the Scoop and
Homebrew generators - assert against the checkout they operate on rather than
against a temporary fixture directory, because what they guard IS this
repository's release configuration. Resolving that checkout once here keeps
each cohabiting ``tests`` package from re-deriving it by counting directory
hops, which is the derivation a move silently breaks.

Mirrors ``dev/conftest.py`` in vaultspec-core, which owns the same tooling
under that repository's own layout.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Return the repository checkout the release instruments operate on."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def pyproject(repo_root: Path) -> dict[str, Any]:
    """Return the parsed ``pyproject.toml`` of this checkout."""
    return tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
