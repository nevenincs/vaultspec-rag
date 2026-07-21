"""Installed-distribution metadata and canonical MCP payload guards.

The suite proves the optional MCP dependency boundary, console entry point, and
package-data launch contract from the distribution visible to the interpreter.
"""

from __future__ import annotations

import importlib.metadata
import json
from importlib.resources import files

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


def test_mcp_console_entry_point_targets_server_main() -> None:
    """The installed console metadata exposes the supported stdio server."""
    entry_points = {
        entry.name: entry.value
        for entry in importlib.metadata.entry_points(group="console_scripts")
    }
    assert entry_points["vaultspec-search-mcp"] == "vaultspec_rag.server:main"


def test_canonical_mcp_builtin_is_installed() -> None:
    """The installed payload launches the MCP-capable package extra via uvx."""
    source = files("vaultspec_rag.builtins") / "mcps" / "vaultspec-rag.builtin.json"
    assert json.loads(source.read_text(encoding="utf-8")) == {
        "command": "@@VAULTSPEC_INSTALL_MODE_COMMAND@@",
        "args": ["@@VAULTSPEC_INSTALL_MODE_ARGS@@"],
        "_vaultspec_mode_package": "vaultspec-rag",
        "_vaultspec_mode_module": "vaultspec_rag.server",
        "_vaultspec_mode_tool_spec": "vaultspec-rag[mcp]",
    }


def test_published_core_floor_carries_native_mcp_contract() -> None:
    """The distribution cannot resolve against a pre-native-MCP Core release."""
    core = next(req for req in _requirements() if req.name == "vaultspec-core")
    assert str(core.specifier) == ">=0.1.45"
