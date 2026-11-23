"""The jobs feed renders the service's admission verdict and derives nothing.

Only one encode-bearing index job runs at a time, so the jobs beyond it sit in
the ``running`` state having done nothing. The feed used to render those as
"active ... running for 6 minutes", which is two claims an operator acts on and
both were wrong: the job was not active, and the duration was its queue wait
rather than time spent working.

The service owns the verdict. It publishes ``waiting_on``, ``admission_slot``
and ``queue_position`` for a job that waits, and a null ``waiting_on`` for one
that does not. These pin the CLI to those fields: it renders them, and it never
reads a wait out of a null admission stamp or a missing field.

MUTATION PROOF, each run in one uninterrupted sequence:

- Making ``job_waiting_on`` return ``admission`` for a running job whose
  ``admission_acquired_at`` is null fails
  ``test_a_null_admission_stamp_alone_is_not_a_wait`` on its
  ``0 waiting`` assertion.
- Making ``_admission_wait_detail`` drop the queue position fails
  ``test_a_waiter_reports_the_service_queue_position`` on its position
  assertion.

Restoring each returns the module to green.

No mocks, patches, or fakes: the real renderer writes to the real console and
the assertions read what it printed.
"""

from __future__ import annotations

import pytest

from ..cli._service_jobs_presentation import _render_jobs_feed

pytestmark = [pytest.mark.unit]


def _job(
    job_id: str,
    *,
    position: int | None,
    runtime: float,
    slot: str = "encode",
    progress: dict[str, object] | None = None,
) -> dict[str, object]:
    """One running job, working (no position) or waiting at *position*."""
    waiting = position is not None
    record: dict[str, object] = {
        "id": job_id,
        "source": "code",
        "state": "running",
        "phase": "awaiting_admission" if waiting else "running",
        "waiting_on": "admission" if waiting else None,
        "admission_slot": slot if waiting else None,
        "queue_position": position,
        "started_at": 1_000.0,
        "runtime_seconds": runtime,
        "initiator": {"command": "reindex_codebase", "project_root": "/w/demo"},
    }
    if progress is not None:
        record["progress"] = progress
    return record


def _render(jobs: list[dict[str, object]]) -> str:
    _render_jobs_feed(
        {"total": len(jobs), "returned": len(jobs)},
        list(jobs),
        port=8766,
    )
    return ""


class TestAdmissionWaitIsVisible:
    """A job the service says waits for a slot is never reported as working."""

    def test_queued_job_is_counted_as_waiting_not_active(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # One working job with real progress, three parked on the slot: the
        # exact shape a four-job feed takes on a single GPU.
        jobs = [
            _job(
                "aaaaaaaa",
                position=None,
                runtime=300.0,
                progress={"step": "hash documents", "completed": 40, "total": 100},
            ),
            _job("bbbbbbbb", position=1, runtime=280.0),
            _job("cccccccc", position=2, runtime=200.0),
            _job("dddddddd", position=3, runtime=60.0),
        ]
        _render(jobs)
        out = capsys.readouterr().out

        # The headline count is the number an operator reads first.
        assert "Displayed jobs: 1 active, 3 waiting" in out

    def test_a_waiter_reports_the_service_queue_position(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _render([_job("bbbbbbbb", position=2, runtime=280.0)])
        out = capsys.readouterr().out

        assert "for the GPU slot" in out
        assert "queue position 2" in out
        # The duration must not be phrased as time spent working.
        assert "running for" not in out

    def test_an_index_slot_waiter_does_not_claim_the_gpu_slot(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _render([_job("bbbbbbbb", position=1, runtime=20.0, slot="index")])
        out = capsys.readouterr().out

        assert "for an index slot, queue position 1" in out
        assert "GPU slot" not in out

    def test_a_working_job_still_reports_as_active_and_running(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The other direction: a job the service says is working must not be
        # relabelled, whatever its progress looks like.
        _render(
            [
                _job(
                    "aaaaaaaa",
                    position=None,
                    runtime=300.0,
                    progress={"step": "embed", "completed": 7, "total": 20},
                )
            ]
        )
        out = capsys.readouterr().out

        assert "Displayed jobs: 1 active, 0 waiting" in out
        assert "running for" in out
        assert "for the GPU slot" not in out

    def test_a_payload_without_waiting_on_is_not_waiting(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # An older daemon, or any projection that does not carry the field,
        # says nothing about waiting. The CLI renders what the service says and
        # an absent verdict is "not waiting", never a wait read from elsewhere.
        record: dict[str, object] = {
            "id": "eeeeeeee",
            "source": "code",
            "phase": "running",
            "started_at": 1_000.0,
            "runtime_seconds": 90.0,
            "progress": {"step": "embed", "completed": 3, "total": 9},
        }
        assert "waiting_on" not in record
        _render([record])
        out = capsys.readouterr().out

        assert "Displayed jobs: 1 active, 0 waiting" in out
        assert "for the GPU slot" not in out

    def test_a_null_admission_stamp_alone_is_not_a_wait(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The retired inference read a wait from a null admission stamp. The
        # stamp measures the wait; it is not the verdict, and a payload that
        # carries only the stamp is a working job.
        record = _job("ffffffff", position=None, runtime=5.0)
        record["admission_acquired_at"] = None
        _render([record])
        out = capsys.readouterr().out

        assert "Displayed jobs: 1 active, 0 waiting" in out
        assert "for the GPU slot" not in out
