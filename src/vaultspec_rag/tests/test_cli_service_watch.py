"""Unit tests for service-start watcher flag -> env translation.

The daemon inherits config only via the environment, so ``service start``
flags are translated into ``VAULTSPEC_RAG_WATCH*`` by
``_build_service_child_env`` - the same call the daemon spawn makes with the
request it assembled from the flags. These tests exercise that pure function
against the real ``os.environ`` - no subprocess, no mocks.
"""

from __future__ import annotations

import pytest

from ..cli._process import _build_service_child_env, _ServiceChildEnvRequest
from ..cli._service_start import _decide_backend
from ..config._types import EnvVar
from ._scaffold import restore_env, set_env

pytestmark = [pytest.mark.unit]


def test_unset_flags_add_no_watch_env() -> None:
    env = _build_service_child_env(_ServiceChildEnvRequest())
    assert EnvVar.WATCH_ENABLED.value not in env
    assert EnvVar.WATCH_DEBOUNCE_MS.value not in env
    assert EnvVar.WATCH_COOLDOWN_S.value not in env


def test_watch_true_sets_enabled_one() -> None:
    env = _build_service_child_env(_ServiceChildEnvRequest(watch=True))
    assert env[EnvVar.WATCH_ENABLED.value] == "1"


def test_watch_false_sets_enabled_zero() -> None:
    env = _build_service_child_env(_ServiceChildEnvRequest(watch=False))
    assert env[EnvVar.WATCH_ENABLED.value] == "0"


def test_debounce_and_cooldown_translate_to_strings() -> None:
    env = _build_service_child_env(
        _ServiceChildEnvRequest(watch_debounce_ms=500, watch_cooldown_s=1.5)
    )
    assert env[EnvVar.WATCH_DEBOUNCE_MS.value] == "500"
    assert env[EnvVar.WATCH_COOLDOWN_S.value] == "1.5"


def test_unset_watch_flag_preserves_operator_env() -> None:
    # An operator who exported VAULTSPEC_RAG_WATCH_ENABLED=0 must keep it
    # when no --watch/--no-watch flag is given.
    prev = set_env(EnvVar.WATCH_ENABLED, "0")
    try:
        env = _build_service_child_env(_ServiceChildEnvRequest(watch=None))
        assert env[EnvVar.WATCH_ENABLED.value] == "0"
    finally:
        restore_env(EnvVar.WATCH_ENABLED, prev)


def test_set_watch_flag_overrides_operator_env() -> None:
    prev = set_env(EnvVar.WATCH_ENABLED, "0")
    try:
        env = _build_service_child_env(_ServiceChildEnvRequest(watch=True))
        assert env[EnvVar.WATCH_ENABLED.value] == "1"
    finally:
        restore_env(EnvVar.WATCH_ENABLED, prev)


def test_rag_root_is_stripped_from_child_env() -> None:
    prev = set_env(EnvVar.RAG_ROOT, "/some/project")
    try:
        env = _build_service_child_env(_ServiceChildEnvRequest())
        assert EnvVar.RAG_ROOT.value not in env
    finally:
        restore_env(EnvVar.RAG_ROOT, prev)


def test_unset_local_only_adds_no_local_only_env() -> None:
    env = _build_service_child_env(_ServiceChildEnvRequest())
    assert EnvVar.LOCAL_ONLY.value not in env


def test_local_only_true_sets_enabled_one() -> None:
    env = _build_service_child_env(_ServiceChildEnvRequest(local_only=True))
    assert env[EnvVar.LOCAL_ONLY.value] == "1"


def test_local_only_false_sets_enabled_zero() -> None:
    env = _build_service_child_env(_ServiceChildEnvRequest(local_only=False))
    assert env[EnvVar.LOCAL_ONLY.value] == "0"


def _env_for_start(*, local_only: bool, qdrant: bool | None) -> dict[str, str]:
    """The daemon environment a start with these backend flags builds.

    The request comes from the start command's own decision, so what is held
    is the value the command passes and not one a test chose for it.
    """
    backend = _decide_backend(local_only=local_only, qdrant=qdrant)
    return _build_service_child_env(
        _ServiceChildEnvRequest(local_only=backend.local_only, qdrant=backend.qdrant)
    )


def test_a_start_with_no_backend_flag_preserves_an_exported_local_only() -> None:
    # An operator who exported VAULTSPEC_RAG_LOCAL_ONLY=1 must keep it when
    # the start names no backend. Mutation check: with the absent flag passed
    # on as an explicit off, the daemon is handed "0" and this fails.
    prev = set_env(EnvVar.LOCAL_ONLY, "1")
    try:
        env = _env_for_start(local_only=False, qdrant=None)
        assert env[EnvVar.LOCAL_ONLY.value] == "1"
    finally:
        restore_env(EnvVar.LOCAL_ONLY, prev)


def test_the_qdrant_flag_overrides_an_exported_local_only() -> None:
    prev = set_env(EnvVar.LOCAL_ONLY, "1")
    try:
        env = _env_for_start(local_only=False, qdrant=True)
        assert env[EnvVar.LOCAL_ONLY.value] == "0"
        assert env[EnvVar.QDRANT_SERVER.value] == "1"
    finally:
        restore_env(EnvVar.LOCAL_ONLY, prev)
