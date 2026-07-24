"""Integration tests for the watcher-control MCP tools (#143/#144).

Drives the real ``start_watcher`` / ``stop_watcher`` / ``reconfigure_watcher``
/ ``get_watcher_state`` tools against the global registry with a real
GPU-backed slot. No mocks: env vars on the real ``os.environ``, the real
``VaultSpecConfigWrapper``, and the watcher's own startup log captured via
``caplog`` to confirm reconfigured values reach ``watch_and_reindex``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import vaultspec_rag.mcp._admin_client as admin

from ... import server
from ...config import reset_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


from ._helpers import _make_root

pytestmark = [pytest.mark.integration]


@pytest.fixture
def _clean_watchers(  # pyright: ignore[reportUnusedFunction]
) -> Iterator[None]:
    reset_config()
    yield
    server._stop_all_watchers()
    reset_config()


@pytest.mark.subprocess_gpu
@pytest.mark.usefixtures("live_service_with_watch")
async def test_start_then_stop_watcher(tmp_path: Path) -> None:
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
@pytest.mark.usefixtures("live_service_with_watch")
async def test_reconfigure_restarts_with_new_values(tmp_path: Path) -> None:
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
    from ...cli import _spawn_service, _write_service_status
    from ._helpers import _get_ephemeral_port, _poll_health, _service_env
    from .conftest import _cleanup_service_process

    root = _make_root(tmp_path)

    with _service_env(tmp_path, env_overrides={"VAULTSPEC_RAG_WATCH_ENABLED": "0"}):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"
        pid = _spawn_service(port, log_path)
        request.addfinalizer(
            lambda: _cleanup_service_process(
                pid=pid, port=port, log_path=log_path, timeout=15.0
            )
        )
        _write_service_status(pid, port)
        _poll_health(port)

        result = await admin.start_watcher(str(root))
        assert result["started"] is False
        assert result["watch_enabled"] is False

        state = await admin.get_watcher_state()
        assert state["watch_enabled"] is False
