"""Durable watcher retry, circuit, and convergence-generation tests."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from .._job_errors import JobError, JobErrorKind
from ..watcher import (
    _STATE_TRANSACTION_WORKER_SLOTS,
    _admit_watcher_attempt,
    _persist_observed_sources,
    _run_durable_retry_transaction,
)
from ..watcher_retry import (
    WatcherCircuitState,
    WatcherRetryPolicy,
    WatcherRetryStateError,
    WatcherSource,
)

if TYPE_CHECKING:
    from pathlib import Path


def _policy(
    path: Path,
    root: Path,
    *,
    now: float = 0.0,
    jitter_fraction: float = 0.2,
    source: WatcherSource = WatcherSource.CODE,
) -> WatcherRetryPolicy:
    return WatcherRetryPolicy(
        path,
        canonical_root=os.path.normcase(str(root.resolve())),
        source=source,
        base_seconds=10.0,
        max_seconds=25.0,
        jitter_fraction=jitter_fraction,
        failure_threshold=3,
        now=now,
    )


def _spawn_state_lock_holder(
    lock_path: Path,
    ready_path: Path,
    *,
    hold_seconds: float,
) -> subprocess.Popen[str]:
    script = "\n".join(
        (
            "import sys, time",
            "from pathlib import Path",
            "from vaultspec_rag._store_locks import FileLock",
            "lock = FileLock(Path(sys.argv[1]))",
            "assert lock.acquire()",
            "Path(sys.argv[2]).write_text('ready', encoding='utf-8')",
            "time.sleep(float(sys.argv[3]))",
            "lock.release()",
        )
    )
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(lock_path),
            str(ready_path),
            str(hold_seconds),
        ],
        text=True,
    )


def test_newer_convergence_generation_survives_older_success(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "code.json"
    first = _policy(state_path, tmp_path)
    second = _policy(state_path, tmp_path)

    dirty = first.mark_convergence_pending(now=1.0)
    assert dirty.convergence_generation == 1
    admitted = first.admit(now=1.0)
    assert admitted.admitted
    assert admitted.attempt_generation == 1

    newer = second.mark_convergence_pending(now=2.0)
    assert newer.convergence_generation == 2
    completed = first.record_success(1, now=3.0)
    assert completed.last_durable_progress_at == 3.0
    assert completed.convergence_pending

    next_attempt = second.admit(now=3.0)
    assert next_attempt.admitted
    assert next_attempt.attempt_generation == 2
    assert next_attempt.requires_unscoped
    settled = second.record_success(2, now=4.0)
    assert not settled.convergence_pending
    assert settled.circuit_state is WatcherCircuitState.CLOSED

    reloaded = _policy(state_path, tmp_path, now=5.0)
    assert reloaded.state == settled


def _fail_once(
    policy: WatcherRetryPolicy,
    error: BaseException,
    *,
    now: float,
    random_unit: float,
) -> WatcherRetryState:
    """Admit an attempt and fail it, returning the resulting state."""
    admitted = policy.admit(now=now)
    assert admitted.attempt_generation is not None
    return policy.record_failure(
        error,
        admitted.attempt_generation,
        now=now,
        random_unit=random_unit,
    )


def _drive_to_open_circuit(policy: WatcherRetryPolicy) -> None:
    """Fail three times, which is what opens the circuit."""
    policy.mark_convergence_pending(now=0.0)
    _fail_once(policy, TimeoutError("t"), now=0.0, random_unit=0.5)
    _fail_once(policy, ConnectionError("c"), now=11.0, random_unit=1.0)
    _fail_once(policy, TimeoutError("t"), now=35.0, random_unit=0.5)


def test_retry_backoff_grows_and_gates_admission(tmp_path: Path) -> None:
    policy = _policy(tmp_path / "code.json", tmp_path)
    policy.mark_convergence_pending(now=0.0)

    state = _fail_once(
        policy, TimeoutError("qdrant timed out"), now=1.0, random_unit=0.5
    )
    assert state.consecutive_failures == 1
    assert state.last_error_kind is JobErrorKind.TIMEOUT
    assert state.next_retry_at == 11.0
    assert state.circuit_state is WatcherCircuitState.CLOSED
    assert not policy.admit(now=10.9).admitted

    state = _fail_once(
        policy, ConnectionError("qdrant unavailable"), now=11.0, random_unit=1.0
    )
    assert state.next_retry_at == 35.0
    assert state.circuit_state is WatcherCircuitState.CLOSED


def test_third_failure_opens_the_circuit(tmp_path: Path) -> None:
    policy = _policy(tmp_path / "code.json", tmp_path)
    policy.mark_convergence_pending(now=0.0)
    _fail_once(policy, TimeoutError("t"), now=1.0, random_unit=0.5)
    _fail_once(policy, ConnectionError("c"), now=11.0, random_unit=1.0)

    state = _fail_once(policy, TimeoutError("timeout"), now=35.0, random_unit=0.5)

    assert state.next_retry_at == 60.0
    assert state.circuit_state is WatcherCircuitState.OPEN
    assert not policy.admit(now=59.9).admitted


def test_half_open_probe_is_single_flight(tmp_path: Path) -> None:
    policy = _policy(tmp_path / "code.json", tmp_path)
    _drive_to_open_circuit(policy)

    half_open = policy.admit(now=60.0)

    assert half_open.admitted
    assert half_open.circuit_state is WatcherCircuitState.HALF_OPEN
    assert half_open.attempt_generation is not None
    # Only one probe may be in flight while half-open.
    assert not policy.admit(now=60.0).admitted


def test_successful_probe_resets_the_circuit(tmp_path: Path) -> None:
    policy = _policy(tmp_path / "code.json", tmp_path)
    _drive_to_open_circuit(policy)
    half_open = policy.admit(now=60.0)
    assert half_open.attempt_generation is not None

    settled = policy.record_success(half_open.attempt_generation, now=61.0)

    assert settled.consecutive_failures == 0
    assert settled.last_error_kind is None
    assert settled.last_failure_at is None
    assert settled.last_durable_progress_at == 61.0
    assert settled.next_retry_at == 0.0
    assert settled.circuit_state is WatcherCircuitState.CLOSED
    assert not settled.convergence_pending


@pytest.mark.parametrize(
    "error, expected_kind",
    [
        (
            JobError(
                JobErrorKind.JOB_CAPACITY_EXCEEDED,
                "index admission capacity exhausted",
            ),
            JobErrorKind.JOB_CAPACITY_EXCEEDED,
        ),
        (OSError("No space left on device"), JobErrorKind.DISK_FULL),
        (MemoryError("host allocation failed"), JobErrorKind.OTHER),
    ],
)
def test_nonretryable_failure_opens_immediately(
    tmp_path: Path,
    error: BaseException,
    expected_kind: JobErrorKind,
) -> None:
    policy = _policy(tmp_path / "code.json", tmp_path)
    policy.mark_convergence_pending(now=0.0)
    decision = policy.admit(now=0.0)
    assert decision.attempt_generation is not None

    state = policy.record_failure(
        error,
        decision.attempt_generation,
        now=1.0,
        random_unit=0.5,
    )

    assert state.last_error_kind is expected_kind
    assert state.circuit_state is WatcherCircuitState.OPEN
    assert state.convergence_pending


def test_restart_reopens_unsettled_attempt_with_delay(tmp_path: Path) -> None:
    state_path = tmp_path / "code.json"
    script = "\n".join(
        (
            "import os, sys",
            "from pathlib import Path",
            (
                "from vaultspec_rag.watcher_retry import "
                "WatcherRetryPolicy, WatcherSource"
            ),
            "path, root = Path(sys.argv[1]), Path(sys.argv[2]).resolve()",
            (
                "policy = WatcherRetryPolicy(path, "
                "canonical_root=os.path.normcase(str(root)), "
                "source=WatcherSource.CODE, base_seconds=10.0, "
                "max_seconds=25.0, jitter_fraction=0.0, "
                "failure_threshold=3, now=0.0)"
            ),
            "policy.mark_convergence_pending(now=0.0)",
            "first = policy.admit(now=0.0)",
            "assert first.attempt_generation == 1",
            (
                "policy.record_failure(TimeoutError('timeout'), "
                "first.attempt_generation, now=0.0, random_unit=0.5)"
            ),
            "second = policy.admit(now=10.0)",
            "assert second.attempt_generation == 1",
            (
                "policy.record_failure(TimeoutError('timeout'), "
                "second.attempt_generation, now=10.0, random_unit=0.5)"
            ),
            "assert policy.admit(now=30.0).attempt_generation == 1",
        )
    )
    subprocess.run(
        [sys.executable, "-c", script, str(state_path), str(tmp_path)],
        check=True,
    )

    restarted = _policy(state_path, tmp_path, now=40.0, jitter_fraction=0.0)
    state = restarted.state
    assert state.consecutive_failures == 3
    assert state.last_error_kind is JobErrorKind.UNAVAILABLE
    assert state.circuit_state is WatcherCircuitState.OPEN
    assert state.next_retry_at == 65.0
    assert state.attempt_generation is None
    assert state.unscoped_required
    assert not restarted.admit(now=64.9).admitted
    assert restarted.admit(now=65.0).circuit_state is WatcherCircuitState.HALF_OPEN


def test_live_attempt_owner_is_not_reclaimed(tmp_path: Path) -> None:
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    policy.mark_convergence_pending(now=0.0)
    decision = policy.admit(now=0.0)
    assert decision.attempt_generation == 1

    overlapping = _policy(state_path, tmp_path, now=5.0)
    assert overlapping.state.attempt_generation == 1
    assert not overlapping.admit(now=100.0).admitted

    settled = policy.record_success(1, now=101.0)
    assert not settled.convergence_pending


@pytest.mark.asyncio
async def test_cancelled_contended_admission_settles_committed_claim(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    policy.mark_convergence_pending(now=0.0)
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    ready_path = tmp_path / "admission-lock-ready.marker"
    holder = _spawn_state_lock_holder(
        lock_path,
        ready_path,
        hold_seconds=2.4,
    )
    try:
        for _ in range(100):
            if ready_path.exists():
                break
            await asyncio.sleep(0.02)
        assert ready_path.exists()

        admission = asyncio.create_task(
            _admit_watcher_attempt(
                policy,
                source=WatcherSource.CODE,
                root_dir=tmp_path,
            )
        )
        await asyncio.sleep(0.05)
        admission.cancel()
        with pytest.raises(asyncio.CancelledError):
            await admission

        await asyncio.to_thread(holder.wait, 10.0)
        assert holder.returncode == 0
        assert policy.state.attempt_generation is None
        assert policy.state.convergence_pending
        assert policy.state.unscoped_required
        next_attempt = policy.admit()
        assert next_attempt.admitted
        assert next_attempt.attempt_generation is not None
        policy.record_interrupted(next_attempt.attempt_generation)
    finally:
        if holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=5.0)


@pytest.mark.asyncio
async def test_detached_admission_consumes_its_fenced_handoff(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    policy.mark_convergence_pending(now=0.0)
    ready_path = tmp_path / "detached-admission-ready.marker"
    holder = _spawn_state_lock_holder(
        state_path.with_name(f"{state_path.name}.lock"),
        ready_path,
        hold_seconds=3.5,
    )
    try:
        for _ in range(100):
            if ready_path.exists():
                break
            await asyncio.sleep(0.02)
        assert ready_path.exists()

        admission = asyncio.create_task(
            _admit_watcher_attempt(
                policy,
                source=WatcherSource.CODE,
                root_dir=tmp_path,
            )
        )
        await asyncio.sleep(0.05)
        started = asyncio.get_running_loop().time()
        admission.cancel()
        with pytest.raises(asyncio.CancelledError):
            await admission
        assert asyncio.get_running_loop().time() - started < 5.5
        assert list(tmp_path.glob("code.recovery.*.json"))

        await asyncio.to_thread(holder.wait, 10.0)
        assert holder.returncode == 0
        for _ in range(100):
            if not list(tmp_path.glob("code.recovery.*.json")):
                break
            await asyncio.sleep(0.02)
        assert not list(tmp_path.glob("code.recovery.*.json"))

        replacement = _policy(state_path, tmp_path)
        assert replacement.state.attempt_generation is None
        assert replacement.state.convergence_pending
        assert replacement.state.unscoped_required
        next_attempt = replacement.admit()
        assert next_attempt.admitted
        assert next_attempt.attempt_generation is not None
        replacement.record_interrupted(next_attempt.attempt_generation)
    finally:
        if holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=5.0)


def test_prestart_handoff_cancels_reserved_admission(tmp_path: Path) -> None:
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    policy.mark_convergence_pending(now=0.0)
    attempt_token = policy.reserve_admission()
    assert attempt_token is not None

    marker = policy.write_recovery_marker()
    decision = policy.admit_reserved(attempt_token, now=1.0)

    assert not decision.admitted
    replacement = _policy(state_path, tmp_path, now=2.0)
    assert not marker.exists()
    assert replacement.state.attempt_generation is None
    assert replacement.state.convergence_pending
    assert replacement.state.unscoped_required
    next_attempt = replacement.admit(now=2.0)
    assert next_attempt.admitted
    assert next_attempt.attempt_generation is not None
    replacement.record_interrupted(next_attempt.attempt_generation, now=3.0)


def test_handoff_without_reservation_closes_admission_authority(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path / "code.json", tmp_path)
    marker = policy.write_recovery_marker()

    with pytest.raises(WatcherRetryStateError, match="authority has been handed off"):
        policy.reserve_admission()

    assert marker.exists()


@pytest.mark.asyncio
async def test_cancellation_handoff_has_reserved_worker_capacity(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path / "code.json", tmp_path)
    acquired_slots = 0
    try:
        for _ in range(4):
            assert _STATE_TRANSACTION_WORKER_SLOTS.acquire(blocking=False)
            acquired_slots += 1

        persistence = asyncio.create_task(
            _run_durable_retry_transaction(
                policy.mark_convergence_pending,
                source=WatcherSource.CODE,
                root_dir=tmp_path,
                action="mark_convergence_pending",
                cancellation_fallback=policy.write_recovery_marker,
            )
        )
        await asyncio.sleep(0.05)
        started = asyncio.get_running_loop().time()
        persistence.cancel()
        with pytest.raises(asyncio.CancelledError):
            await persistence
        assert asyncio.get_running_loop().time() - started < 6.0
        assert list(tmp_path.glob("code.recovery.*.json"))
    finally:
        for _ in range(acquired_slots):
            _STATE_TRANSACTION_WORKER_SLOTS.release()

    replacement = _policy(tmp_path / "code.json", tmp_path)
    assert replacement.state.convergence_pending
    assert replacement.state.unscoped_required


def test_restored_unknown_scope_is_not_narrowed_by_new_event(tmp_path: Path) -> None:
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    policy.mark_convergence_pending(now=0.0)
    attempt = policy.admit(now=0.0)
    assert attempt.attempt_generation is not None
    policy.record_failure(
        OSError("No space left on device"),
        attempt.attempt_generation,
        now=1.0,
        random_unit=0.5,
    )

    restarted = _policy(state_path, tmp_path, now=2.0)
    restarted.mark_convergence_pending(now=3.0)
    decision = restarted.admit(now=11.0)
    assert decision.admitted
    assert decision.requires_unscoped


def test_interruption_releases_claim_and_preserves_unknown_scope(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path / "code.json", tmp_path)
    policy.mark_convergence_pending(now=0.0)
    attempt = policy.admit(now=0.0)
    assert attempt.attempt_generation is not None

    state = policy.record_interrupted(attempt.attempt_generation, now=1.0)
    assert state.attempt_generation is None
    assert state.consecutive_failures == 0
    assert state.convergence_pending
    assert state.unscoped_required
    assert policy.admit(now=1.0).admitted


def test_malformed_state_fails_closed_without_overwrite(tmp_path: Path) -> None:
    state_path = tmp_path / "code.json"
    malformed = '{"schema_version":1,"source":"code"}'
    state_path.write_text(malformed, encoding="utf-8")

    with pytest.raises((ValueError, WatcherRetryStateError)):
        _policy(state_path, tmp_path)

    assert state_path.read_text(encoding="utf-8") == malformed


def test_authority_mismatch_is_rejected(tmp_path: Path) -> None:
    state_path = tmp_path / "code.json"
    _policy(state_path, tmp_path)

    with pytest.raises(WatcherRetryStateError, match="root/source authority"):
        WatcherRetryPolicy(
            state_path,
            canonical_root=os.path.normcase(str((tmp_path / "other").resolve())),
            source=WatcherSource.CODE,
            base_seconds=10.0,
            max_seconds=25.0,
            jitter_fraction=0.2,
            failure_threshold=3,
            now=1.0,
        )


@pytest.mark.asyncio
async def test_permanent_state_path_error_fails_without_retrying(
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("blocks retry state directory", encoding="utf-8")
    started = asyncio.get_running_loop().time()

    with pytest.raises(WatcherRetryStateError, match="prepare failed"):
        await _run_durable_retry_transaction(
            lambda: _policy(blocker / "code.json", tmp_path),
            source=WatcherSource.CODE,
            root_dir=tmp_path,
            action="construct",
        )

    assert asyncio.get_running_loop().time() - started < 1.0


@pytest.mark.asyncio
async def test_permanent_lock_file_error_fails_without_retrying(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    lock_path.unlink()
    lock_path.mkdir()
    started = asyncio.get_running_loop().time()

    with pytest.raises(WatcherRetryStateError, match="lock failed"):
        await _run_durable_retry_transaction(
            policy.refresh,
            source=WatcherSource.CODE,
            root_dir=tmp_path,
            action="refresh",
        )

    assert asyncio.get_running_loop().time() - started < 1.0


def test_recovery_marker_clears_claim_and_forces_unscoped(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    policy.mark_convergence_pending(now=0.0)
    attempt = policy.admit(now=0.0)
    assert attempt.attempt_generation is not None
    marker = policy.write_recovery_marker()
    assert marker.exists()
    assert not list(tmp_path.glob(".code.recovery-write.*.tmp"))

    recovered = _policy(state_path, tmp_path, now=1.0)

    assert recovered.state.attempt_generation is None
    assert recovered.state.convergence_pending
    assert recovered.state.unscoped_required
    assert not marker.exists()
    next_attempt = recovered.admit(now=1.0)
    assert next_attempt.admitted
    assert next_attempt.requires_unscoped
    assert next_attempt.attempt_generation is not None
    recovered.record_interrupted(next_attempt.attempt_generation, now=2.0)


def test_late_recovery_marker_preserves_newer_live_claim(tmp_path: Path) -> None:
    state_path = tmp_path / "code.json"
    retiring = _policy(state_path, tmp_path)
    retiring.mark_convergence_pending(now=0.0)
    retiring_attempt = retiring.admit(now=0.0)
    assert retiring_attempt.attempt_generation is not None
    retiring.record_interrupted(retiring_attempt.attempt_generation, now=1.0)

    replacement = _policy(state_path, tmp_path, now=2.0)
    replacement_attempt = replacement.admit(now=2.0)
    assert replacement_attempt.attempt_generation is not None
    marker = retiring.write_recovery_marker()

    settled = replacement.record_success(
        replacement_attempt.attempt_generation,
        now=3.0,
    )

    assert not marker.exists()
    assert settled.attempt_generation is None
    assert settled.convergence_pending
    assert settled.unscoped_required
    assert settled.convergence_generation > replacement_attempt.attempt_generation


def test_inactive_same_process_fence_is_consumed(tmp_path: Path) -> None:
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    policy.mark_convergence_pending(now=0.0)
    attempt = policy.admit(now=0.0)
    assert attempt.attempt_generation is not None
    marker = policy.write_recovery_marker()
    hidden = marker.with_suffix(".held")
    marker.replace(hidden)
    policy.record_interrupted(attempt.attempt_generation, now=1.0)
    hidden.replace(marker)

    replacement = _policy(state_path, tmp_path, now=2.0)

    assert not marker.exists()
    assert replacement.state.attempt_generation is None
    assert replacement.state.convergence_pending
    assert replacement.state.unscoped_required


def test_invalid_recovery_marker_fails_closed(tmp_path: Path) -> None:
    state_path = tmp_path / "code.json"
    _policy(state_path, tmp_path)
    marker = tmp_path / "code.recovery.invalid.json"
    marker.mkdir()
    started = time.monotonic()

    with pytest.raises(WatcherRetryStateError, match="read recovery marker"):
        _policy(state_path, tmp_path, now=1.0)

    assert time.monotonic() - started < 1.0
    marker.rmdir()


def test_time_confirmed_recovery_temporary_is_removed(tmp_path: Path) -> None:
    policy = _policy(tmp_path / "code.json", tmp_path)
    stale = time.time() - 7200.0
    temporaries = [
        tmp_path / f".code.recovery-write.abandoned-{index}.tmp" for index in range(300)
    ]
    for temporary in temporaries:
        temporary.write_text("partial", encoding="utf-8")
        os.utime(temporary, (stale, stale))

    policy.refresh()

    assert not any(temporary.exists() for temporary in temporaries)


@pytest.mark.asyncio
async def test_mixed_batch_cancellation_hands_off_both_sources(
    tmp_path: Path,
) -> None:
    vault_path = tmp_path / "vault.json"
    code_path = tmp_path / "code.json"
    vault = _policy(vault_path, tmp_path, source=WatcherSource.VAULT)
    code = _policy(code_path, tmp_path)
    vault_ready = tmp_path / "mixed-vault-lock-ready.marker"
    code_ready = tmp_path / "mixed-code-lock-ready.marker"
    holders = [
        _spawn_state_lock_holder(
            vault_path.with_name(f"{vault_path.name}.lock"),
            vault_ready,
            hold_seconds=30.0,
        ),
        _spawn_state_lock_holder(
            code_path.with_name(f"{code_path.name}.lock"),
            code_ready,
            hold_seconds=30.0,
        ),
    ]
    try:
        for _ in range(100):
            if vault_ready.exists() and code_ready.exists():
                break
            await asyncio.sleep(0.02)
        assert vault_ready.exists()
        assert code_ready.exists()

        persistence = asyncio.create_task(
            _persist_observed_sources(
                vault_events_observed=True,
                code_events_observed=True,
                vault_retry=vault,
                code_retry=code,
                root_dir=tmp_path,
            )
        )
        await asyncio.sleep(0.05)
        started = asyncio.get_running_loop().time()
        persistence.cancel()
        assert await persistence is True

        assert asyncio.get_running_loop().time() - started < 8.0
        assert list(tmp_path.glob("vault.recovery.*.json"))
        assert list(tmp_path.glob("code.recovery.*.json"))
    finally:
        for holder in holders:
            if holder.poll() is None:
                holder.terminate()
                holder.wait(timeout=5.0)

    recovered_vault = _policy(vault_path, tmp_path, source=WatcherSource.VAULT)
    recovered_code = _policy(code_path, tmp_path)
    assert recovered_vault.state.convergence_pending
    assert recovered_vault.state.unscoped_required
    assert recovered_code.state.convergence_pending
    assert recovered_code.state.unscoped_required


@pytest.mark.asyncio
async def test_cancellation_hands_off_after_indefinite_lock_contention(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    ready_path = tmp_path / "recovery-lock-ready.marker"
    holder = _spawn_state_lock_holder(
        lock_path,
        ready_path,
        hold_seconds=30.0,
    )
    try:
        for _ in range(100):
            if ready_path.exists():
                break
            await asyncio.sleep(0.02)
        assert ready_path.exists()

        refresh = asyncio.create_task(
            _run_durable_retry_transaction(
                policy.refresh,
                source=WatcherSource.CODE,
                root_dir=tmp_path,
                action="refresh",
                cancellation_fallback=policy.write_recovery_marker,
            )
        )
        await asyncio.sleep(0.05)
        started = asyncio.get_running_loop().time()
        refresh.cancel()
        with pytest.raises(asyncio.CancelledError):
            await refresh
        elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < 8.0
        assert list(tmp_path.glob("code.recovery.*.json"))
    finally:
        if holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=5.0)

    recovered = _policy(state_path, tmp_path)
    assert recovered.state.convergence_pending
    assert recovered.state.unscoped_required
