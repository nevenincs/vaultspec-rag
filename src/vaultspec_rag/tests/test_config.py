"""Unit tests for VaultSpecConfigWrapper RAG-specific keys."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from vaultspec_rag.config import EnvVar, get_config, reset_config


@pytest.fixture(autouse=True)
def _reset_config_around_each_test() -> Iterator[None]:
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
