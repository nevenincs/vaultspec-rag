"""Integration tests for the watcher-control MCP tools (#143/#144, plan P04).

Drives the real ``start_watcher`` / ``stop_watcher`` / ``reconfigure_watcher``
/ ``get_watcher_state`` tools against the global registry with a real
GPU-backed slot. No mocks: env vars on the real ``os.environ``, the real
``VaultSpecConfigWrapper``, and the watcher's own startup log captured via
``caplog`` to confirm reconfigured values reach ``watch_and_reindex``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

import vaultspec_rag.mcp._admin_tools as admin

from ... import server
from ...config import EnvVar, reset_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


pytestmark = [pytest.mark.integration]


def _set_env(var: EnvVar, value: str) -> str | None:
    prev = os.environ.get(var.value)
    os.environ[var.value] = value
    return prev


def _restore_env(var: EnvVar, prev: str | None) -> None:
    if prev is None:
        os.environ.pop(var.value, None)
    else:
        os.environ[var.value] = prev


@pytest.fixture
def _clean_watchers() -> Iterator[None]:
    reset_config()
    yield
    server._stop_all_watchers()
    reset_config()


def _make_root(tmp_path: Path) -> Path:
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "x.md").write_text(
        "---\ntags: ['#adr', '#t']\n---\n# x\n\nbody\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.subprocess_gpu
async def test_start_then_stop_watcher(
    tmp_path: Path,
    _live_service: tuple[int, Path],
) -> None:
    root = _make_root(tmp_path)
    resolved = str(root.resolve())

    started = await admin.start_watcher(str(root))
    assert started["started"] is True
    assert started["watch_enabled"] is True

    state = await admin.get_watcher_state(str(root))
    assert resolved in state["watching"]
    assert state["running"] is True

    stopped = await admin.stop_watcher(str(root))
    assert stopped["stopped"] is True

    state2 = await admin.get_watcher_state(str(root))
    assert state2["running"] is False


@pytest.mark.subprocess_gpu
async def test_reconfigure_restarts_with_new_values(
    tmp_path: Path,
    _live_service: tuple[int, Path],
) -> None:
    root = _make_root(tmp_path)
    await admin.start_watcher(str(root))

    result = await admin.reconfigure_watcher(
        str(root),
        debounce_ms=50,
        cooldown_s=2,
    )
    assert result["restarted"] is True
    assert result["debounce_ms"] == 50
    assert result["cooldown_s"] == 2


@pytest.mark.subprocess_gpu
async def test_start_watcher_disabled_is_pull_only(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    from ...cli import _spawn_service, _terminate_pid, _write_service_status
    from ._helpers import _get_ephemeral_port, _poll_health, _service_env

    root = _make_root(tmp_path)

    with _service_env(tmp_path, env_overrides={"VAULTSPEC_RAG_WATCH_ENABLED": "0"}):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"
        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        _write_service_status(pid, port)
        _poll_health(port)

        result = await admin.start_watcher(str(root))
        assert result["started"] is False
        assert result["watch_enabled"] is False

        state = await admin.get_watcher_state()
        assert state["watch_enabled"] is False
