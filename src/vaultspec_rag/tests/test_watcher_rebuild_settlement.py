"""Exact scope and execution ownership survive certified rebuild settlement."""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import replace
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from .._job_errors import JobError, JobErrorKind
from ..watcher_retry import (
    WatcherCircuitState,
    WatcherScopeRefusal,
    WatcherSource,
    read_state,
    write_state,
)
from ..watcher_retry_policy import _ADMISSION_RESERVATIONS, WatcherRetryPolicy
from ..watcher_runtime import reconcile_completed_rebuild
from .test_watcher_rebuild_reconciliation import (
    _observe,
    _published_rebuild,
    _refused_policy,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ..watcher_retry import WatcherRetryState

pytestmark = pytest.mark.unit


def _persist_exited_owner_attempt(
    root: Path,
    source: WatcherSource,
    job_id: str | None,
    *,
    exact: bool = True,
) -> WatcherRetryState:
    """Persist exact fencing under a real process that exits before recovery."""
    from ..config._settings import get_config

    child = dedent(
        """\
        import sys
        from dataclasses import replace
        from pathlib import Path
        from vaultspec_rag._job_errors import JobErrorKind
        from vaultspec_rag.watcher_retry import (
            WatcherCircuitState, WatcherPathEvent, WatcherPathObservation,
            WatcherScopeRefusal, WatcherSource, write_state,
        )
        from vaultspec_rag.watcher_retry_policy import WatcherRetryPolicy

        source = WatcherSource(sys.argv[2])
        policy = WatcherRetryPolicy.for_root(Path(sys.argv[1]), source, now=1.0)
        def observe(path, now):
            return WatcherPathObservation(
                path, source, now, now,
                frozenset({WatcherPathEvent.MODIFIED}), 1,
            )
        policy.mark_scope_pending((observe('src/captured.py', 1.0),), now=1.0)
        decision = policy.admit_reserved(
            policy.reserve_admission(), job_id=sys.argv[3] or None, now=2.0,
        )
        assert decision.admitted
        policy.mark_scope_pending((observe('src/later.py', 12.0),), now=12.0)
        if sys.argv[4] == 'unknown':
            write_state(policy._path, replace(
                policy.state, pending_paths=(), captured_paths=(),
                scope_refusal=WatcherScopeRefusal.FULL_REINDEX_REQUIRED,
                last_error_kind=JobErrorKind.FULL_REINDEX_REQUIRED,
                last_failure_at=3.0, updated_at=4.0,
                circuit_state=WatcherCircuitState.OPEN,
            ))
        """
    )
    subprocess.run(
        [
            sys.executable,
            "-c",
            child,
            str(root),
            source.value,
            job_id or "",
            "exact" if exact else "unknown",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=20.0,
    )
    cfg = get_config()
    return read_state(
        root / cfg.data_dir / "watcher-retry" / f"{source.value}.json",
        scope_max_paths=cfg.watch_scope_max_paths,
        scope_max_bytes=cfg.watch_scope_max_bytes,
    )


@pytest.mark.parametrize(
    "outcome", ["success", "interrupted", "failed", "requires-full"]
)
@pytest.mark.parametrize("later_paths", [False, True])
def test_scoped_outcomes_preserve_other_unknown_marker_intent(
    tmp_path: Path, outcome: str, later_paths: bool
) -> None:
    policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
    _observe(policy, "src/captured.py")
    admitted = policy.admit_reserved(policy.reserve_admission(), job_id="watcher")
    assert admitted.attempt_generation is not None
    token = policy.state.attempt_token
    marker_owner = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
    marker_owner.write_recovery_marker()
    unknown = policy.refresh()
    if later_paths:
        _observe(policy, "src/later.py")
    assert unknown.unscoped_required
    assert unknown.attempt_token == token

    if outcome == "success":
        settled = policy.record_success(admitted.attempt_generation)
    elif outcome == "interrupted":
        settled = policy.record_interrupted(admitted.attempt_generation)
    else:
        error = (
            JobError(JobErrorKind.FULL_REINDEX_REQUIRED, "source run unpublished")
            if outcome == "requires-full"
            else TimeoutError("source run failed")
        )
        settled = policy.record_failure(error, admitted.attempt_generation)

    # Mutation: scoped settlement cannot consume unknown observations.
    assert settled.unscoped_required
    assert settled.convergence_pending
    assert settled.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    assert settled.last_failure_at == unknown.last_failure_at
    assert settled.last_error_detail == unknown.last_error_detail
    assert settled.circuit_state is WatcherCircuitState.OPEN
    expected = (["src/captured.py"] if outcome != "success" else []) + (
        ["src/later.py"] if later_paths else []
    )
    assert [item.relative_path for item in settled.pending_paths] == expected
    assert settled.captured_paths == ()
    assert settled.attempt_job_id is None
    assert token not in _ADMISSION_RESERVATIONS


def test_own_marker_restores_scope_before_releasing_its_job_fence(
    tmp_path: Path,
) -> None:
    policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
    _observe(policy, "src/captured.py")
    admitted = policy.admit_reserved(policy.reserve_admission(), job_id="watcher")
    assert admitted.attempt_generation is not None
    token = policy.state.attempt_token
    _observe(policy, "src/later.py")
    marker = policy.write_recovery_marker()

    restored = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)

    # Mutation: clearing ownership without restoring captured paths loses scope.
    assert [item.relative_path for item in restored.state.pending_paths] == [
        "src/captured.py",
        "src/later.py",
    ]
    assert not restored.state.captured_paths
    assert restored.state.attempt_job_id is None
    assert restored.state.attempt_token is None
    assert restored.state.unscoped_required
    assert token not in _ADMISSION_RESERVATIONS
    assert not marker.exists()


@pytest.mark.parametrize("later_paths", [False, True])
def test_certified_rebuild_preserves_a_live_captured_attempt(
    tmp_path: Path, later_paths: bool
) -> None:
    policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
    _observe(policy, "src/captured.py")
    admitted = policy.admit_reserved(policy.reserve_admission(), job_id="watcher")
    assert admitted.attempt_generation is not None
    now = time.time()
    write_state(
        policy._path,
        replace(
            policy.state,
            scope_refusal=WatcherScopeRefusal.FULL_REINDEX_REQUIRED,
            last_error_kind=JobErrorKind.FULL_REINDEX_REQUIRED,
            last_error_detail="old publication refused",
            last_failure_at=now,
            circuit_state=WatcherCircuitState.OPEN,
            updated_at=now,
        ),
    )
    rebuilt = _published_rebuild(tmp_path, WatcherSource.CODE)
    if later_paths:
        _observe(policy, "src/later.py")
    before = policy.refresh()

    assert reconcile_completed_rebuild(rebuilt)
    settled = policy.refresh()

    # Mutation: rebuild settlement cannot steal the current attempt's fence.
    assert settled.attempt_token == before.attempt_token
    assert settled.attempt_generation == before.attempt_generation
    assert settled.attempt_job_id == before.attempt_job_id
    assert settled.attempt_owner_pid == before.attempt_owner_pid
    assert settled.attempt_owner_create_time == before.attempt_owner_create_time
    assert settled.captured_paths == before.captured_paths
    assert settled.pending_paths == before.pending_paths
    assert settled.scope_refusal is None
    assert settled.convergence_pending
    assert policy._owned_admission_token() == before.attempt_token
    ordinary = policy.record_success(admitted.attempt_generation)
    assert ordinary.convergence_pending is later_paths


@pytest.mark.parametrize("later_paths", [False, True])
def test_new_unknown_marker_cannot_be_covered_by_an_older_rebuild(
    tmp_path: Path, later_paths: bool
) -> None:
    policy = _refused_policy(tmp_path, WatcherSource.CODE)
    rebuilt = _published_rebuild(tmp_path, WatcherSource.CODE)
    marker_owner = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
    marker_owner.write_recovery_marker()
    refused = policy.refresh()
    if later_paths:
        _observe(policy, "src/later.py")

    # Mutation: exact paths cannot hide the newer unknown handoff.
    assert not reconcile_completed_rebuild(rebuilt)
    assert policy.refresh().unscoped_required
    assert policy.state.last_failure_at == refused.last_failure_at
    assert policy.state.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    fresh = _published_rebuild(tmp_path, WatcherSource.CODE)
    assert reconcile_completed_rebuild(fresh)
    assert not policy.refresh().unscoped_required
    assert policy.state.pending_paths


@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.parametrize("later", [False, True])
def test_unknown_scope_uses_its_latest_observation_cutoff(
    tmp_path: Path, unknown: bool, later: bool
) -> None:
    policy = _refused_policy(tmp_path, WatcherSource.CODE)
    rebuilt = _published_rebuild(tmp_path, WatcherSource.CODE)
    started = rebuilt.timestamps.started_at
    assert started is not None
    observed_at = started + (1.0 if later else -1.0)
    write_state(
        policy._path,
        replace(
            policy.state,
            convergence_pending=True,
            pending_paths=(),
            unscoped_required=unknown,
            updated_at=observed_at,
        ),
    )

    # Mutation: omitting the unknown-scope observation cutoff erases newer intent.
    assert reconcile_completed_rebuild(rebuilt) is not later
    if later:
        assert policy.refresh().scope_refusal is not None


@pytest.mark.parametrize("exact", [False, True])
@pytest.mark.parametrize("recover_before_rebuild", [False, True])
def test_certified_rebuild_covers_dead_legacy_fencing_without_restamping(
    tmp_path: Path, exact: bool, recover_before_rebuild: bool
) -> None:
    before = _persist_exited_owner_attempt(
        tmp_path, WatcherSource.CODE, None, exact=exact
    )
    unowned = WatcherRetryPolicy.for_root(
        tmp_path, WatcherSource.CODE, recover_abandoned_attempt=False
    )
    write_state(
        unowned._path,
        replace(
            before,
            scope_refusal=WatcherScopeRefusal.FULL_REINDEX_REQUIRED,
            last_error_kind=JobErrorKind.FULL_REINDEX_REQUIRED,
            last_failure_at=3.0,
            circuit_state=WatcherCircuitState.OPEN,
        ),
    )
    if recover_before_rebuild:
        recovered = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
        assert recovered.state.updated_at == before.updated_at
    rebuilt = _published_rebuild(tmp_path)

    # Mutation: adopting or restamping old dead fencing strands a covering rebuild.
    assert reconcile_completed_rebuild(rebuilt)
    settled = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE).state
    assert settled.attempt_generation is None
    assert settled.attempt_token is None
    assert settled.scope_refusal is None
    assert settled.last_error_kind is None
    assert settled.convergence_pending is exact
    assert [item.relative_path for item in settled.pending_paths] == (
        ["src/captured.py", "src/later.py"] if exact else []
    )


@pytest.mark.parametrize("outcome", ["success", "interrupted", "failed"])
def test_historical_settlement_retains_newer_observation_time(
    tmp_path: Path, outcome: str
) -> None:
    from .test_watcher_retry import _path_observation

    policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE, now=1.0)
    policy.mark_scope_pending(
        (_path_observation("src/captured.py", first=1.0, latest=1.0),), now=1.0
    )
    admitted = policy.admit_reserved(
        policy.reserve_admission(), job_id="watcher", now=1.0
    )
    assert admitted.attempt_generation is not None
    policy.mark_scope_pending(
        (_path_observation("src/newer.py", first=3.0, latest=3.0),), now=3.0
    )
    if outcome == "success":
        settled = policy.record_success(admitted.attempt_generation, now=2.0)
    elif outcome == "interrupted":
        settled = policy.record_interrupted(admitted.attempt_generation, now=2.0)
    else:
        settled = policy.record_failure(
            TimeoutError("old attempt timeout"), admitted.attempt_generation, now=2.0
        )

    # Mutation: historical terminal timing cannot overwrite a newer observation.
    assert settled.updated_at == 3.0
    assert "src/newer.py" in {item.relative_path for item in settled.pending_paths}
