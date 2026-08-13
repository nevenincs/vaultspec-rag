"""Tests for the consolidated service-state backend surface (#142).

Two layers, no mocks/skips/monkeypatch:

- Integration (GPU): call the real ``get_service_state`` MCP tool against the
  global registry with a real GPU-backed slot (reusing the session-scoped
  ``embedding_model`` fixture and the global-registry pattern from
  ``test_watcher_control.py``) and assert the consolidated shape.
- CLI: assert the backend-only service-state read is not exposed as a second
  human-facing status command. Operators use ``server status``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

import vaultspec_rag.mcp._admin_client as admin

from ... import server, store_schema
from ...cli import app
from ._helpers import _make_root

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


runner = CliRunner()

# A port with nothing listening: _try_http_admin gets connection-refused
# and returns None -> the command reports service-not-running (exit 3).
_DEAD_PORT = "59233"


@pytest.fixture
def _clean_watchers(  # pyright: ignore[reportUnusedFunction]
) -> Iterator[None]:
    """Stop any watcher the consolidated read may have started as a side effect."""
    yield
    server._stop_all_watchers()


def _assert_managed_qdrant_state(qdrant: object) -> None:
    """Assert the state reports the real fixture-owned Qdrant server."""
    assert isinstance(qdrant, dict)
    state = cast("dict[str, object]", qdrant)
    assert state["mode"] == "server"
    assert state["alive"] is True
    assert isinstance(state["pid"], int)
    assert isinstance(state["port"], int)


def _assert_index_state(index: object, root: Path) -> None:
    """Assert the consolidated index section retains its complete shape."""
    assert isinstance(index, dict)
    state = cast("dict[str, object]", index)
    assert "vault_count" in state
    assert "code_count" in state
    assert "vram_gb" in state
    assert state["target_dir"] == str(root)


def _assert_projects_state(projects: object) -> None:
    """Assert project registry metadata remains bounded and typed."""
    assert isinstance(projects, dict)
    state = cast("dict[str, object]", projects)
    assert "projects" in state
    assert "max_projects" in state
    assert "idle_ttl_seconds" in state
    assert isinstance(state["projects"], list)


def _assert_watcher_state(watcher: object) -> None:
    """Assert watcher observability retains its complete shape."""
    assert isinstance(watcher, dict)
    state = cast("dict[str, object]", watcher)
    assert "watch_enabled" in state
    assert "debounce_ms" in state
    assert "cooldown_s" in state
    assert isinstance(state["watching"], list)


def _assert_quiesce_state(quiesce: object) -> None:
    """Assert the consolidated state carries the live quiesce observation.

    An idle service is running and admitting, and the flags a borrower reads
    before touching the card have to be present and boolean: a missing
    ``safe_to_borrow_gpu`` reads as falsy and would silently deny every
    borrow, which is the failure this shape exists to make visible.
    """
    assert isinstance(quiesce, dict)
    state = cast("dict[str, object]", quiesce)
    assert state["state"] == "running"
    assert state["admissions_open"] is True
    assert isinstance(state["safe_to_borrow_gpu"], bool)
    assert isinstance(state["admission_epoch"], int)


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

    assert set(state) == {
        "index",
        "projects",
        "qdrant",
        "schema_version",
        "watcher",
        "quiesce",
    }
    assert state["schema_version"] == store_schema.STORAGE_SCHEMA_VERSION
    _assert_managed_qdrant_state(state["qdrant"])
    _assert_index_state(state["index"], root)
    _assert_projects_state(state["projects"])
    _assert_watcher_state(state["watcher"])
    _assert_quiesce_state(state["quiesce"])


@pytest.mark.unit
def test_info_subcommand_not_registered() -> None:
    result = runner.invoke(app, ["server", "info", "--help"])
    assert result.exit_code != 0
    assert "No such command" in result.output


@pytest.mark.unit
def test_service_state_backend_remains_available_without_cli_alias() -> None:
    assert callable(admin.get_service_state)
    help_result = runner.invoke(app, ["server", "--help"])
    assert help_result.exit_code == 0
    assert "info" not in help_result.stdout.lower()
    assert "health" not in help_result.stdout.lower()
    assert "status" in help_result.stdout


@pytest.mark.unit
def test_health_subcommand_not_registered() -> None:
    result = runner.invoke(app, ["server", "health", "--help"])
    assert result.exit_code != 0
    assert "No such command" in result.output
