"""Unit tests for VaultSpecConfigWrapper RAG-specific keys.

Covers the memory-budget, CUDA-ceiling, and resilience settings. The
backend-selection, code-noise, index-reuse, malformed-value, preprocessing,
storage-maintenance, and model-repo tests live in ``test_config_backend.py``,
split out to stay under the module-length gate.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from .._job_errors import JobError, JobErrorKind
from ..config._settings import (
    VaultSpecConfigWrapper,
    get_config,
    reset_config,
)
from ..config._types import EnvVar, hf_cache_only
from ..memory_probe import MemoryBudget
from ._scaffold import restore_env, set_env

pytestmark = [pytest.mark.unit]

_RESILIENCE_CONFIG_CASES: tuple[
    tuple[str, EnvVar, str, object, str, object],
    ...,
] = (
    (
        "store_operation_timeout_seconds",
        EnvVar.STORE_OPERATION_TIMEOUT_SECONDS,
        "VAULTSPEC_RAG_STORE_OPERATION_TIMEOUT_SECONDS",
        120.0,
        "75.5",
        75.5,
    ),
    (
        "store_write_retry_attempts",
        EnvVar.STORE_WRITE_RETRY_ATTEMPTS,
        "VAULTSPEC_RAG_STORE_WRITE_RETRY_ATTEMPTS",
        5,
        "4",
        4,
    ),
    (
        "store_write_retry_base_seconds",
        EnvVar.STORE_WRITE_RETRY_BASE_SECONDS,
        "VAULTSPEC_RAG_STORE_WRITE_RETRY_BASE_SECONDS",
        0.5,
        "1.25",
        1.25,
    ),
    (
        "store_write_retry_max_seconds",
        EnvVar.STORE_WRITE_RETRY_MAX_SECONDS,
        "VAULTSPEC_RAG_STORE_WRITE_RETRY_MAX_SECONDS",
        8.0,
        "10.5",
        10.5,
    ),
    (
        "index_segment_max_chunks",
        EnvVar.INDEX_SEGMENT_MAX_CHUNKS,
        "VAULTSPEC_RAG_INDEX_SEGMENT_MAX_CHUNKS",
        64,
        "32",
        32,
    ),
    (
        "index_segment_max_bytes",
        EnvVar.INDEX_SEGMENT_MAX_BYTES,
        "VAULTSPEC_RAG_INDEX_SEGMENT_MAX_BYTES",
        8 * 1024 * 1024,
        "4194304",
        4194304,
    ),
    (
        "index_queue_max_chunks",
        EnvVar.INDEX_QUEUE_MAX_CHUNKS,
        "VAULTSPEC_RAG_INDEX_QUEUE_MAX_CHUNKS",
        512,
        "256",
        256,
    ),
    (
        "index_queue_max_bytes",
        EnvVar.INDEX_QUEUE_MAX_BYTES,
        "VAULTSPEC_RAG_INDEX_QUEUE_MAX_BYTES",
        128 * 1024 * 1024,
        "67108864",
        67108864,
    ),
    (
        "index_no_progress_timeout_seconds",
        EnvVar.INDEX_NO_PROGRESS_TIMEOUT_SECONDS,
        "VAULTSPEC_RAG_INDEX_NO_PROGRESS_TIMEOUT_SECONDS",
        900.0,
        "123.5",
        123.5,
    ),
    (
        "watch_retry_base_seconds",
        EnvVar.WATCH_RETRY_BASE_SECONDS,
        "VAULTSPEC_RAG_WATCH_RETRY_BASE_SECONDS",
        30.0,
        "2.5",
        2.5,
    ),
    (
        "watch_retry_max_seconds",
        EnvVar.WATCH_RETRY_MAX_SECONDS,
        "VAULTSPEC_RAG_WATCH_RETRY_MAX_SECONDS",
        1800.0,
        "45.25",
        45.25,
    ),
    (
        "watch_retry_jitter_fraction",
        EnvVar.WATCH_RETRY_JITTER_FRACTION,
        "VAULTSPEC_RAG_WATCH_RETRY_JITTER_FRACTION",
        0.1,
        "0.25",
        0.25,
    ),
    (
        "watch_circuit_failure_threshold",
        EnvVar.WATCH_CIRCUIT_FAILURE_THRESHOLD,
        "VAULTSPEC_RAG_WATCH_CIRCUIT_FAILURE_THRESHOLD",
        3,
        "7",
        7,
    ),
    (
        "index_rss_ceiling_mib",
        EnvVar.INDEX_RSS_CEILING_MIB,
        "VAULTSPEC_RAG_INDEX_RSS_CEILING_MIB",
        16384.0,
        "4096.5",
        4096.5,
    ),
    (
        "index_cuda_ceiling_mib",
        EnvVar.INDEX_CUDA_CEILING_MIB,
        "VAULTSPEC_RAG_INDEX_CUDA_CEILING_MIB",
        0.0,
        "3072.25",
        3072.25,
    ),
    (
        "index_cuda_headroom_mib",
        EnvVar.INDEX_CUDA_HEADROOM_MIB,
        "VAULTSPEC_RAG_INDEX_CUDA_HEADROOM_MIB",
        2048.0,
        "1024.0",
        1024.0,
    ),
    (
        "index_cuda_allocator_fraction",
        EnvVar.INDEX_CUDA_ALLOCATOR_FRACTION,
        "VAULTSPEC_RAG_INDEX_CUDA_ALLOCATOR_FRACTION",
        0.8,
        "0.6",
        0.6,
    ),
    (
        "index_support_profile",
        EnvVar.INDEX_SUPPORT_PROFILE,
        "VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE",
        "managed-service",
        " Embedded-Local ",
        "embedded-local",
    ),
)


_RESILIENCE_ENV_VARS = tuple(case[1] for case in _RESILIENCE_CONFIG_CASES)


def _clear_resilience_env() -> dict[EnvVar, str | None]:
    return {var: os.environ.pop(var.value, None) for var in _RESILIENCE_ENV_VARS}


def _restore_resilience_env(saved: dict[EnvVar, str | None]) -> None:
    for var, previous in saved.items():
        restore_env(var, previous)


def test_service_idle_ttl_default() -> None:
    cfg = get_config()
    assert cfg.service_idle_ttl_seconds == 1800


@pytest.mark.parametrize(
    ("var", "value"),
    [
        (EnvVar.HF_HUB_OFFLINE, "1"),
        (EnvVar.HF_HUB_OFFLINE, "true"),
        (EnvVar.TRANSFORMERS_OFFLINE, "yes"),
        (EnvVar.TRANSFORMERS_OFFLINE, "on"),
    ],
)
def test_hf_cache_only_honours_supported_offline_modes(
    var: EnvVar,
    value: str,
) -> None:
    previous = set_env(var, value)
    try:
        assert hf_cache_only()
    finally:
        restore_env(var, previous)


def test_hf_cache_only_defaults_to_online_capable() -> None:
    previous_hub = os.environ.pop(EnvVar.HF_HUB_OFFLINE.value, None)
    previous_transformers = os.environ.pop(EnvVar.TRANSFORMERS_OFFLINE.value, None)
    try:
        assert not hf_cache_only()
    finally:
        if previous_hub is not None:
            os.environ[EnvVar.HF_HUB_OFFLINE.value] = previous_hub
        if previous_transformers is not None:
            os.environ[EnvVar.TRANSFORMERS_OFFLINE.value] = previous_transformers


def test_empty_path_env_falls_back_to_default_not_cwd() -> None:
    # M1 (security): an empty/whitespace path override must be treated as absent
    # and fall back to the default, never collapse to cwd (Path("") == ".") -
    # which would repoint the managed-dir delete/clean blast radius.
    # The session-wide singleton isolation fixture deliberately supplies a
    # non-default status directory. Compare the blank override with the
    # production default itself, not with that outer test override.
    default = cast("str", VaultSpecConfigWrapper._RAG_DEFAULTS["status_dir"])
    reset_config()
    prev = set_env(EnvVar.STATUS_DIR, "   ")
    reset_config()
    try:
        resolved = get_config().status_dir
        assert resolved == default
        assert resolved not in ("", ".")
    finally:
        restore_env(EnvVar.STATUS_DIR, prev)
        reset_config()


def test_nonempty_path_env_is_still_honoured() -> None:
    # Control: a real override must still win (M1 only neutralises blanks).
    prev = set_env(EnvVar.STATUS_DIR, "/custom/status/dir")
    reset_config()
    try:
        assert get_config().status_dir == "/custom/status/dir"
    finally:
        restore_env(EnvVar.STATUS_DIR, prev)
        reset_config()


def test_service_max_projects_default() -> None:
    cfg = get_config()
    assert cfg.service_max_projects == 16


def test_managed_log_max_bytes_default() -> None:
    cfg = get_config()
    assert cfg.managed_log_max_bytes == 2097152


def test_managed_log_backup_count_default() -> None:
    cfg = get_config()
    assert cfg.managed_log_backup_count == 5


def test_managed_log_environment_names_are_generic_only() -> None:
    assert EnvVar.MANAGED_LOG_MAX_BYTES.value == "VAULTSPEC_RAG_MANAGED_LOG_MAX_BYTES"
    assert (
        EnvVar.MANAGED_LOG_BACKUP_COUNT.value
        == "VAULTSPEC_RAG_MANAGED_LOG_BACKUP_COUNT"
    )
    assert not any(name.startswith("SERVICE_LOG_") for name in EnvVar.__members__)
    assert not any(
        name.startswith("service_log_") for name in VaultSpecConfigWrapper._RAG_DEFAULTS
    )


def test_cuda_ceiling_override_raises_and_lowers_past_the_profile() -> None:
    # The former min(profile, config) clamp could only ever lower the ceiling
    # below the 12 GiB profile constant. The override is now authoritative in
    # both directions: this test binds that a value ABOVE the profile raises the
    # effective ceiling (the bug that pinned a 16 GiB card at 12 GiB) and a value
    # BELOW it still lowers it.
    from ..memory_probe import resolve_index_cuda_ceiling_mib

    profile_mib = 12288.0
    raised = resolve_index_cuda_ceiling_mib(
        configured_mib=15000.0,
        headroom_mib=2048.0,
        profile_cuda_mib=profile_mib,
        baseline_mib=0.0,
    )
    lowered = resolve_index_cuda_ceiling_mib(
        configured_mib=6000.0,
        headroom_mib=2048.0,
        profile_cuda_mib=profile_mib,
        baseline_mib=0.0,
    )
    assert raised == 15000.0
    assert raised > profile_mib
    assert lowered == 6000.0
    assert lowered < profile_mib


def test_cuda_ceiling_auto_derives_or_falls_back_to_profile() -> None:
    # With no override (0), the ceiling derives from the device: total minus
    # headroom when the free reading is unavailable, or the profile figure when
    # the device total is also unavailable (the torch-free / CPU-only path).
    # The derivation is exercised over the readings themselves, so it states
    # what a given observation must yield rather than depending on a machine
    # that happens to present one.
    from .. import memory_probe

    derived = memory_probe.cuda_ceiling_from_observation(
        memory_probe.CudaCeilingObservation(
            device_total_mib=16376.0,
            free_mib=None,
            configured_mib=0.0,
            headroom_mib=2048.0,
            profile_cuda_mib=12288.0,
            baseline_mib=0.0,
        )
    )
    assert derived == 16376.0 - 2048.0

    fallback = memory_probe.cuda_ceiling_from_observation(
        memory_probe.CudaCeilingObservation(
            device_total_mib=None,
            free_mib=None,
            configured_mib=0.0,
            headroom_mib=2048.0,
            profile_cuda_mib=12288.0,
            baseline_mib=0.0,
        )
    )
    assert fallback == 12288.0


def test_cuda_ceiling_auto_is_absolute_over_free_plus_resident_baseline() -> None:
    # Double-count guard. The free reading is sampled after the resident
    # models loaded, so it already excludes them, while enforcement compares
    # peak and ceiling net of the resident baseline. The auto ceiling must
    # therefore be ABSOLUTE - baseline + free - headroom, clamped below
    # total - headroom. The observe() call below is the assertion that
    # catches the mutation back to a bare free - headroom ceiling: under
    # that form the resident models are charged twice and this legitimate
    # net forward (within free minus headroom) is falsely rejected as a
    # cuda_memory_ceiling JobError.
    from .. import memory_probe

    baseline = 5000.0
    ceiling = memory_probe.cuda_ceiling_from_observation(
        memory_probe.CudaCeilingObservation(
            device_total_mib=16000.0,
            free_mib=6000.0,
            configured_mib=0.0,
            headroom_mib=2048.0,
            profile_cuda_mib=12288.0,
            baseline_mib=baseline,
        )
    )
    budget = memory_probe.MemoryBudget(
        cuda_ceiling_mib=ceiling,
        cuda_baseline_mib=baseline,
    )
    # Net demand 3500 MiB sits inside free - headroom (3952 MiB): admitted.
    snapshot = budget.observe(
        label="net forward within free memory",
        rss_mib=0.0,
        cuda_allocated_mib=baseline + 3500.0,
        cuda_reserved_mib=baseline + 3500.0,
    )
    assert snapshot.peak_cuda_allocated_mib == baseline + 3500.0
    assert ceiling == baseline + 6000.0 - 2048.0

    # An idle-device free reading recovers the total - headroom clamp.
    clamped = memory_probe.cuda_ceiling_from_observation(
        memory_probe.CudaCeilingObservation(
            device_total_mib=16000.0,
            free_mib=15500.0,
            configured_mib=0.0,
            headroom_mib=2048.0,
            profile_cuda_mib=12288.0,
            baseline_mib=baseline,
        )
    )
    assert clamped == 16000.0 - 2048.0


def test_document_encode_batch_is_independent_of_vault_and_code() -> None:
    # Document fragments are window-sized after chunk-bounding, so the document
    # encode sub-batch is decoupled from the vault and code sub-batches and
    # defaults smaller. This test binds that independence: pointing the document
    # path back at embedding_encode_batch_size would silently reintroduce the
    # window-sized-batch overrun the dedicated knob exists to prevent.
    cfg = get_config()
    assert cfg.embedding_document_encode_batch_size == 12
    assert cfg.embedding_encode_batch_size == 32
    assert cfg.embedding_code_encode_batch_size == 32
    assert cfg.embedding_document_encode_batch_size != cfg.embedding_encode_batch_size


def test_document_encode_batch_env_override_is_independent() -> None:
    # The document knob overrides on its own env var without perturbing the
    # vault or code sub-batches.
    prev = set_env(EnvVar.EMBEDDING_DOCUMENT_ENCODE_BATCH_SIZE, "5")
    try:
        reset_config()
        cfg = get_config()
        value = cfg.embedding_document_encode_batch_size
        assert value == 5
        assert isinstance(value, int)
        assert cfg.embedding_encode_batch_size == 32
        assert cfg.embedding_code_encode_batch_size == 32
    finally:
        restore_env(EnvVar.EMBEDDING_DOCUMENT_ENCODE_BATCH_SIZE, prev)
        reset_config()


def test_service_idle_ttl_env_override() -> None:
    prev = set_env(EnvVar.SERVICE_IDLE_TTL_SECONDS, "60")
    try:
        reset_config()
        cfg = get_config()
        value = cfg.service_idle_ttl_seconds
        assert value == 60
        assert isinstance(value, int)
    finally:
        restore_env(EnvVar.SERVICE_IDLE_TTL_SECONDS, prev)
        reset_config()


def test_service_max_projects_env_override() -> None:
    prev = set_env(EnvVar.SERVICE_MAX_PROJECTS, "4")
    try:
        reset_config()
        cfg = get_config()
        value = cfg.service_max_projects
        assert value == 4
        assert isinstance(value, int)
    finally:
        restore_env(EnvVar.SERVICE_MAX_PROJECTS, prev)
        reset_config()


def test_managed_log_max_bytes_env_override() -> None:
    prev = set_env(EnvVar.MANAGED_LOG_MAX_BYTES, "4096")
    try:
        reset_config()
        cfg = get_config()
        value = cfg.managed_log_max_bytes
        assert value == 4096
        assert isinstance(value, int)
    finally:
        restore_env(EnvVar.MANAGED_LOG_MAX_BYTES, prev)
        reset_config()


def test_managed_log_backup_count_env_override() -> None:
    prev = set_env(EnvVar.MANAGED_LOG_BACKUP_COUNT, "2")
    try:
        reset_config()
        cfg = get_config()
        value = cfg.managed_log_backup_count
        assert value == 2
        assert isinstance(value, int)
    finally:
        restore_env(EnvVar.MANAGED_LOG_BACKUP_COUNT, prev)
        reset_config()


@pytest.mark.parametrize("raw", ["0", "-1"])
def test_managed_log_max_bytes_rejects_unbounded_values(raw: str) -> None:
    prev = set_env(EnvVar.MANAGED_LOG_MAX_BYTES, raw)
    try:
        reset_config()
        with pytest.raises(ValueError, match="must be a positive integer"):
            _ = get_config().managed_log_max_bytes
    finally:
        restore_env(EnvVar.MANAGED_LOG_MAX_BYTES, prev)
        reset_config()


def test_managed_log_backup_count_rejects_negative_value() -> None:
    prev = set_env(EnvVar.MANAGED_LOG_BACKUP_COUNT, "-1")
    try:
        reset_config()
        with pytest.raises(ValueError, match="must be a non-negative integer"):
            _ = get_config().managed_log_backup_count
    finally:
        restore_env(EnvVar.MANAGED_LOG_BACKUP_COUNT, prev)
        reset_config()


def test_resilience_configuration_defaults() -> None:
    saved = _clear_resilience_env()
    try:
        reset_config()
        cfg = get_config()
        for (
            attribute,
            _var,
            _env_name,
            expected,
            _raw,
            _coerced,
        ) in _RESILIENCE_CONFIG_CASES:
            value = cast("object", getattr(cfg, attribute))
            assert value == expected
            assert type(value) is type(expected)
    finally:
        _restore_resilience_env(saved)
        reset_config()


@pytest.mark.parametrize(
    ("attribute", "var", "env_name", "_default", "raw", "expected"),
    _RESILIENCE_CONFIG_CASES,
    ids=[case[0] for case in _RESILIENCE_CONFIG_CASES],
)
def test_resilience_configuration_environment_mapping_and_coercion(
    attribute: str,
    var: EnvVar,
    env_name: str,
    _default: object,
    raw: str,
    expected: object,
) -> None:
    saved = _clear_resilience_env()
    os.environ[var.value] = raw
    try:
        reset_config()
        assert var.value == env_name
        value = cast("object", getattr(get_config(), attribute))
        assert value == expected
        assert type(value) is type(expected)
    finally:
        _restore_resilience_env(saved)
        reset_config()


@pytest.mark.parametrize(
    ("var", "attribute"),
    [
        (EnvVar.STORE_WRITE_RETRY_ATTEMPTS, "store_write_retry_attempts"),
        (EnvVar.INDEX_SEGMENT_MAX_CHUNKS, "index_segment_max_chunks"),
        (EnvVar.INDEX_SEGMENT_MAX_BYTES, "index_segment_max_bytes"),
        (EnvVar.INDEX_QUEUE_MAX_CHUNKS, "index_queue_max_chunks"),
        (EnvVar.INDEX_QUEUE_MAX_BYTES, "index_queue_max_bytes"),
        (
            EnvVar.WATCH_CIRCUIT_FAILURE_THRESHOLD,
            "watch_circuit_failure_threshold",
        ),
    ],
)
def test_resilience_positive_integer_settings_reject_zero(
    var: EnvVar,
    attribute: str,
) -> None:
    saved = _clear_resilience_env()
    os.environ[var.value] = "0"
    try:
        reset_config()
        with pytest.raises(ValueError, match=attribute):
            getattr(get_config(), attribute)
    finally:
        _restore_resilience_env(saved)
        reset_config()


@pytest.mark.parametrize(
    ("var", "attribute"),
    [
        (
            EnvVar.STORE_OPERATION_TIMEOUT_SECONDS,
            "store_operation_timeout_seconds",
        ),
        (
            EnvVar.STORE_WRITE_RETRY_BASE_SECONDS,
            "store_write_retry_base_seconds",
        ),
        (
            EnvVar.STORE_WRITE_RETRY_MAX_SECONDS,
            "store_write_retry_max_seconds",
        ),
        (
            EnvVar.INDEX_NO_PROGRESS_TIMEOUT_SECONDS,
            "index_no_progress_timeout_seconds",
        ),
        (EnvVar.WATCH_RETRY_BASE_SECONDS, "watch_retry_base_seconds"),
        (EnvVar.WATCH_RETRY_MAX_SECONDS, "watch_retry_max_seconds"),
        (EnvVar.INDEX_RSS_CEILING_MIB, "index_rss_ceiling_mib"),
        (EnvVar.INDEX_CUDA_HEADROOM_MIB, "index_cuda_headroom_mib"),
    ],
)
def test_resilience_positive_float_settings_reject_zero(
    var: EnvVar,
    attribute: str,
) -> None:
    saved = _clear_resilience_env()
    os.environ[var.value] = "0"
    try:
        reset_config()
        with pytest.raises(ValueError, match=attribute):
            getattr(get_config(), attribute)
    finally:
        _restore_resilience_env(saved)
        reset_config()


def test_cuda_ceiling_accepts_zero_sentinel_but_rejects_negative() -> None:
    # index_cuda_ceiling_mib carries an in-band 0 sentinel meaning "auto-derive
    # from the device", so unlike the other float ceilings it must ACCEPT zero.
    # A negative override is still nonsense and must be rejected. This guard
    # binds the sentinel contract: reverting the knob to a positive-only
    # validator would break auto-derivation, and dropping the lower bound would
    # admit a negative ceiling.
    saved = _clear_resilience_env()
    try:
        os.environ[EnvVar.INDEX_CUDA_CEILING_MIB.value] = "0"
        reset_config()
        assert get_config().index_cuda_ceiling_mib == 0.0

        os.environ[EnvVar.INDEX_CUDA_CEILING_MIB.value] = "-1"
        reset_config()
        with pytest.raises(ValueError, match="index_cuda_ceiling_mib"):
            _ = get_config().index_cuda_ceiling_mib
    finally:
        _restore_resilience_env(saved)
        reset_config()


@pytest.mark.parametrize("raw", ["nan", "inf"])
def test_resilience_positive_float_settings_reject_nonfinite(raw: str) -> None:
    saved = _clear_resilience_env()
    os.environ[EnvVar.INDEX_NO_PROGRESS_TIMEOUT_SECONDS.value] = raw
    try:
        reset_config()
        with pytest.raises(ValueError, match="index_no_progress_timeout_seconds"):
            _ = get_config().index_no_progress_timeout_seconds
    finally:
        _restore_resilience_env(saved)
        reset_config()


@pytest.mark.parametrize("raw", ["-0.01", "1.01", "nan"])
def test_watch_retry_jitter_rejects_values_outside_closed_unit_interval(
    raw: str,
) -> None:
    saved = _clear_resilience_env()
    os.environ[EnvVar.WATCH_RETRY_JITTER_FRACTION.value] = raw
    try:
        reset_config()
        with pytest.raises(ValueError, match="watch_retry_jitter_fraction"):
            _ = get_config().watch_retry_jitter_fraction
    finally:
        _restore_resilience_env(saved)
        reset_config()


@pytest.mark.parametrize("raw", ["0", "1.01", "nan"])
def test_cuda_allocator_fraction_rejects_values_outside_open_closed_interval(
    raw: str,
) -> None:
    saved = _clear_resilience_env()
    os.environ[EnvVar.INDEX_CUDA_ALLOCATOR_FRACTION.value] = raw
    try:
        reset_config()
        with pytest.raises(ValueError, match="index_cuda_allocator_fraction"):
            _ = get_config().index_cuda_allocator_fraction
    finally:
        _restore_resilience_env(saved)
        reset_config()


@pytest.mark.parametrize(
    ("var", "attribute", "raw", "expected"),
    [
        (
            EnvVar.WATCH_RETRY_JITTER_FRACTION,
            "watch_retry_jitter_fraction",
            "0.0",
            0.0,
        ),
        (
            EnvVar.WATCH_RETRY_JITTER_FRACTION,
            "watch_retry_jitter_fraction",
            "1.0",
            1.0,
        ),
        (
            EnvVar.INDEX_CUDA_ALLOCATOR_FRACTION,
            "index_cuda_allocator_fraction",
            "1.0",
            1.0,
        ),
    ],
)
def test_fraction_settings_accept_included_endpoints(
    var: EnvVar,
    attribute: str,
    raw: str,
    expected: float,
) -> None:
    saved = _clear_resilience_env()
    os.environ[var.value] = raw
    try:
        reset_config()
        assert getattr(get_config(), attribute) == expected
    finally:
        _restore_resilience_env(saved)
        reset_config()


def test_index_support_profile_rejects_unknown_name() -> None:
    saved = _clear_resilience_env()
    os.environ[EnvVar.INDEX_SUPPORT_PROFILE.value] = "unknown-profile"
    try:
        reset_config()
        with pytest.raises(ValueError, match="index_support_profile"):
            _ = get_config().index_support_profile
    finally:
        _restore_resilience_env(saved)
        reset_config()


@pytest.mark.parametrize(
    ("segment_var", "queue_var", "queue_attribute"),
    [
        (
            EnvVar.INDEX_SEGMENT_MAX_CHUNKS,
            EnvVar.INDEX_QUEUE_MAX_CHUNKS,
            "index_queue_max_chunks",
        ),
        (
            EnvVar.INDEX_SEGMENT_MAX_BYTES,
            EnvVar.INDEX_QUEUE_MAX_BYTES,
            "index_queue_max_bytes",
        ),
    ],
)
def test_index_queue_budget_must_admit_one_segment(
    segment_var: EnvVar,
    queue_var: EnvVar,
    queue_attribute: str,
) -> None:
    saved = _clear_resilience_env()
    os.environ[segment_var.value] = "8"
    os.environ[queue_var.value] = "8"
    try:
        reset_config()
        assert getattr(get_config(), queue_attribute) == 8
        os.environ[queue_var.value] = "7"
        with pytest.raises(ValueError, match="greater than or equal"):
            getattr(get_config(), queue_attribute)
    finally:
        _restore_resilience_env(saved)
        reset_config()


@pytest.mark.parametrize(
    ("base_var", "max_var", "max_attribute"),
    [
        (
            EnvVar.STORE_WRITE_RETRY_BASE_SECONDS,
            EnvVar.STORE_WRITE_RETRY_MAX_SECONDS,
            "store_write_retry_max_seconds",
        ),
        (
            EnvVar.WATCH_RETRY_BASE_SECONDS,
            EnvVar.WATCH_RETRY_MAX_SECONDS,
            "watch_retry_max_seconds",
        ),
    ],
)
def test_retry_maximum_must_not_be_less_than_base(
    base_var: EnvVar,
    max_var: EnvVar,
    max_attribute: str,
) -> None:
    saved = _clear_resilience_env()
    os.environ[base_var.value] = "8"
    os.environ[max_var.value] = "8"
    try:
        reset_config()
        assert getattr(get_config(), max_attribute) == 8.0
        os.environ[max_var.value] = "7"
        with pytest.raises(ValueError, match="greater than or equal"):
            getattr(get_config(), max_attribute)
    finally:
        _restore_resilience_env(saved)
        reset_config()


def test_low_configured_memory_budget_accepts_exact_limit_and_latches_rss() -> None:
    saved = _clear_resilience_env()
    os.environ[EnvVar.INDEX_RSS_CEILING_MIB.value] = "4"
    os.environ[EnvVar.INDEX_CUDA_CEILING_MIB.value] = "3"
    try:
        reset_config()
        cfg = get_config()
        budget = MemoryBudget(
            rss_ceiling_mib=cfg.index_rss_ceiling_mib,
            cuda_ceiling_mib=cfg.index_cuda_ceiling_mib,
        )
        exact = budget.observe(
            label="exact-low-limits",
            rss_mib=4.0,
            cuda_allocated_mib=3.0,
            cuda_reserved_mib=3.0,
        )
        assert exact.rss_mib == exact.rss_ceiling_mib == 4.0
        assert exact.cuda_allocated_mib == exact.cuda_ceiling_mib == 3.0
        assert exact.cuda_reserved_mib == exact.cuda_ceiling_mib == 3.0

        with pytest.raises(JobError) as first_failure:
            budget.observe(
                label="first-rss-failure",
                rss_mib=4.1,
                cuda_allocated_mib=3.1,
                cuda_reserved_mib=3.1,
            )
        assert first_failure.value.error_kind is JobErrorKind.RSS_MEMORY_CEILING
        violating_snapshot = budget.snapshot
        assert violating_snapshot is not None
        assert violating_snapshot.label == "first-rss-failure"

        with pytest.raises(JobError) as latched_failure:
            budget.observe(
                label="later-safe-observation",
                rss_mib=0.0,
                cuda_allocated_mib=0.0,
                cuda_reserved_mib=0.0,
            )
        assert latched_failure.value.error_kind is first_failure.value.error_kind
        assert latched_failure.value.detail == first_failure.value.detail
        assert budget.snapshot is violating_snapshot
    finally:
        _restore_resilience_env(saved)
        reset_config()


def test_low_configured_cuda_budget_returns_typed_failure() -> None:
    saved = _clear_resilience_env()
    os.environ[EnvVar.INDEX_CUDA_CEILING_MIB.value] = "3"
    try:
        reset_config()
        budget = MemoryBudget(cuda_ceiling_mib=get_config().index_cuda_ceiling_mib)
        with pytest.raises(JobError) as failure:
            budget.observe(
                label="cuda-failure",
                rss_mib=0.0,
                cuda_allocated_mib=3.1,
                cuda_reserved_mib=0.0,
            )
        assert failure.value.error_kind is JobErrorKind.CUDA_MEMORY_CEILING
        # The detail must name the allocated high-water measure: the ceiling
        # enforces demand, and this match catches a reintroduced reserved
        # comparison relabelling the failure.
        assert "CUDA allocated" in failure.value.detail
    finally:
        _restore_resilience_env(saved)
        reset_config()


def test_cuda_reserved_above_ceiling_is_diagnostic_not_enforced() -> None:
    """Reserved (allocator retention) above the ceiling must be admitted.

    Reserved ratchets with process retention history; only the allocated
    high-water (demand) may fail a job. This test guards the demotion: it
    fails if a reserved-vs-ceiling comparison is reintroduced into
    ``MemoryBudget`` enforcement.
    """
    saved = _clear_resilience_env()
    os.environ[EnvVar.INDEX_CUDA_CEILING_MIB.value] = "3"
    try:
        reset_config()
        budget = MemoryBudget(cuda_ceiling_mib=get_config().index_cuda_ceiling_mib)
        snapshot = budget.observe(
            label="reserved-retention-only",
            rss_mib=0.0,
            cuda_allocated_mib=1.0,
            cuda_reserved_mib=11.0,
        )
        assert snapshot.peak_cuda_reserved_mib == 11.0
        assert snapshot.cuda_ceiling_mib == 3.0
        # Reserved stays reported on the snapshot for operators; it just no
        # longer decides outcome.
        later = budget.observe(
            label="still-admitted",
            rss_mib=0.0,
            cuda_allocated_mib=1.5,
            cuda_reserved_mib=12.0,
        )
        assert later.peak_cuda_reserved_mib == 12.0
    finally:
        _restore_resilience_env(saved)
        reset_config()


def test_cuda_ceiling_comparison_is_baseline_consistent() -> None:
    """Double-count guard: the baseline comes off both sides or neither.

    A captured peak is absolute (a post-rebase counter starts at the
    resident models), so the resident baseline must be subtracted from the
    peak AND the ceiling on the same side of the comparison. Each assertion
    is deliberately narrow and pins one single-side mutation:

    - a peak between (ceiling - baseline) and the ceiling must be ADMITTED;
      it is rejected iff the baseline is subtracted from the ceiling only -
      the double-count that covertly tightens the ceiling by the resident
      models' size and reproduces the spurious-failure defect;
    - a peak just above the ceiling must be REJECTED; it is admitted iff
      the baseline is subtracted from the peak only.
    """
    admitted_budget = MemoryBudget(cuda_ceiling_mib=1000.0, cuda_baseline_mib=400.0)
    admitted = admitted_budget.observe(
        label="peak-between-net-ceiling-and-ceiling",
        rss_mib=0.0,
        cuda_allocated_mib=900.0,
        cuda_reserved_mib=0.0,
    )
    assert admitted.peak_cuda_allocated_mib == 900.0

    rejecting_budget = MemoryBudget(cuda_ceiling_mib=1000.0, cuda_baseline_mib=400.0)
    with pytest.raises(JobError) as failure:
        rejecting_budget.observe(
            label="peak-above-ceiling",
            rss_mib=0.0,
            cuda_allocated_mib=1050.0,
            cuda_reserved_mib=0.0,
        )
    assert failure.value.error_kind is JobErrorKind.CUDA_MEMORY_CEILING
    # The failure names the baseline-relative measure so an operator reads
    # indexing demand against indexing headroom, not raw absolutes.
    assert "resident baseline" in failure.value.detail


def test_memory_budget_fails_closed_when_real_measurements_are_unavailable() -> None:
    source_root = Path(__file__).resolve().parents[2]
    # The measurement libraries are blocked by name rather than by dropping
    # site-packages: the probe imports the framework's value vocabulary, and
    # an installed framework shares site-packages with psutil and torch, so
    # hiding one by path layout would hide both or neither.
    child_code = """
import sys

sys.modules["psutil"] = None
sys.modules["torch"] = None
sys.path.insert(0, sys.argv[1])

from vaultspec_rag._job_errors import JobError, JobErrorKind  # absolute-import-ok
from vaultspec_rag.memory_probe import MemoryBudget  # absolute-import-ok

rss_budget = MemoryBudget(rss_ceiling_mib=1.0)
try:
    rss_budget.sample("rss-unavailable")
except JobError as exc:
    assert exc.error_kind is JobErrorKind.RSS_MEMORY_CEILING
    assert exc.detail == (
        "RSS measurement was unavailable while enforcing the 1.0 MiB "
        "ceiling at rss-unavailable"
    )
    rss_kind = exc.error_kind.value
else:
    raise AssertionError("unavailable RSS measurement was admitted")

cuda_budget = MemoryBudget(cuda_ceiling_mib=1.0)
try:
    cuda_budget.sample("cuda-unavailable")
except JobError as exc:
    assert exc.error_kind is JobErrorKind.CUDA_MEMORY_CEILING
    assert exc.detail == (
        "CUDA measurement was unavailable while enforcing the 1.0 MiB "
        "ceiling at cuda-unavailable"
    )
    cuda_kind = exc.error_kind.value
else:
    raise AssertionError("unavailable CUDA measurement was admitted")

print(f"{rss_kind},{cuda_kind}")
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            child_code,
            os.fspath(source_root),
        ],
        cwd=source_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "rss_memory_ceiling,cuda_memory_ceiling"
