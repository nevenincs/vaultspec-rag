"""Integration tests for watcher config wiring (#143/#144).

Exercises the real ``_ensure_watcher`` path against the global service
registry and a real GPU-backed slot. No mocks: env vars are set on the
real ``os.environ``, resolved through the real ``VaultSpecConfigWrapper``,
and the watcher's own startup log is captured via pytest ``caplog`` to
confirm the config values actually reach ``watch_and_reindex``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

from ... import server
from ...config import EnvVar, get_config, reset_config
from ...server import WatcherStartOutcome

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ...embeddings import EmbeddingModel

from .._scaffold import restore_env, set_env
from ._helpers import _make_root

pytestmark = [pytest.mark.integration]


@pytest.fixture
def _clean_watchers(  # pyright: ignore[reportUnusedFunction]
) -> Iterator[None]:
    reset_config()
    yield
    server._stop_all_watchers()
    reset_config()


async def test_watch_disabled_starts_no_watcher(
    tmp_path: Path,
    _clean_watchers: None,
) -> None:
    root = _make_root(tmp_path)
    prev = set_env(EnvVar.WATCH_ENABLED, "0")
    try:
        reset_config()
        server._ensure_watcher(root)
        assert root.resolve() not in server._watcher_tasks
    finally:
        restore_env(EnvVar.WATCH_ENABLED, prev)


async def test_watch_enabled_propagates_debounce_and_cooldown(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
    caplog: pytest.LogCaptureFixture,
    _clean_watchers: None,
) -> None:
    root = _make_root(tmp_path)
    # Share the session model with the global registry so peek_project
    # can build a slot without reloading GPU weights.
    server._registry._model = embedding_model
    saved = [
        (EnvVar.WATCH_ENABLED, set_env(EnvVar.WATCH_ENABLED, "1")),
        (EnvVar.WATCH_DEBOUNCE_MS, set_env(EnvVar.WATCH_DEBOUNCE_MS, "123")),
        (EnvVar.WATCH_COOLDOWN_S, set_env(EnvVar.WATCH_COOLDOWN_S, "4")),
    ]
    try:
        reset_config()
        with caplog.at_level(logging.INFO, logger="vaultspec_rag.watcher"):
            server._ensure_watcher(root)
            # Yield so the freshly created task runs its startup log line.
            await asyncio.sleep(0.1)
        assert root.resolve() in server._watcher_tasks
        assert "service.watcher event=started" in caplog.text
        assert "debounce_ms=123" in caplog.text
        assert "cooldown_seconds=4" in caplog.text
    finally:
        for var, prev in saved:
            restore_env(var, prev)


async def test_failed_watcher_task_is_removed_from_running_registry(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
    caplog: pytest.LogCaptureFixture,
    _clean_watchers: None,
) -> None:
    root = _make_root(tmp_path)
    server._registry._model = embedding_model
    previous = set_env(EnvVar.WATCH_ENABLED, "1")
    try:
        reset_config()
        corrupt = root / get_config().data_dir / "watcher-retry" / "vault.json"
        corrupt.parent.mkdir(parents=True, exist_ok=True)
        corrupt.write_text("{not-json", encoding="utf-8")

        with caplog.at_level(logging.INFO, logger="vaultspec_rag.server"):
            assert server._ensure_watcher(root) is WatcherStartOutcome.STARTED
            for _ in range(20):
                await asyncio.sleep(0.05)
                if root.resolve() not in server._watcher_tasks:
                    break

        assert root.resolve() not in server._watcher_tasks
        assert root.resolve() not in server._watcher_stops
        assert "service.watcher event=task_exited" in caplog.text
    finally:
        restore_env(EnvVar.WATCH_ENABLED, previous)
