"""The service owns one wait verdict, and every reader of it agrees.

A running job waits on ``admission`` while its attempt is a registered limiter
waiter, or on ``writer`` while its progress step is ``queued``. These cover the
projection: the verdict, the admission stamp, the phase, the ``waiting`` filter,
the summary counts and the request bounds of the wait route.

MUTATION PROOF, each run in one uninterrupted sequence:

- Reversing the precedence in ``job_wait_reason`` (checking the writer step
  before the admission slot) fails
  ``test_admission_takes_precedence_over_the_writer`` on its ``"admission"``
  assertion.
- Dropping the ``min(timeout, JOB_WAIT_MAX_SECONDS)`` cap in
  ``_job_wait_request`` fails ``test_a_wait_request_is_capped`` on its
  ``JOB_WAIT_MAX_SECONDS`` assertion.
- Treating a job whose state is not running as waiting (removing the state
  check from ``job_wait_reason``) fails
  ``test_only_a_running_job_waits`` on its ``is None`` assertion.

Restoring each returns the module to green.
"""

from __future__ import annotations

import pytest

from ..job_manager.state import AdmissionWaiter
from ..server._routes import (
    JOB_WAIT_DEFAULT_SECONDS,
    JOB_WAIT_MAX_SECONDS,
    InvalidJobRequestError,
    _job_wait_request,
)
from ..server._routes_jobs import (
    JobFilter,
    _job_matches,
    _job_summary,
    _job_with_liveness,
    job_wait_reason,
    with_admission,
)

pytestmark = [pytest.mark.unit]

_NOW = 2_000.0


def _record(
    job_id: str,
    *,
    state: str = "running",
    step: str | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "id": job_id,
        "state": state,
        "phase": state,
        "source": "code",
        "started_at": _NOW - 100,
    }
    if step is not None:
        record["progress"] = {"step": step, "last_updated": _NOW - 1}
    return record


def _filter(
    waiting: bool | None,
    *,
    phase: str | None = None,
    state: str | None = None,
) -> JobFilter:
    return JobFilter(
        phase=phase,
        source=None,
        trigger=None,
        query=None,
        failed=False,
        job_id=None,
        since_seconds=None,
        now=_NOW,
        state=state,
        waiting=waiting,
    )


class TestWaitReason:
    def test_a_working_job_waits_on_nothing(self) -> None:
        assert job_wait_reason(_record("work", step="embed")) is None

    def test_a_registered_waiter_waits_on_admission(self) -> None:
        (stamped,) = with_admission(
            [_record("held")], (AdmissionWaiter("held", "encode", 1),)
        )
        assert job_wait_reason(stamped) == "admission"

    def test_a_queued_progress_step_waits_on_the_writer(self) -> None:
        assert job_wait_reason(_record("writer", step="queued")) == "writer"

    def test_admission_takes_precedence_over_the_writer(self) -> None:
        (stamped,) = with_admission(
            [_record("both", step="queued")],
            (AdmissionWaiter("both", "index", 1),),
        )
        assert job_wait_reason(stamped) == "admission"

    def test_only_a_running_job_waits(self) -> None:
        (stamped,) = with_admission(
            [_record("paused", state="paused", step="queued")],
            (AdmissionWaiter("paused", "encode", 1),),
        )
        assert job_wait_reason(stamped) is None

    def test_a_stamp_from_an_unknown_slot_is_not_a_wait(self) -> None:
        record = _record("odd") | {"admission_slot": "disk"}
        assert job_wait_reason(record) is None


class TestAdmissionStamp:
    def test_only_waiters_are_stamped_and_the_input_is_untouched(self) -> None:
        waiter, other = _record("waiter"), _record("other")
        stamped = with_admission(
            [waiter, other], (AdmissionWaiter("waiter", "encode", 3),)
        )

        assert stamped[0]["admission_slot"] == "encode"
        assert stamped[0]["queue_position"] == 3
        assert stamped[1] == other
        assert "admission_slot" not in waiter
        assert "queue_position" not in waiter

    def test_an_empty_queue_changes_nothing(self) -> None:
        records = [_record("a"), _record("b")]
        assert with_admission(records, ()) == records


class TestProjection:
    def test_a_waiter_reports_phase_slot_and_position_and_stays_running(
        self,
    ) -> None:
        (stamped,) = with_admission(
            [_record("waiter")], (AdmissionWaiter("waiter", "encode", 2),)
        )
        job = _job_with_liveness(stamped, now=_NOW)

        assert job["state"] == "running"
        assert job["phase"] == "awaiting_admission"
        assert job["waiting_on"] == "admission"
        assert job["admission_slot"] == "encode"
        assert job["queue_position"] == 2

    def test_the_writer_wait_keeps_phase_running(self) -> None:
        job = _job_with_liveness(_record("writer", step="queued"), now=_NOW)

        assert job["state"] == "running"
        assert job["phase"] == "running"
        assert job["waiting_on"] == "writer"
        assert job["admission_slot"] is None
        assert job["queue_position"] is None

    def test_a_working_job_carries_the_keys_as_nulls(self) -> None:
        job = _job_with_liveness(_record("work", step="embed"), now=_NOW)

        assert job["phase"] == "running"
        assert job["waiting_on"] is None
        assert job["admission_slot"] is None
        assert job["queue_position"] is None

    def test_a_waiter_is_never_reported_stalled(self) -> None:
        old = _record("waiter") | {"started_at": _NOW - 10_000}
        (stamped,) = with_admission([old], (AdmissionWaiter("waiter", "encode", 1),))

        assert _job_with_liveness(stamped, now=_NOW)["stalled"] is False


class TestWaitingFilter:
    def _records(self) -> list[dict[str, object]]:
        return with_admission(
            [
                _record("working", step="embed"),
                _record("admission"),
                _record("writer", step="queued"),
                _record("finished", state="succeeded"),
            ],
            (AdmissionWaiter("admission", "encode", 1),),
        )

    def _ids(self, waiting: bool | None) -> list[str]:
        return [
            str(record["id"])
            for record in self._records()
            if _job_matches(record, _filter(waiting))
        ]

    def test_waiting_true_keeps_both_kinds_of_wait(self) -> None:
        assert self._ids(True) == ["admission", "writer"]

    def test_waiting_false_keeps_only_working_running_jobs(self) -> None:
        # The finished job is excluded: the filter speaks about running work.
        assert self._ids(False) == ["working"]

    def test_no_waiting_filter_keeps_everything(self) -> None:
        assert self._ids(None) == ["working", "admission", "writer", "finished"]

    def test_phase_running_excludes_admission_waiters(self) -> None:
        matched = [
            str(record["id"])
            for record in self._records()
            if _job_matches(record, _filter(None, phase="running", state="running"))
        ]
        assert matched == ["working", "writer"]


def test_the_summary_splits_running_into_working_and_waiting() -> None:
    summary = _job_summary(
        with_admission(
            [
                _record("working", step="embed"),
                _record("admission"),
                _record("writer", step="queued"),
            ],
            (AdmissionWaiter("admission", "index", 1),),
        ),
        now=_NOW,
    )

    # ``running`` stays the canonical state count and includes waiters.
    assert summary["running"] == 3
    assert summary["working"] == 1
    assert summary["waiting"] == 2
    assert summary["awaiting_admission"] == 1


class TestWaitRequest:
    def test_defaults_to_finished_with_the_default_timeout(self) -> None:
        assert _job_wait_request(None, None) == ("finished", JOB_WAIT_DEFAULT_SECONDS)
        assert _job_wait_request("", "  ") == ("finished", JOB_WAIT_DEFAULT_SECONDS)

    def test_reads_the_condition_and_the_timeout(self) -> None:
        assert _job_wait_request("Admitted", "2.5") == ("admitted", 2.5)
        assert _job_wait_request("finished", "0") == ("finished", 0.0)

    def test_a_wait_request_is_capped(self) -> None:
        assert _job_wait_request("finished", "100000")[1] == JOB_WAIT_MAX_SECONDS

    @pytest.mark.parametrize("until", ["started", "done", "admitted,finished"])
    def test_an_unknown_condition_is_refused(self, until: str) -> None:
        with pytest.raises(InvalidJobRequestError) as refused:
            _job_wait_request(until, None)
        assert refused.value.code == "invalid_wait"
        assert "until" in str(refused.value)

    @pytest.mark.parametrize("timeout", ["-1", "abc", "nan", "inf", "-inf"])
    def test_an_unusable_timeout_is_refused(self, timeout: str) -> None:
        with pytest.raises(InvalidJobRequestError) as refused:
            _job_wait_request("finished", timeout)
        assert refused.value.code == "invalid_wait"
        assert "timeout" in str(refused.value)
