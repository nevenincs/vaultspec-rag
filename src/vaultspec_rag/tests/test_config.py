"""Unit tests for VaultSpecConfigWrapper RAG-specific keys."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from ..config import EnvVar, get_config, reset_config


@pytest.fixture(autouse=True)
def _reset_config_around_each_test(  # pyright: ignore[reportUnusedFunction]
) -> Iterator[None]:
    reset_config()
    yield
    reset_config()


def _set_env(var: EnvVar, value: str) -> str | None:
    prev = os.environ.get(var.value)
    os.environ[var.value] = value
    return prev


def _restore_env(var: EnvVar, prev: str | None) -> None:
    if prev is None:
        os.environ.pop(var.value, None)
    else:
        os.environ[var.value] = prev


def test_service_idle_ttl_default() -> None:
    cfg = get_config()
    assert cfg.service_idle_ttl_seconds == 1800


def test_service_max_projects_default() -> None:
    cfg = get_config()
    assert cfg.service_max_projects == 16


def test_service_log_max_bytes_default() -> None:
    cfg = get_config()
    assert cfg.service_log_max_bytes == 10485760


def test_service_log_backup_count_default() -> None:
    cfg = get_config()
    assert cfg.service_log_backup_count == 5


def test_service_idle_ttl_env_override() -> None:
    prev = _set_env(EnvVar.SERVICE_IDLE_TTL_SECONDS, "60")
    try:
        reset_config()
        cfg = get_config()
        value = cfg.service_idle_ttl_seconds
        assert value == 60
        assert isinstance(value, int)
    finally:
        _restore_env(EnvVar.SERVICE_IDLE_TTL_SECONDS, prev)
        reset_config()


def test_service_max_projects_env_override() -> None:
    prev = _set_env(EnvVar.SERVICE_MAX_PROJECTS, "4")
    try:
        reset_config()
        cfg = get_config()
        value = cfg.service_max_projects
        assert value == 4
        assert isinstance(value, int)
    finally:
        _restore_env(EnvVar.SERVICE_MAX_PROJECTS, prev)
        reset_config()


def test_service_log_max_bytes_env_override() -> None:
    prev = _set_env(EnvVar.SERVICE_LOG_MAX_BYTES, "4096")
    try:
        reset_config()
        cfg = get_config()
        value = cfg.service_log_max_bytes
        assert value == 4096
        assert isinstance(value, int)
    finally:
        _restore_env(EnvVar.SERVICE_LOG_MAX_BYTES, prev)
        reset_config()


def test_service_log_backup_count_env_override() -> None:
    prev = _set_env(EnvVar.SERVICE_LOG_BACKUP_COUNT, "2")
    try:
        reset_config()
        cfg = get_config()
        value = cfg.service_log_backup_count
        assert value == 2
        assert isinstance(value, int)
    finally:
        _restore_env(EnvVar.SERVICE_LOG_BACKUP_COUNT, prev)
        reset_config()


def test_watch_enabled_default() -> None:
    cfg = get_config()
    value = cfg.watch_enabled
    assert value is True
    assert isinstance(value, bool)


def test_watch_debounce_ms_default() -> None:
    cfg = get_config()
    value = cfg.watch_debounce_ms
    assert value == 2000
    assert isinstance(value, int)


def test_watch_cooldown_s_default() -> None:
    cfg = get_config()
    value = cfg.watch_cooldown_s
    assert value == 30.0
    assert isinstance(value, float)


def test_watch_debounce_ms_env_override() -> None:
    prev = _set_env(EnvVar.WATCH_DEBOUNCE_MS, "500")
    try:
        reset_config()
        cfg = get_config()
        value = cfg.watch_debounce_ms
        assert value == 500
        assert isinstance(value, int)
    finally:
        _restore_env(EnvVar.WATCH_DEBOUNCE_MS, prev)
        reset_config()


def test_watch_debounce_ms_env_zero_means_no_delay() -> None:
    # 0 is a valid tuning value (no debounce), NOT a disable sentinel.
    prev = _set_env(EnvVar.WATCH_DEBOUNCE_MS, "0")
    try:
        reset_config()
        cfg = get_config()
        assert cfg.watch_debounce_ms == 0
        # The watcher stays enabled; only watch_enabled disables it.
        assert cfg.watch_enabled is True
    finally:
        _restore_env(EnvVar.WATCH_DEBOUNCE_MS, prev)
        reset_config()


def test_watch_cooldown_s_env_override() -> None:
    prev = _set_env(EnvVar.WATCH_COOLDOWN_S, "1.5")
    try:
        reset_config()
        cfg = get_config()
        value = cfg.watch_cooldown_s
        assert value == 1.5
        assert isinstance(value, float)
    finally:
        _restore_env(EnvVar.WATCH_COOLDOWN_S, prev)
        reset_config()


@pytest.mark.parametrize("raw", ["0", "false", "False", "no", "off", ""])
def test_watch_enabled_env_falsey(raw: str) -> None:
    prev = _set_env(EnvVar.WATCH_ENABLED, raw)
    try:
        reset_config()
        cfg = get_config()
        value = cfg.watch_enabled
        assert value is False
        assert isinstance(value, bool)
    finally:
        _restore_env(EnvVar.WATCH_ENABLED, prev)
        reset_config()


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "Yes"])
def test_watch_enabled_env_truthy(raw: str) -> None:
    prev = _set_env(EnvVar.WATCH_ENABLED, raw)
    try:
        reset_config()
        cfg = get_config()
        value = cfg.watch_enabled
        assert value is True
        assert isinstance(value, bool)
    finally:
        _restore_env(EnvVar.WATCH_ENABLED, prev)
        reset_config()


def _clear_server_mode_env() -> dict[EnvVar, str | None]:
    """Snapshot and clear the two effective-server-mode env knobs.

    The test host may carry an ambient ``VAULTSPEC_RAG_QDRANT_SERVER``
    or ``VAULTSPEC_RAG_LOCAL_ONLY`` (the lifespan publishes server-mode
    state into the environment for the daemon's lifetime), so the
    default-resolution assertions must run from a known-clean slate.
    """
    saved: dict[EnvVar, str | None] = {}
    for var in (EnvVar.QDRANT_SERVER, EnvVar.LOCAL_ONLY):
        saved[var] = os.environ.pop(var.value, None)
    return saved


def _restore_server_mode_env(saved: dict[EnvVar, str | None]) -> None:
    for var, prev in saved.items():
        _restore_env(var, prev)


def test_qdrant_server_default_is_true() -> None:
    saved = _clear_server_mode_env()
    try:
        reset_config()
        cfg = get_config()
        value = cfg.qdrant_server
        assert value is True
        assert isinstance(value, bool)
    finally:
        _restore_server_mode_env(saved)
        reset_config()


def test_local_only_default_is_false() -> None:
    saved = _clear_server_mode_env()
    try:
        reset_config()
        cfg = get_config()
        value = cfg.local_only
        assert value is False
        assert isinstance(value, bool)
    finally:
        _restore_server_mode_env(saved)
        reset_config()


def test_effective_server_mode_default_is_true() -> None:
    saved = _clear_server_mode_env()
    try:
        reset_config()
        cfg = get_config()
        assert cfg.effective_server_mode() is True
    finally:
        _restore_server_mode_env(saved)
        reset_config()


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes"])
def test_local_only_env_flips_effective_mode_off(raw: str) -> None:
    saved = _clear_server_mode_env()
    os.environ[EnvVar.LOCAL_ONLY.value] = raw
    try:
        reset_config()
        cfg = get_config()
        # local-only deterministically wins over the server default:
        # qdrant_server stays its default-true while effective mode is
        # forced off.
        assert cfg.qdrant_server is True
        assert cfg.local_only is True
        assert cfg.effective_server_mode() is False
    finally:
        _restore_server_mode_env(saved)
        reset_config()


@pytest.mark.parametrize("raw", ["0", "false", "no", ""])
def test_local_only_env_falsey_keeps_server_mode(raw: str) -> None:
    saved = _clear_server_mode_env()
    os.environ[EnvVar.LOCAL_ONLY.value] = raw
    try:
        reset_config()
        cfg = get_config()
        assert cfg.local_only is False
        assert cfg.effective_server_mode() is True
    finally:
        _restore_server_mode_env(saved)
        reset_config()


def test_qdrant_server_env_off_disables_effective_mode() -> None:
    saved = _clear_server_mode_env()
    os.environ[EnvVar.QDRANT_SERVER.value] = "0"
    try:
        reset_config()
        cfg = get_config()
        # The redundant server-mode env knob set off also disables
        # effective mode, independently of local_only.
        assert cfg.qdrant_server is False
        assert cfg.local_only is False
        assert cfg.effective_server_mode() is False
    finally:
        _restore_server_mode_env(saved)
        reset_config()


def test_local_only_wins_even_when_server_env_on() -> None:
    saved = _clear_server_mode_env()
    os.environ[EnvVar.QDRANT_SERVER.value] = "1"
    os.environ[EnvVar.LOCAL_ONLY.value] = "1"
    try:
        reset_config()
        cfg = get_config()
        assert cfg.qdrant_server is True
        assert cfg.local_only is True
        assert cfg.effective_server_mode() is False
    finally:
        _restore_server_mode_env(saved)
        reset_config()
