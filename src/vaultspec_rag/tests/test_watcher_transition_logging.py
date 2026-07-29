"""A watcher job state transition must be reported as what it actually is.

``_log_managed_transition`` dispatches on the observed job state. Its failure
branch was the fallthrough, so every state without an explicit case landed
there - including ``QUEUED`` and ``RUNNING``, which are progress. A healthy
run therefore logged ``reindex_failed`` at ERROR about a second after it
started, then went on to succeed. The cost is not cosmetic: an error line per
healthy run is what makes a real failure unfindable.

These bind every member of the state enum to the event it should produce, so
a state added later cannot silently inherit the failure branch again.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from ..job_models import (
    DesiredJobState,
    JobAttempt,
    JobCapabilities,
    JobInitiator,
    JobMode,
    JobOperation,
    JobResourceSnapshot,
    JobRuntimeSnapshot,
    JobSnapshot,
    JobSource,
    JobSpec,
    JobState,
    JobTimestamps,
)
from ..service import ServiceRegistry
from ..watcher_retry import WatcherRetryPolicy, WatcherSource, _WatcherRetryOptions
from ..watcher_runtime import (
    WatcherConvergenceSlot,
    _log_managed_transition,
    _TransitionLogContext,
)

pytestmark = [pytest.mark.unit]

#: Every state that is not an outcome. Reporting any of these as a failure is
#: the defect these tests exist for.
_NON_TERMINAL = (
    JobState.QUEUED,
    JobState.RUNNING,
    JobState.PAUSING,
    JobState.CANCELLING,
)

#: The only states that genuinely mean the run did not deliver.
_FAILED = (JobState.FAILED, JobState.INTERRUPTED)


def _snapshot(state: JobState) -> JobSnapshot:
    root = Path("/tmp/root")
    return JobSnapshot(
        id="job-1",
        revision=1,
        spec=JobSpec(
            operation=JobOperation.INDEX,
            source=JobSource.CODE,
            project_root=str(root),
            mode=JobMode.INCREMENTAL,
        ),
        state=state,
        desired_state=DesiredJobState.RUNNING,
        capabilities=JobCapabilities(
            pausable=False,
            resumable=False,
            cancellable=False,
            retryable=False,
            deletable=False,
        ),
        attempt=JobAttempt(number=1),
        timestamps=JobTimestamps(created_at=0.0, state_changed_at=0.0),
        progress=None,
        result=None,
        error_kind=None,
        initiator=JobInitiator(
            kind="watcher",
            command="watcher_code_index",
            project_root=str(root),
        ),
        runtime=JobRuntimeSnapshot(
            pid=1,
            parent_pid=0,
            user="u",
            executable="python",
            prefix="p",
            base_prefix="p",
            virtual_env=None,
        ),
        resources=JobResourceSnapshot(started=None, finished=None),
    )


def _events(caplog: pytest.LogCaptureFixture) -> list[tuple[str, int]]:
    """Return ``(event name, level)`` per record.

    ``log_event`` renders ``namespace event=name key=value`` into the message
    rather than attaching an attribute, so the name is read back out of the
    rendered line - the same way any log consumer would.
    """
    events: list[tuple[str, int]] = []
    for record in caplog.records:
        match = re.search(r"\bevent=(\S+)", record.getMessage())
        if match is not None:
            events.append((match.group(1), record.levelno))
    return events


def _log(
    state: JobState,
    caplog: pytest.LogCaptureFixture,
) -> list[tuple[str, int]]:
    root = Path("/tmp/root")
    slot = WatcherConvergenceSlot(
        source=JobSource.CODE,
        root=root,
        registry=ServiceRegistry(),
        retry_policy=WatcherRetryPolicy(
            root,
            _WatcherRetryOptions(
                canonical_root=str(root),
                source=WatcherSource.CODE,
                base_seconds=1.0,
                max_seconds=2.0,
                jitter_fraction=0.0,
                failure_threshold=3,
            ),
        ),
    )
    caplog.clear()
    # Raise the level on the logger that actually emits. The module logs through
    # ``getLogger(__name__)``, so its name IS the defining module - taking it
    # from the function keeps this correct if the module is ever renamed. A
    # hard-coded sibling name silently raises nothing, leaving capture at the
    # mercy of whatever level an earlier test in the same process left behind.
    with caplog.at_level(logging.DEBUG, logger=_log_managed_transition.__module__):
        _log_managed_transition(
            slot,
            _snapshot(state),
            _TransitionLogContext(
                watcher_owned=True,
                pending_count=0,
                replacement_delay=0.0,
                error=None,
            ),
        )
    return _events(caplog)


@pytest.mark.parametrize("state", _NON_TERMINAL)
def test_a_non_terminal_transition_is_never_reported_as_a_failure(
    state: JobState,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Progress must not be logged as an error, at any severity."""
    events = _log(state, caplog)
    assert events, f"{state.value} produced no event at all"
    for name, level in events:
        assert name != "reindex_failed", (
            f"{state.value} was reported as a failure; it is progress"
        )
        assert level < logging.ERROR, (
            f"{state.value} logged at {logging.getLevelName(level)}"
        )


@pytest.mark.parametrize("state", _FAILED)
def test_a_failed_terminal_state_is_still_reported_as_a_failure(
    state: JobState,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The fix must not silence the outcomes the branch exists to report."""
    events = _log(state, caplog)
    assert ("reindex_failed", logging.ERROR) in events, (
        f"{state.value} must still surface as an error, got {events}"
    )


@pytest.mark.parametrize("state", _FAILED)
def test_a_failure_event_always_carries_a_populated_error(
    state: JobState,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``reindex_failed`` must never fire with a null error again.

    The snapshot here carries no result and no exception - the exact shape
    that used to render ``error=null``, an error event naming neither cause
    nor remediation on the one channel operators grep for real failures.

    Mutation check: restoring the bare ``context.error or snapshot.result``
    fallback (dropping the explicit no-recorded-error text) makes this fail
    on the ``error=null`` assertion below, not on collection.
    """
    _log(state, caplog)
    failed_lines = [
        record.getMessage()
        for record in caplog.records
        if "event=reindex_failed" in record.getMessage()
    ]
    assert failed_lines, f"{state.value} produced no reindex_failed event"
    for line in failed_lines:
        assert "error=null" not in line, f"null error published: {line}"
        assert re.search(r"\berror=\S", line), f"no error field at all: {line}"


def test_supersession_is_its_own_outcome_at_ordinary_severity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A coalesced-away job reports supersession, not failure and not progress.

    Three claims the broader state sweep cannot make: the event fires at all
    (a silently dropped outcome hides that coalescing happened), it is named
    distinctly, and it is not filed under the progress event - which would
    report a terminal state as an ongoing one.

    Mutation check: routing supersession into the progress branch (deleting
    its case) fails on the event-name assertion below, and dropping the
    branch's ``log_event`` call entirely fails on the emptiness assertion,
    neither on collection.
    """
    events = _log(JobState.SUPERSEDED, caplog)
    assert events, "supersession produced no event at all"
    assert events == [("reindex_superseded", logging.INFO)], (
        f"supersession must report itself once, at INFO; got {events}"
    )


def test_every_job_state_has_an_explicit_outcome(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No state may reach the failure branch by fallthrough.

    This is the regression itself: the branch was a catch-all, so any state
    the dispatch did not name was reported as a failure. A state added to the
    enum later must be classified deliberately, not inherit that default.
    """
    reported_failed = {
        state
        for state in JobState
        if any(name == "reindex_failed" for name, _ in _log(state, caplog))
    }
    assert reported_failed == set(_FAILED), (
        "states reaching the failure branch: "
        f"{sorted(s.value for s in reported_failed)}"
    )
