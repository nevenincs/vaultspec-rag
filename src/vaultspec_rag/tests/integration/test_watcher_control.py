"""Integration tests for the watcher-control MCP tools (#143/#144, plan P04).

Drives the real ``start_watcher`` / ``stop_watcher`` / ``reconfigure_watcher``
/ ``get_watcher_state`` tools against the global registry with a real
GPU-backed slot. No mocks: env vars on the real ``os.environ``, the real
``VaultSpecConfigWrapper``, and the watcher's own startup log captured via
``caplog`` to confirm reconfigured values reach ``watch_and_reindex``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import pytest

from ... import mcp_server
from ...config import EnvVar, reset_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ...embeddings import EmbeddingModel

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
    mcp_server._stop_all_watchers()
    reset_config()


def _make_root(tmp_path: Path) -> Path:
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "x.md").write_text(
        "---\ntags: ['#adr', '#t']\n---\n# x\n\nbody\n",
        encoding="utf-8",
    )
    return tmp_path


async def test_start_then_stop_watcher(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
    _clean_watchers: None,
) -> None:
    root = _make_root(tmp_path)
    mcp_server._registry._model = embedding_model
    resolved = str(root.resolve())

    started = await mcp_server.start_watcher(str(root))
    assert started["started"] is True
    assert started["watch_enabled"] is True
    assert root.resolve() in mcp_server._watcher_tasks

    state = await mcp_server.get_watcher_state(str(root))
    assert resolved in state["watching"]
    assert state["running"] is True

    stopped = await mcp_server.stop_watcher(str(root))
    assert stopped["stopped"] is True
    assert root.resolve() not in mcp_server._watcher_tasks

    state2 = await mcp_server.get_watcher_state(str(root))
    assert state2["running"] is False


async def test_reconfigure_restarts_with_new_values(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
    caplog: pytest.LogCaptureFixture,
    _clean_watchers: None,
) -> None:
    root = _make_root(tmp_path)
    mcp_server._registry._model = embedding_model
    await mcp_server.start_watcher(str(root))

    with caplog.at_level(logging.INFO, logger="vaultspec_rag.watcher"):
        result = await mcp_server.reconfigure_watcher(
            str(root),
            debounce_ms=50,
            cooldown_s=2,
        )
        await asyncio.sleep(0.1)

    assert result["restarted"] is True
    assert result["debounce_ms"] == 50
    assert result["cooldown_s"] == 2
    assert root.resolve() in mcp_server._watcher_tasks
    assert "debounce=50ms" in caplog.text
    assert "cooldown=2s" in caplog.text


async def test_start_watcher_disabled_is_pull_only(
    tmp_path: Path,
    _clean_watchers: None,
) -> None:
    root = _make_root(tmp_path)
    prev = _set_env(EnvVar.WATCH_ENABLED, "0")
    try:
        reset_config()
        result = await mcp_server.start_watcher(str(root))
        assert result["started"] is False
        assert result["watch_enabled"] is False
        assert root.resolve() not in mcp_server._watcher_tasks

        state = await mcp_server.get_watcher_state()
        assert state["watch_enabled"] is False
    finally:
        _restore_env(EnvVar.WATCH_ENABLED, prev)
