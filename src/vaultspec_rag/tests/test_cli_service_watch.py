"""Unit tests for service-start watcher flag -> env translation (plan P03).

The daemon inherits config only via the environment, so ``service start``
flags are translated into ``VAULTSPEC_RAG_WATCH*`` by ``_service_child_env``.
These tests exercise that pure function against the real ``os.environ`` -
no subprocess, no mocks.
"""

from __future__ import annotations

import os

from ..cli import _service_child_env
from ..config import EnvVar


def _set_env(var: EnvVar, value: str) -> str | None:
    prev = os.environ.get(var.value)
    os.environ[var.value] = value
    return prev


def _restore_env(var: EnvVar, prev: str | None) -> None:
    if prev is None:
        os.environ.pop(var.value, None)
    else:
        os.environ[var.value] = prev


def test_unset_flags_add_no_watch_env() -> None:
    env = _service_child_env()
    assert EnvVar.WATCH_ENABLED.value not in env
    assert EnvVar.WATCH_DEBOUNCE_MS.value not in env
    assert EnvVar.WATCH_COOLDOWN_S.value not in env


def test_watch_true_sets_enabled_one() -> None:
    env = _service_child_env(watch=True)
    assert env[EnvVar.WATCH_ENABLED.value] == "1"


def test_watch_false_sets_enabled_zero() -> None:
    env = _service_child_env(watch=False)
    assert env[EnvVar.WATCH_ENABLED.value] == "0"


def test_debounce_and_cooldown_translate_to_strings() -> None:
    env = _service_child_env(watch_debounce_ms=500, watch_cooldown_s=1.5)
    assert env[EnvVar.WATCH_DEBOUNCE_MS.value] == "500"
    assert env[EnvVar.WATCH_COOLDOWN_S.value] == "1.5"


def test_unset_watch_flag_preserves_operator_env() -> None:
    # An operator who exported VAULTSPEC_RAG_WATCH_ENABLED=0 must keep it
    # when no --watch/--no-watch flag is given.
    prev = _set_env(EnvVar.WATCH_ENABLED, "0")
    try:
        env = _service_child_env(watch=None)
        assert env[EnvVar.WATCH_ENABLED.value] == "0"
    finally:
        _restore_env(EnvVar.WATCH_ENABLED, prev)


def test_set_watch_flag_overrides_operator_env() -> None:
    prev = _set_env(EnvVar.WATCH_ENABLED, "0")
    try:
        env = _service_child_env(watch=True)
        assert env[EnvVar.WATCH_ENABLED.value] == "1"
    finally:
        _restore_env(EnvVar.WATCH_ENABLED, prev)


def test_rag_root_is_stripped_from_child_env() -> None:
    prev = _set_env(EnvVar.RAG_ROOT, "/some/project")
    try:
        env = _service_child_env()
        assert EnvVar.RAG_ROOT.value not in env
    finally:
        _restore_env(EnvVar.RAG_ROOT, prev)


def test_unset_local_only_adds_no_local_only_env() -> None:
    env = _service_child_env()
    assert EnvVar.LOCAL_ONLY.value not in env


def test_local_only_true_sets_enabled_one() -> None:
    env = _service_child_env(local_only=True)
    assert env[EnvVar.LOCAL_ONLY.value] == "1"


def test_local_only_false_sets_enabled_zero() -> None:
    env = _service_child_env(local_only=False)
    assert env[EnvVar.LOCAL_ONLY.value] == "0"


def test_unset_local_only_flag_preserves_operator_env() -> None:
    # An operator who exported VAULTSPEC_RAG_LOCAL_ONLY=1 must keep it
    # when no --local-only flag selects a value (None).
    prev = _set_env(EnvVar.LOCAL_ONLY, "1")
    try:
        env = _service_child_env(local_only=None)
        assert env[EnvVar.LOCAL_ONLY.value] == "1"
    finally:
        _restore_env(EnvVar.LOCAL_ONLY, prev)


def test_set_local_only_flag_overrides_operator_env() -> None:
    prev = _set_env(EnvVar.LOCAL_ONLY, "1")
    try:
        env = _service_child_env(local_only=False)
        assert env[EnvVar.LOCAL_ONLY.value] == "0"
    finally:
        _restore_env(EnvVar.LOCAL_ONLY, prev)
