"""Tests for the Tier-1 consolidated service state surface (#142, plan P02).

Two layers, no mocks/skips/monkeypatch:

- Integration (GPU): call the real ``get_service_state`` MCP tool against the
  global registry with a real GPU-backed slot (reusing the session-scoped
  ``embedding_model`` fixture and the global-registry pattern from
  ``test_watcher_control.py``) and assert the consolidated shape.
- CLI: drive ``server info`` through the real Typer app against a dead
  ``--port`` so ``_try_mcp_admin`` genuinely fails to connect, asserting the
  exit-3 + JSON envelope contract.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

import vaultspec_rag.mcp._admin_tools as admin

from ... import server
from ...cli import app

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


runner = CliRunner()

# A port with nothing listening: _try_mcp_admin gets connection-refused
# and returns None -> the command reports service-not-running (exit 3).
_DEAD_PORT = "59233"


@pytest.fixture
def _clean_watchers(  # pyright: ignore[reportUnusedFunction]
) -> Iterator[None]:
    """Stop any watcher the consolidated read may have started as a side effect."""
    yield
    server._stop_all_watchers()


def _make_root(tmp_path: Path) -> Path:
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "x.md").write_text(
        "---\ntags: ['#adr', '#t']\n---\n# x\n\nbody\n",
        encoding="utf-8",
    )
    return tmp_path


# --------------------------------------------------------------------------- #
# Integration (GPU): the real tool returns the consolidated shape             #
# --------------------------------------------------------------------------- #


@pytest.mark.subprocess_gpu
async def test_get_service_state_consolidated_shape(
    tmp_path: Path,
    live_service: tuple[int, Path],  # noqa: ARG001
) -> None:
    root = _make_root(tmp_path)

    state = await admin.get_service_state(project_root=str(root))

    assert set(state) == {"index", "projects", "watcher"}

    index = state["index"]
    assert isinstance(index, dict)
    # get_index_status payload (model_dump of IndexStatus) - counts + GPU.
    assert "vault_count" in index
    assert "code_count" in index
    assert "vram_gb" in index
    assert index["target_dir"] == str(root)

    projects = state["projects"]
    assert isinstance(projects, dict)
    assert "projects" in projects
    assert "max_projects" in projects
    assert "idle_ttl_seconds" in projects
    assert isinstance(projects["projects"], list)

    watcher = state["watcher"]
    assert isinstance(watcher, dict)
    assert "watch_enabled" in watcher
    assert "debounce_ms" in watcher
    assert "cooldown_s" in watcher
    assert isinstance(watcher["watching"], list)


# --------------------------------------------------------------------------- #
# CLI: service-not-running -> exit 3 + JSON envelope                          #
# --------------------------------------------------------------------------- #


def test_info_not_running_json() -> None:
    result = runner.invoke(
        app,
        ["server", "info", "--port", _DEAD_PORT, "--json"],
    )
    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "service.info"
    assert payload["error"] == "service_not_running"


def test_info_not_running_prose() -> None:
    result = runner.invoke(app, ["server", "info", "--port", _DEAD_PORT])
    assert result.exit_code == 3
    assert "not running" in result.stdout.lower()


def test_info_subcommand_registered() -> None:
    result = runner.invoke(app, ["server", "info", "--help"])
    assert result.exit_code == 0


def test_info_cli_mcp_parity() -> None:
    # The consolidated read must exist as an MCP tool AND a CLI subcommand.
    assert callable(admin.get_service_state)
    help_result = runner.invoke(app, ["server", "--help"])
    assert help_result.exit_code == 0
    assert "info" in help_result.stdout
