"""Real install and uninstall acceptance across native MCP host targets.

The suite uses real temporary workspaces, Core provider enrollment, RAG's bundled
sources, and the installed Claude Code and Codex CLIs. It proves dry-run byte safety,
provider-local drift reporting and repair, exact repeat-install stability, selective
unenrollment, user and Core sibling preservation, and host recognition without mocks,
fakes, stubs, patches, or skipped behavior.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tomllib
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from vaultspec_core.core.manifest import (
    write_manifest,
)

from ...builtins import list_builtins
from ...commands._install import install_run

if TYPE_CHECKING:
    from ...commands._models import InstallReport

pytestmark = [pytest.mark.integration]


_RAG_RULE_REL = Path(".vaultspec") / "rules" / "vaultspec-rag.builtin.md"
_RAG_MCP_REL = Path(".vaultspec") / "mcps" / "vaultspec-rag.builtin.json"
_RAG_SKILL_REL = Path(".vaultspec") / "skills" / "vaultspec-rag-discovery" / "SKILL.md"
_RAG_NON_MCP_BUILTIN_REL = Path(".vaultspec") / next(
    relative for relative in list_builtins() if not relative.startswith("mcps/")
)
_REQUIRED_MCP_RELATIVES = (
    Path(".mcp.json"),
    Path(".codex") / "config.toml",
    Path(".vaultspec") / "mcp-ownership.json",
    Path(".vaultspec") / "providers.json",
    Path(".vaultspec") / "workspace.json",
    _RAG_MCP_REL,
)

_CONSUMER_PYPROJECT = (
    "[project]\n"
    'name = "demo-consumer"\n'
    'version = "0.1.0"\n'
    'dependencies = ["vaultspec-rag"]\n'
)


def read_mcp_json(target: Path) -> dict[str, Any]:
    return json.loads((target / ".mcp.json").read_text(encoding="utf-8"))


def read_codex_mcp(target: Path) -> dict[str, Any]:
    raw = tomllib.loads((target / ".codex" / "config.toml").read_text(encoding="utf-8"))
    return raw["mcp_servers"]


def workspace_file_bytes(target: Path) -> dict[str, bytes]:
    """Capture every real workspace file for byte-inert preview assertions."""
    return {
        path.relative_to(target).as_posix(): path.read_bytes()
        for path in target.rglob("*")
        if path.is_file()
    }


def workspace_inventory(target: Path) -> dict[str, tuple[str, bytes]]:
    return {
        path.relative_to(target).as_posix(): (
            ("file", path.read_bytes()) if path.is_file() else ("directory", b"")
        )
        for path in target.rglob("*")
    }


def _node_signature(path: Path) -> tuple[str, str | int, bool]:
    if path.is_junction():
        return ("junction", os.readlink(path), True)
    if path.is_symlink():
        metadata = path.lstat()
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        is_directory = path.is_dir() or bool(
            attributes & getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0)
        )
        return ("symlink", os.readlink(path), is_directory)
    return ("node", stat.S_IFMT(path.lstat().st_mode), path.is_dir())


def required_mcp_transaction_inventory(
    target: Path,
) -> dict[str, tuple[tuple[str, str | int, bool] | None, bytes | None]]:
    required = (
        *(target / relative for relative in _REQUIRED_MCP_RELATIVES),
        target / "pyproject.toml",
    )
    paths = (
        *required,
        *(path.with_suffix(path.suffix + ".lock") for path in required),
    )
    return {
        path.relative_to(target).as_posix(): (
            _node_signature(path) if path.exists() or path.is_symlink() else None,
            path.read_bytes() if path.is_file() else None,
        )
        for path in paths
    }


def create_windows_junction(path: Path, target: Path) -> None:
    environment = {
        **os.environ,
        "VAULTSPEC_TEST_JUNCTION_PATH": str(path),
        "VAULTSPEC_TEST_JUNCTION_TARGET": str(target),
    }
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "New-Item -ItemType Junction -Path $env:VAULTSPEC_TEST_JUNCTION_PATH "
        "-Target $env:VAULTSPEC_TEST_JUNCTION_TARGET | Out-Null"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )


def _install(target: Path, **overrides: Any) -> InstallReport:
    """Run a network-free dual-provider install with MCP intent enabled."""
    options: dict[str, Any] = {
        "install_mcp": True,
        "configure_torch": False,
        "provision": False,
    }
    options.update(overrides)
    return install_run(path=target, **options)


def seed_core_mcp_source(target: Path) -> None:
    source = files("vaultspec_core.builtins") / "mcps" / "vaultspec-core.builtin.json"
    destination = target / ".vaultspec" / "mcps" / "vaultspec-core.builtin.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    write_manifest(target, {"claude", "codex"})


@pytest.fixture()
def fresh_workspace(tmp_path: Path) -> Path:
    """An empty directory rag will bootstrap from scratch."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def installed_workspace(tmp_path: Path) -> Path:
    """An empty directory with rag freshly installed (post-sync)."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    _install(ws)
    return ws
