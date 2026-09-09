"""Unit tests for the filesystem-watcher settings the config exposes.

Split from the general configuration tests because the adaptive watcher knobs
are not independent of one another: several are bounds on the others, and the
relations between them are asserted here alongside the legacy inputs that map
onto them.
"""

from __future__ import annotations

import pytest
from vaultspec_core.config import get_config as get_base_config

from ..config._settings import VaultSpecConfigWrapper, get_config, reset_config
from ..config._types import EnvVar
from ._scaffold import restore_env, set_env

pytestmark = [pytest.mark.unit]


def _config_with_overrides(overrides: dict[str, object]) -> VaultSpecConfigWrapper:
    return VaultSpecConfigWrapper(get_base_config(overrides), overrides)


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
    prev = set_env(EnvVar.WATCH_DEBOUNCE_MS, "500")
    try:
        reset_config()
        cfg = get_config()
        value = cfg.watch_debounce_ms
        assert value == 500
        assert isinstance(value, int)
    finally:
        restore_env(EnvVar.WATCH_DEBOUNCE_MS, prev)
        reset_config()


def test_watch_debounce_ms_env_zero_means_no_delay() -> None:
    # 0 is a valid tuning value (no debounce), NOT a disable sentinel.
    prev = set_env(EnvVar.WATCH_DEBOUNCE_MS, "0")
    try:
        reset_config()
        cfg = get_config()
        assert cfg.watch_debounce_ms == 0
        # The watcher stays enabled; only watch_enabled disables it.
        assert cfg.watch_enabled is True
    finally:
        restore_env(EnvVar.WATCH_DEBOUNCE_MS, prev)
        reset_config()


def test_watch_cooldown_s_env_override() -> None:
    prev = set_env(EnvVar.WATCH_COOLDOWN_S, "1.5")
    try:
        reset_config()
        cfg = get_config()
        value = cfg.watch_cooldown_s
        assert value == 1.5
        assert isinstance(value, float)
    finally:
        restore_env(EnvVar.WATCH_COOLDOWN_S, prev)
        reset_config()


def test_adaptive_watcher_policy_defaults_are_bounded() -> None:
    cfg = get_config()

    assert cfg.watch_coalesce_min_seconds == 2.0
    assert cfg.watch_coalesce_max_seconds == 30.0
    assert cfg.watch_cooling_max_seconds == 120.0
    assert cfg.watch_maximum_freshness_seconds == 300.0
    assert cfg.watch_measurement_reevaluation_seconds == 5.0
    assert cfg.watch_batch_path_limit == 10_000
    assert cfg.watch_scope_max_paths == 100_000
    assert cfg.watch_scope_max_bytes == 8 * 1024 * 1024


def test_legacy_watcher_timing_inputs_map_to_adaptive_bounds() -> None:
    cfg = _config_with_overrides(
        {
            "watch_debounce_ms": 750,
            "watch_cooldown_s": 12.5,
        }
    )

    assert cfg.watch_debounce_ms == 750
    assert cfg.watch_cooldown_s == 12.5
    assert cfg.watch_coalesce_min_seconds == 0.75
    assert cfg.watch_coalesce_max_seconds == 0.75
    assert cfg.watch_cooling_max_seconds == 12.5


def test_adaptive_watcher_inputs_take_precedence_over_legacy_mapping() -> None:
    cfg = _config_with_overrides(
        {
            "watch_debounce_ms": 750,
            "watch_cooldown_s": 12.5,
            "watch_coalesce_min_seconds": 3.0,
            "watch_coalesce_max_seconds": 9.0,
            "watch_cooling_max_seconds": 45.0,
        }
    )

    assert cfg.watch_coalesce_min_seconds == 3.0
    assert cfg.watch_coalesce_max_seconds == 9.0
    assert cfg.watch_cooling_max_seconds == 45.0


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "watch_coalesce_min_seconds": 12.0,
                "watch_coalesce_max_seconds": 6.0,
            },
            "watch_coalesce_max_seconds must be greater than or equal to "
            "watch_coalesce_min_seconds",
        ),
        (
            {
                "watch_coalesce_max_seconds": 31.0,
                "watch_maximum_freshness_seconds": 30.0,
            },
            "watch_maximum_freshness_seconds must be greater than or equal to "
            "watch_coalesce_max_seconds",
        ),
        (
            {
                "watch_cooling_max_seconds": 31.0,
                "watch_maximum_freshness_seconds": 30.0,
            },
            "watch_maximum_freshness_seconds must be greater than or equal to "
            "watch_cooling_max_seconds",
        ),
        (
            {
                "watch_batch_path_limit": 101,
                "watch_scope_max_paths": 100,
            },
            "watch_batch_path_limit must be less than or equal to "
            "watch_scope_max_paths",
        ),
    ],
)
def test_adaptive_watcher_policy_rejects_inconsistent_relations(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _config_with_overrides(overrides)


def test_adaptive_watcher_policy_reads_environment_bounds() -> None:
    previous = set_env(EnvVar.WATCH_MAXIMUM_FRESHNESS_SECONDS, "480.5")
    try:
        reset_config()
        assert get_config().watch_maximum_freshness_seconds == 480.5
    finally:
        restore_env(EnvVar.WATCH_MAXIMUM_FRESHNESS_SECONDS, previous)
        reset_config()


@pytest.mark.parametrize(
    "raw",
    ["0", "false", "False", "no", "off", ""],
    ids=["zero", "false-lower", "false-title", "no", "off", "empty"],
)
def test_watch_enabled_env_falsey(raw: str) -> None:
    prev = set_env(EnvVar.WATCH_ENABLED, raw)
    try:
        reset_config()
        cfg = get_config()
        value = cfg.watch_enabled
        assert value is False
        assert isinstance(value, bool)
    finally:
        restore_env(EnvVar.WATCH_ENABLED, prev)
        reset_config()


@pytest.mark.parametrize(
    "raw",
    ["1", "true", "TRUE", "yes", "Yes"],
    ids=["one", "true-lower", "true-upper", "yes-lower", "yes-title"],
)
def test_watch_enabled_env_truthy(raw: str) -> None:
    prev = set_env(EnvVar.WATCH_ENABLED, raw)
    try:
        reset_config()
        cfg = get_config()
        value = cfg.watch_enabled
        assert value is True
        assert isinstance(value, bool)
    finally:
        restore_env(EnvVar.WATCH_ENABLED, prev)
        reset_config()
