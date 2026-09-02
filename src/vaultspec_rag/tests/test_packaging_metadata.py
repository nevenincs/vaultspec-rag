"""Installed-distribution metadata and canonical MCP payload guards.

The suite proves the optional MCP dependency boundary, console entry point, and
package-data launch contract from the distribution visible to the interpreter.
"""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys
from importlib.resources import files
from typing import TYPE_CHECKING
from zipfile import ZipFile

import pytest
from packaging.requirements import Requirement

pytestmark = [pytest.mark.unit]

if TYPE_CHECKING:
    from pathlib import Path


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


def test_inference_dependencies_are_only_in_the_gpu_extra() -> None:
    """Keep ordinary package installs free of the local inference stack."""
    core_names = {req.name for req in _requirements() if _is_core(req)}
    gpu_names = {req.name for req in _requirements() if _in_extra(req, "gpu")}
    inference_names = {"sentence-transformers", "torch", "transformers"}
    assert core_names.isdisjoint(inference_names), (
        "base metadata must not pull local inference dependencies; found "
        f"{sorted(core_names & inference_names)}"
    )
    assert inference_names <= gpu_names, (
        "the GPU extra must carry the complete local inference stack; found "
        f"{sorted(gpu_names)}"
    )


def test_published_base_wheel_has_no_linux_cuda_resolution(tmp_path: Path) -> None:
    """Inspect built metadata and resolve it without workspace-only sources.

    This catches a base torch requirement even when a checkout source mapping
    makes local development resolve a different wheel. It fails at the metadata
    assertion when a base torch requirement is reintroduced.
    """
    dist_dir = tmp_path / "dist"
    build = subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--no-sources",
            "--out-dir",
            str(dist_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr
    wheel = next(dist_dir.glob("vaultspec_rag-*.whl"))
    with ZipFile(wheel) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        requirements = [
            Requirement(line.removeprefix("Requires-Dist: "))
            for line in archive.read(metadata_name).decode().splitlines()
            if line.startswith("Requires-Dist: ")
        ]
    core_names = {req.name for req in requirements if _is_core(req)}
    assert core_names.isdisjoint({"sentence-transformers", "torch", "transformers"})

    resolution = subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--dry-run",
            "--python",
            sys.executable,
            "--python-platform",
            "x86_64-unknown-linux-gnu",
            "--target",
            str(tmp_path / "target"),
            str(wheel),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert resolution.returncode == 0, resolution.stderr
    resolver_output = resolution.stdout + resolution.stderr
    assert "nvidia-" not in resolver_output.lower()


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
        "_vaultspec_mode_tool_spec": "vaultspec-rag[gpu,mcp]",
    }


def test_published_core_floor_carries_native_mcp_contract() -> None:
    """The distribution cannot resolve against a pre-native-MCP Core release."""
    core = next(req for req in _requirements() if req.name == "vaultspec-core")
    assert str(core.specifier) == ">=0.1.45"
