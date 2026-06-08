"""Integration tests for watcher config wiring (#143/#144, plan P02).

Exercises the real ``_ensure_watcher`` path against the global service
registry and a real GPU-backed slot. No mocks: env vars are set on the
real ``os.environ``, resolved through the real ``VaultSpecConfigWrapper``,
and the watcher's own startup log is captured via pytest ``caplog`` to
confirm the config values actually reach ``watch_and_reindex``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import pytest

from ... import server
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


async def test_watch_disabled_starts_no_watcher(
    tmp_path: Path,
    _clean_watchers: None,
) -> None:
    root = _make_root(tmp_path)
    prev = _set_env(EnvVar.WATCH_ENABLED, "0")
    try:
        reset_config()
        server._ensure_watcher(root)
        assert root.resolve() not in server._watcher_tasks
    finally:
        _restore_env(EnvVar.WATCH_ENABLED, prev)


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
        (EnvVar.WATCH_ENABLED, _set_env(EnvVar.WATCH_ENABLED, "1")),
        (EnvVar.WATCH_DEBOUNCE_MS, _set_env(EnvVar.WATCH_DEBOUNCE_MS, "123")),
        (EnvVar.WATCH_COOLDOWN_S, _set_env(EnvVar.WATCH_COOLDOWN_S, "4")),
    ]
    try:
        reset_config()
        with caplog.at_level(logging.INFO, logger="vaultspec_rag.watcher"):
            server._ensure_watcher(root)
            # Yield so the freshly created task runs its startup log line.
            await asyncio.sleep(0.1)
        assert root.resolve() in server._watcher_tasks
        assert "debounce=123ms" in caplog.text
        assert "cooldown=4s" in caplog.text
    finally:
        for var, prev in saved:
            _restore_env(var, prev)
