"""Packaging-metadata guard for the `mcp-optional-dependency` ADR.

`mcp` is an opt-in extra, not a core dependency: the CLI and the HTTP search
daemon never import it (only the optional stdio MCP server does), so a base
install must not declare it - on Windows that would force `pywin32` and break a
plain `pip install vaultspec-rag`. This reads the installed distribution metadata
and asserts `mcp` is absent from core and present in the `[mcp]` extra. Supersedes
the #182 "mcp is core" guard.
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


def _in_extra(req: Requirement, extra: str) -> bool:
    """Whether *req* is contributed by the named optional-dependency *extra*."""
    return req.marker is not None and req.marker.evaluate({"extra": extra})


def test_mcp_is_not_a_core_dependency() -> None:
    """`mcp` must NOT be a core dependency (the CLI/daemon path never imports it)."""
    core_names = {req.name for req in _requirements() if _is_core(req)}
    assert "mcp" not in core_names, (
        "mcp must be an optional extra, not core, so a base install does not "
        f"drag mcp/pywin32 onto the CLI path; core dependencies were: "
        f"{sorted(core_names)}"
    )


def test_mcp_is_declared_in_the_mcp_extra() -> None:
    """`mcp` is available via the `[mcp]` extra for the optional MCP server."""
    extra_mcp = {req.name for req in _requirements() if _in_extra(req, "mcp")}
    assert "mcp" in extra_mcp, (
        "mcp must be declared in the [mcp] extra so `vaultspec-rag[mcp]` installs "
        f"the MCP server's dependency; the [mcp] extra contained: "
        f"{sorted(extra_mcp)}"
    )
