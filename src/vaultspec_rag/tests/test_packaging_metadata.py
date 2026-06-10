"""Packaging-metadata regression guard for #182.

`mcp` is a hard runtime dependency of the RAG server (the daemon imports it
unconditionally and the HTTP transport is ``mcp.streamable_http_app()``), so it
must be declared in the package's *core* dependencies — not only as an optional
extra, and not relying on ``vaultspec-core`` pulling it in transitively. This
reads the installed distribution metadata and asserts the declaration directly.
"""

from __future__ import annotations

import importlib.metadata

import pytest
from packaging.requirements import Requirement

pytestmark = [pytest.mark.unit]


def _requirements() -> list[Requirement]:
    raw = importlib.metadata.requires("vaultspec-rag") or []
    return [Requirement(r) for r in raw]


def _is_core(req: Requirement) -> bool:
    """A core dependency carries no ``extra == ...`` environment marker."""
    return req.marker is None or "extra" not in str(req.marker)


def test_mcp_is_a_core_dependency() -> None:
    """`mcp` is declared as a core runtime dependency, not just an extra (#182)."""
    core_names = {req.name for req in _requirements() if _is_core(req)}
    assert "mcp" in core_names, (
        "mcp must be declared as a core runtime dependency (#182); "
        f"core dependencies were: {sorted(core_names)}"
    )
