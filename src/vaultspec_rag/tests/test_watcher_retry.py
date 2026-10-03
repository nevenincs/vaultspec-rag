"""Durable watcher retry, circuit, and convergence-generation tests."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from .._job_errors import JobError, JobErrorKind, classify_error_text
from .._publication_state import acquire_publication_snapshot
from .._source_types import PublicSourceType
from ..indexer._publication_proof import ProofMissingError
from ..watcher_durability import (
    _STATE_TRANSACTION_WORKER_SLOTS,
    run_durable_retry_transaction,
)
from ..watcher_retry import (
    WatcherCircuitState,
    WatcherPathEvent,
    WatcherPathObservation,
    WatcherRetryState,
    WatcherRetryStateError,
    WatcherScopeRefusal,
    WatcherSource,
)
from ..watcher_retry_policy import (
    WatcherRetryPolicy,
    _WatcherRetryOptions,
)
from ._child_signal import (
    CHILD_PROCESS_TIMEOUT_SECONDS,
    PROCESS_TIMEOUT_SECONDS,
    await_marker,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


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
        _WatcherRetryOptions(
            canonical_root=os.path.normcase(str(root.resolve())),
            source=source,
            base_seconds=10.0,
            max_seconds=25.0,
            jitter_fraction=jitter_fraction,
            failure_threshold=3,
            now=now,
        ),
    )


def _path_observation(
    path: str,
    *,
    generation: int = 1,
    first: float = 1.0,
    latest: float = 2.0,
    source: WatcherSource = WatcherSource.CODE,
) -> WatcherPathObservation:
    return WatcherPathObservation(
        relative_path=path,
        source=source,
        first_observed_at=first,
        latest_observed_at=latest,
        event_kinds=frozenset({WatcherPathEvent.MODIFIED}),
        generation=generation,
    )


def _mark_scope(
    policy: WatcherRetryPolicy,
    *,
    now: float,
    path: str = "src/a.py",
    source: WatcherSource = WatcherSource.CODE,
) -> WatcherRetryState:
    """Stage one pending generation the way the watcher intake stages it."""
    return policy.mark_scope_pending(
        (_path_observation(path, first=now, latest=now, source=source),), now=now
    )


def test_exact_scope_round_trips_and_merges_path_evidence(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "code.json"
    policy = _policy(state_path, tmp_path)
    policy.mark_scope_pending((_path_observation("src/b.py"),), now=2.0)
    merged = policy.mark_scope_pending(
        (
            WatcherPathObservation(
                relative_path="src/b.py",
                source=WatcherSource.CODE,
                first_observed_at=3.0,
                latest_observed_at=4.0,
                event_kinds=frozenset({WatcherPathEvent.DELETED}),
                generation=2,
            ),
            _path_observation("src/a.py", generation=2),
        ),
        now=4.0,
    )

    assert [item.relative_path for item in merged.pending_paths] == [
        "src/a.py",
        "src/b.py",
    ]
    assert merged.pending_paths[1].first_observed_at == 1.0
    assert merged.pending_paths[1].event_kinds == {
        WatcherPathEvent.MODIFIED,
        WatcherPathEvent.DELETED,
    }
    restarted = _policy(state_path, tmp_path, now=5.0)
    assert restarted.state.pending_paths == merged.pending_paths
    assert restarted.state.scope_refusal is None
    assert restarted.state.last_error_kind is None


def test_scope_count_overflow_refuses_without_truncating_last_complete_scope(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state" / "code.json"
    policy = WatcherRetryPolicy(
        state_path,
        _WatcherRetryOptions(
            canonical_root=os.path.normcase(str(tmp_path.resolve())),
            source=WatcherSource.CODE,
            base_seconds=10.0,
            max_seconds=25.0,
            jitter_fraction=0.0,
            failure_threshold=3,
            scope_max_paths=1,
            now=0.0,
        ),
    )
    accepted = policy.mark_scope_pending((_path_observation("src/a.py"),), now=1.0)

    refused = policy.mark_scope_pending((_path_observation("src/b.py"),), now=2.0)

    assert refused.scope_refusal is WatcherScopeRefusal.SCOPE_CAPACITY_EXCEEDED
    assert refused.pending_paths == accepted.pending_paths
    assert refused.convergence_generation == accepted.convergence_generation
    assert refused.circuit_state is WatcherCircuitState.OPEN


def test_scope_byte_overflow_refuses_without_persisting_partial_scope(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state" / "code.json"
    policy = WatcherRetryPolicy(
        state_path,
        _WatcherRetryOptions(
            canonical_root=os.path.normcase(str(tmp_path.resolve())),
            source=WatcherSource.CODE,
            base_seconds=10.0,
            max_seconds=25.0,
            jitter_fraction=0.0,
            failure_threshold=3,
            scope_max_bytes=2048,
            now=0.0,
        ),
    )

    refused = policy.mark_scope_pending(
        (_path_observation(f"src/{'a' * 1500}.py"),),
        now=1.0,
    )

    assert refused.scope_refusal is WatcherScopeRefusal.SCOPE_CAPACITY_EXCEEDED
    assert refused.pending_paths == ()
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["pending_paths"] == []


@pytest.mark.parametrize(
    "observation",
    [
        _path_observation("../escape.py"),
        WatcherPathObservation(
            relative_path="src/file.py",
            source=WatcherSource.VAULT,
            first_observed_at=1.0,
            latest_observed_at=2.0,
            event_kinds=frozenset({WatcherPathEvent.MODIFIED}),
            generation=1,
        ),
    ],
)
def test_invalid_or_foreign_scope_fails_closed(
    tmp_path: Path,
    observation: WatcherPathObservation,
) -> None:
    policy = _policy(tmp_path / "state" / "code.json", tmp_path)

    with pytest.raises(ValueError, match="scope_state_invalid"):
        policy.mark_scope_pending((observation,), now=1.0)

    assert not policy.state.convergence_pending


def _seed_pending_state_without_exact_scope(state_path: Path, root: Path) -> None:
    """Persist the pending intent an older release wrote with no path evidence.

    That schema carried no path fields at all, so a state file left by one is
    the only way a pending generation arrives with nothing to scope it.
    """
    _policy(state_path, root)
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["schema_version"] = 2
    payload["convergence_pending"] = True
    for field in (
        "pending_paths",
        "captured_paths",
        "scope_max_paths",
        "scope_max_bytes",
        "scope_refusal",
        "attempt_job_id",
    ):
        payload.pop(field)
    state_path.write_text(json.dumps(payload), encoding="utf-8")


def test_schema_two_pending_intent_migrates_to_typed_rebuild_refusal(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state" / "code.json"
    _seed_pending_state_without_exact_scope(state_path, tmp_path)

    migrated = _policy(state_path, tmp_path, now=3.0)

    assert migrated.state.schema_version == 3
    assert migrated.state.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    assert migrated.state.circuit_state is WatcherCircuitState.OPEN


#: A hold long enough that the lock is only ever freed by the test releasing
#: the holder. A test that needs the lock held "until I say so" says so with
#: this, rather than picking a span and hoping the events it brackets land
#: inside it.
_LOCK_HELD_UNTIL_RELEASED = 30.0

#: What a holder publishes once it owns the lock. Read back and compared
#: rather than merely detected, so a marker that appears without its content
#: cannot pass for readiness.
_LOCK_HELD_MARKER = "held"


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
            "from vaultspec_rag.tests._child_signal import publish_marker",
            "lock = FileLock(Path(sys.argv[1]))",
            "assert lock.acquire()",
            f"publish_marker(sys.argv[2], {_LOCK_HELD_MARKER!r})",
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


async def _await_lock_held(
    holder: subprocess.Popen[str],
    ready_path: Path,
) -> None:
    """Block until *holder* reports that it owns the state lock.

    The bound is the spawned-child one and not an in-process one, because
    that is what this wait covers: the holder has to be scheduled, start an
    interpreter and import this package before it can take a lock at all.
    Polling a hand-rolled span instead gave these waits 2.0s, which is
    comfortable on an idle machine and far under the cost of a spawn on a
    machine running the rest of the suite beside it - so a holder that was
    merely slow to start read as a watcher that never handed off.
    """
    reported = await asyncio.to_thread(
        await_marker, ready_path, holder, timeout=CHILD_PROCESS_TIMEOUT_SECONDS
    )
    assert reported == _LOCK_HELD_MARKER, (
        f"the state lock holder never took {ready_path.name}: "
        f"reported {reported!r}, exit status {holder.returncode}"
    )


def test_newer_convergence_generation_survives_older_success(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "code.json"
    first = _policy(state_path, tmp_path)
    second = _policy(state_path, tmp_path)

    dirty = first.mark_scope_pending((_path_observation("src/a.py"),), now=1.0)
    assert dirty.convergence_generation == 1
    admitted = first.admit(now=1.0)
    assert admitted.admitted
    assert admitted.attempt_generation == 1

    newer = second.mark_scope_pending((_path_observation("src/b.py"),), now=2.0)
    assert newer.convergence_generation == 2
    completed = first.record_success(1, now=3.0)
    assert completed.last_durable_progress_at == 3.0
    assert completed.convergence_pending

    next_attempt = second.admit(now=3.0)
    assert next_attempt.admitted
    assert next_attempt.attempt_generation == 2
    assert not next_attempt.requires_unscoped
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
    _mark_scope(policy, now=0.0)
    _fail_once(policy, TimeoutError("t"), now=0.0, random_unit=0.5)
    _fail_once(policy, ConnectionError("c"), now=11.0, random_unit=1.0)
    _fail_once(policy, TimeoutError("t"), now=35.0, random_unit=0.5)


def test_retry_backoff_grows_and_gates_admission(tmp_path: Path) -> None:
    policy = _policy(tmp_path / "code.json", tmp_path)
    _mark_scope(policy, now=0.0)

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
    _mark_scope(policy, now=0.0)
    _fail_once(policy, TimeoutError("t"), now=1.0, random_unit=0.5)
    _fail_once(policy, ConnectionError("c"), now=11.0, random_unit=1.0)

    state = _fail_once(policy, TimeoutError("timeout"), now=35.0, random_unit=0.5)

    assert state.next_retry_at == 60.0
    assert state.circuit_state is WatcherCircuitState.OPEN
    assert not policy.admit(now=59.9).admitted


def test_full_reindex_required_is_terminal_and_clears_pending_intent(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path / "code.json", tmp_path)
    _mark_scope(policy, now=0.0)

    state = _fail_once(
        policy,
        JobError(JobErrorKind.FULL_REINDEX_REQUIRED, "explicit consent required"),
        now=1.0,
        random_unit=0.5,
    )

    assert state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert state.circuit_state is WatcherCircuitState.OPEN
    assert not state.convergence_pending
    assert not policy.admit(now=1000.0).admitted

    renewed = _mark_scope(policy, now=1001.0, path="src/b.py")
    assert renewed.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert renewed.circuit_state is WatcherCircuitState.OPEN
    assert not policy.admit(now=1001.0).admitted


@pytest.mark.parametrize("restart", [False, True])
def test_exact_events_preserve_terminal_rebuild_refusal(
    tmp_path: Path, restart: bool
) -> None:
    # Mutation: resetting failure fields in mark_scope_pending admits the new
    # event even though the publication still requires an explicit rebuild.
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    policy.mark_scope_pending((_path_observation("src/a.py"),), now=2.0)
    failed = _fail_once(
        policy,
        JobError(JobErrorKind.FULL_REINDEX_REQUIRED, "membership proof changed"),
        now=3.0,
        random_unit=0.5,
    )
    if restart:
        policy = _policy(state_path, tmp_path, now=4.0)

    observed = policy.mark_scope_pending(
        (_path_observation("src/b.py", first=4.0, latest=4.0),), now=4.0
    )

    assert observed.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    assert observed.last_error_kind is failed.last_error_kind
    assert observed.last_error_detail == failed.last_error_detail
    assert observed.consecutive_failures == failed.consecutive_failures
    assert observed.circuit_state is WatcherCircuitState.OPEN
    assert observed.next_retry_at == 0.0
    assert [item.relative_path for item in observed.pending_paths] == ["src/b.py"]
    assert not policy.admit(now=1000.0).admitted


def test_exact_events_preserve_failure_backoff_and_circuit(tmp_path: Path) -> None:
    # Mutation: clearing retry history on intake admits before the backoff and
    # prevents repeated transient failures from ever opening the circuit.
    policy = _policy(tmp_path / "code.json", tmp_path)
    policy.mark_scope_pending((_path_observation("src/a.py"),), now=2.0)
    failed = _fail_once(policy, TimeoutError("timeout"), now=3.0, random_unit=0.5)

    observed = policy.mark_scope_pending(
        (_path_observation("src/b.py", first=4.0, latest=4.0),), now=4.0
    )

    assert not policy.admit(now=4.0).admitted
    assert observed.next_retry_at == failed.next_retry_at
    assert observed.consecutive_failures == 1
    assert [item.relative_path for item in observed.pending_paths] == [
        "src/a.py",
        "src/b.py",
    ]
    _fail_once(policy, TimeoutError("timeout"), now=13.0, random_unit=0.5)
    failed = _fail_once(policy, TimeoutError("timeout"), now=33.0, random_unit=0.5)
    observed = policy.mark_scope_pending(
        (_path_observation("src/c.py", first=34.0, latest=34.0),), now=34.0
    )
    assert observed.circuit_state is WatcherCircuitState.OPEN
    assert observed.consecutive_failures == 3
    assert observed.next_retry_at == failed.next_retry_at
    assert not policy.admit(now=34.0).admitted


def test_exact_event_cannot_replace_unknown_scope_from_an_older_release(
    tmp_path: Path,
) -> None:
    # Mutation: clearing the migrated refusal on an exact event loses the older
    # unknown scope while admitting only the newest path.
    state_path = tmp_path / "state" / "code.json"
    _seed_pending_state_without_exact_scope(state_path, tmp_path)
    restarted = _policy(state_path, tmp_path, now=1.0)

    observed = restarted.mark_scope_pending((_path_observation("src/new.py"),), now=2.0)

    assert observed.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    assert not restarted.admit(now=1000.0).admitted


def test_missing_publication_proof_is_a_terminal_rebuild_refusal(
    tmp_path: Path,
) -> None:
    # A watched root that was never built has no committed proof. Its
    # incremental run raises the proof error, not a JobError, and classifying
    # that as ``other`` resubmitted the same doomed incremental on every change
    # instead of refusing with the rebuild remedy. Mutation: dropping the
    # rebuild phrase from the classifier fails both kind assertions.
    with pytest.raises(ProofMissingError) as missing:
        acquire_publication_snapshot(tmp_path / "never-built", PublicSourceType.VAULT)
    assert classify_error_text(str(missing.value)) is JobErrorKind.FULL_REINDEX_REQUIRED

    policy = _policy(tmp_path / "vault.json", tmp_path, source=WatcherSource.VAULT)
    _mark_scope(policy, now=0.0, source=WatcherSource.VAULT)
    state = _fail_once(policy, missing.value, now=1.0, random_unit=0.5)

    assert state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert state.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    assert not state.convergence_pending
    assert state.pending_paths == ()


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
    _mark_scope(policy, now=0.0)
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


def test_restart_refuses_unsettled_attempt_until_explicit_rebuild(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "code.json"
    script = "\n".join(
        (
            "import os, sys",
            "from pathlib import Path",
            (
                "from vaultspec_rag.watcher_retry import "
                "WatcherPathEvent, WatcherPathObservation, WatcherSource"
            ),
            (
                "from vaultspec_rag.watcher_retry_policy import "
                "WatcherRetryPolicy, _WatcherRetryOptions"
            ),
            "path, root = Path(sys.argv[1]), Path(sys.argv[2]).resolve()",
            (
                "policy = WatcherRetryPolicy(path, _WatcherRetryOptions("
                "canonical_root=os.path.normcase(str(root)), "
                "source=WatcherSource.CODE, base_seconds=10.0, "
                "max_seconds=25.0, jitter_fraction=0.0, "
                "failure_threshold=3, now=0.0))"
            ),
            (
                "policy.mark_scope_pending((WatcherPathObservation("
                "relative_path='src/a.py', source=WatcherSource.CODE, "
                "first_observed_at=0.0, latest_observed_at=0.0, "
                "event_kinds=frozenset({WatcherPathEvent.MODIFIED}), "
                "generation=1),), now=0.0)"
            ),
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
    assert state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert state.circuit_state is WatcherCircuitState.OPEN
    assert state.next_retry_at == 0.0
    # The refusal must not post-date the evidence it rests on: the cutoff is
    # the start of the abandoned attempt, not the restart that found it.
    assert state.last_failure_at == 30.0
    assert state.attempt_generation is None
    assert not state.unscoped_required
    assert not restarted.admit(now=64.9).admitted
    refused = restarted.admit(now=65.0)
    assert not refused.admitted
    assert refused.circuit_state is WatcherCircuitState.OPEN


def test_live_attempt_owner_is_not_reclaimed(tmp_path: Path) -> None:
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    policy.mark_scope_pending((_path_observation("src/a.py"),), now=0.0)
    decision = policy.admit_reserved(
        policy.reserve_admission(), now=0.0, job_id="job-1"
    )
    assert decision.attempt_generation == 1

    overlapping = _policy(state_path, tmp_path, now=5.0)
    assert overlapping.state.attempt_generation == 1
    assert not overlapping.admit(now=100.0).admitted

    settled = policy.record_success(1, now=101.0)
    assert not settled.convergence_pending


async def _await_recovery_markers(root: Path, pattern: str) -> list[Path]:
    """Return the recovery markers matching *pattern*, waiting for them to land.

    The handoff writes its marker from the worker thread the cancellation
    abandoned - cancelling stops the awaiting, not the thread - so the write is
    asynchronous with respect to the cancel that triggered it. Sampling the
    directory the instant the cancel returns therefore races the write, which
    is what failed on CI as a bare ``assert []``.

    Bounded by the ceiling for a thread reaching a state. A handoff that never
    happens still fails here; only the instantaneous sampling is given up.

    Mutation: made ``_run_cancellation_fallback`` return False so no marker is
    ever written. All four callers fail, each naming the source whose handoff
    did not happen. Restored, 29 passed.
    """
    deadline = asyncio.get_running_loop().time() + PROCESS_TIMEOUT_SECONDS
    markers = list(root.glob(pattern))
    while not markers and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)
        markers = list(root.glob(pattern))
    return markers


def test_prestart_handoff_cancels_reserved_admission(tmp_path: Path) -> None:
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    _mark_scope(policy, now=0.0)
    attempt_token = policy.reserve_admission()
    assert attempt_token is not None

    marker = policy.write_recovery_marker()
    decision = policy.admit_reserved(attempt_token, now=1.0)

    assert not decision.admitted
    replacement = _policy(state_path, tmp_path, now=2.0)
    assert not marker.exists()
    assert replacement.state.attempt_generation is None
    assert replacement.state.convergence_pending
    assert not replacement.state.unscoped_required
    assert replacement.state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    next_attempt = replacement.admit(now=2.0)
    assert not next_attempt.admitted


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
            run_durable_retry_transaction(
                lambda: _mark_scope(policy, now=time.time()),
                source=WatcherSource.CODE,
                root_dir=tmp_path,
                action="mark_scope_pending",
                cancellation_fallback=policy.write_recovery_marker,
            )
        )
        await asyncio.sleep(0.05)
        started = asyncio.get_running_loop().time()
        persistence.cancel()
        with pytest.raises(asyncio.CancelledError):
            await persistence
        assert asyncio.get_running_loop().time() - started < 6.0
        written = await _await_recovery_markers(tmp_path, "code.recovery.*.json")
        assert written, "the cancelled persistence wrote no recovery marker"
    finally:
        for _ in range(acquired_slots):
            _STATE_TRANSACTION_WORKER_SLOTS.release()

    replacement = _policy(tmp_path / "code.json", tmp_path)
    assert replacement.state.convergence_pending
    assert not replacement.state.unscoped_required
    assert replacement.state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED


def test_interruption_retains_scoped_intent_across_instances(
    tmp_path: Path,
) -> None:
    """An interruption keeps the exact scope, for this instance and the next."""
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    _mark_scope(policy, now=0.0)
    attempt = policy.admit(now=0.0)
    assert attempt.attempt_generation is not None

    state = policy.record_interrupted(attempt.attempt_generation, now=1.0)
    assert state.attempt_generation is None
    assert state.consecutive_failures == 0
    assert state.convergence_pending
    assert not state.unscoped_required
    retry = policy.admit(now=1.0)
    assert retry.admitted
    assert not retry.requires_unscoped
    assert retry.attempt_generation is not None
    policy.record_interrupted(retry.attempt_generation, now=2.0)

    # The scope is durable, so a replacement instance inherits the exact paths
    # rather than losing them with the process that observed them.
    replacement = _policy(state_path, tmp_path, now=3.0)
    assert replacement.state.convergence_pending
    assert not replacement.state.unscoped_required
    assert replacement.state.last_error_kind is None
    assert [item.relative_path for item in replacement.state.pending_paths] == [
        "src/a.py"
    ]
    resumed = replacement.admit(now=3.0)
    assert resumed.admitted
    assert not resumed.requires_unscoped


def test_success_with_mid_attempt_event_stays_scoped(tmp_path: Path) -> None:
    """A generation marked mid-attempt by the same instance converges scoped."""
    policy = _policy(tmp_path / "code.json", tmp_path)
    _mark_scope(policy, now=0.0)
    attempt = policy.admit(now=0.0)
    assert attempt.attempt_generation == 1

    newer = _mark_scope(policy, now=1.0, path="src/b.py")
    assert newer.convergence_generation == 2
    settled = policy.record_success(1, now=2.0)
    assert settled.convergence_pending
    # The instance that marked generation 2 still holds its exact paths, so
    # the follow-up convergence must not be forced to a full-tree pass.
    assert not settled.unscoped_required
    follow_up = policy.admit(now=2.0)
    assert follow_up.admitted
    assert follow_up.attempt_generation == 2
    assert not follow_up.requires_unscoped


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
            _WatcherRetryOptions(
                canonical_root=os.path.normcase(str((tmp_path / "other").resolve())),
                source=WatcherSource.CODE,
                base_seconds=10.0,
                max_seconds=25.0,
                jitter_fraction=0.2,
                failure_threshold=3,
                now=1.0,
            ),
        )


@pytest.mark.asyncio
async def test_permanent_state_path_error_fails_without_retrying(
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("blocks retry state directory", encoding="utf-8")
    started = asyncio.get_running_loop().time()

    with pytest.raises(WatcherRetryStateError, match="prepare failed"):
        await run_durable_retry_transaction(
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
        await run_durable_retry_transaction(
            policy.refresh,
            source=WatcherSource.CODE,
            root_dir=tmp_path,
            action="refresh",
        )

    assert asyncio.get_running_loop().time() - started < 1.0


def test_recovery_marker_clears_claim_and_requires_explicit_rebuild(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    _mark_scope(policy, now=0.0)
    attempt = policy.admit(now=0.0)
    assert attempt.attempt_generation is not None
    marker = policy.write_recovery_marker()
    assert marker.exists()
    assert not list(tmp_path.glob(".code.recovery-write.*.tmp"))

    recovered = _policy(state_path, tmp_path, now=1.0)

    assert recovered.state.attempt_generation is None
    assert recovered.state.convergence_pending
    assert not recovered.state.unscoped_required
    assert recovered.state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert not marker.exists()
    next_attempt = recovered.admit(now=1.0)
    assert not next_attempt.admitted


def test_late_recovery_marker_preserves_newer_live_claim(tmp_path: Path) -> None:
    state_path = tmp_path / "code.json"
    retiring = _policy(state_path, tmp_path)
    _mark_scope(retiring, now=0.0)
    retiring_attempt = retiring.admit(now=0.0)
    assert retiring_attempt.attempt_generation is not None
    retiring.record_interrupted(retiring_attempt.attempt_generation, now=1.0)

    replacement = _policy(state_path, tmp_path, now=2.0)
    replacement_attempt = replacement.admit(now=2.0)
    assert replacement_attempt.admitted
    marker = retiring.write_recovery_marker()

    settled = _policy(state_path, tmp_path, now=3.0).state

    assert not marker.exists()
    # The marker fences the retired attempt, not the live one that replaced it.
    assert settled.attempt_generation == replacement_attempt.attempt_generation
    assert settled.convergence_pending
    assert not settled.unscoped_required
    assert settled.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert settled.convergence_generation > retiring_attempt.attempt_generation


def test_inactive_same_process_fence_is_consumed(tmp_path: Path) -> None:
    state_path = tmp_path / "code.json"
    policy = _policy(state_path, tmp_path)
    _mark_scope(policy, now=0.0)
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
    assert not replacement.state.unscoped_required
    assert replacement.state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED


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
        hold_seconds=_LOCK_HELD_UNTIL_RELEASED,
    )
    try:
        await _await_lock_held(holder, ready_path)

        refresh = asyncio.create_task(
            run_durable_retry_transaction(
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
        written = await _await_recovery_markers(tmp_path, "code.recovery.*.json")
        assert written, "the cancelled refresh wrote no recovery marker"
    finally:
        if holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=5.0)

    recovered = _policy(state_path, tmp_path)
    assert recovered.state.convergence_pending
    assert not recovered.state.unscoped_required
    assert recovered.state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
