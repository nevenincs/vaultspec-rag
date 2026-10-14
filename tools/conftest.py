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
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tools.monitor.pins import WHEEL_PINS_MEMBER, GeneratedPins, render
from vaultspec_rag.monitor_runtime._pins import PinProvenance

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Return the repository checkout the release instruments operate on."""
    return REPO_ROOT


@pytest.fixture
def pinned_wheel() -> Callable[..., Path]:
    """Return a factory for a wheel carrying one release's monitor digests.

    A bundle is checked against the wheel it carries, and a monitor archive
    is admitted by the same digests, so more than one instrument here needs a
    wheel that states them. The module is rendered by the generator the
    release pipeline uses, so a test cannot assert against a shape the
    pipeline would never write.
    """

    def build(
        directory: Path,
        version: str,
        executables: dict[str, str],
        archives: dict[str, str] | None = None,
        provenance: PinProvenance = PinProvenance.RELEASE,
    ) -> Path:
        pins = GeneratedPins(
            provenance=provenance,
            version=version,
            tag=f"vaultspec-rag-v{version}",
            archives=archives or dict.fromkeys(executables, "a" * 64),
            executables=executables,
        )
        directory.mkdir(parents=True, exist_ok=True)
        wheel = directory / f"vaultspec_rag-{version}-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(WHEEL_PINS_MEMBER, render(pins))
        return wheel

    return build


@pytest.fixture(scope="session")
def pyproject(repo_root: Path) -> dict[str, Any]:
    """Return the parsed ``pyproject.toml`` of this checkout."""
    return tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
