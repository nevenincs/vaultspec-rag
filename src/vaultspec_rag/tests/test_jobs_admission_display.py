"""The jobs feed distinguishes work in progress from a queued admission wait.

Only one encode-bearing index job runs at a time, so the jobs beyond it sit in
the ``running`` phase having done nothing. The feed used to render those as
"active ... running for 6 minutes", which is two claims an operator acts on and
both were wrong: the job was not active, and the duration was its queue wait
rather than time spent working. Four jobs then read as four competing on the
GPU when three had not started - a misreading that survived long enough to
drive a real diagnosis down the wrong path.

The service already publishes the distinction. ``admission_acquired_at`` is
stamped when the attempt's worker actually begins, so its absence on a running
job is the service's own statement that the job is still queued. These pin the
CLI to that field rather than to the phase.

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
    admitted: bool,
    runtime: float,
    progress: dict[str, object] | None = None,
) -> dict[str, object]:
    """One running job, admitted or still queued for the encode slot."""
    # The field is always present, null while queued - the shape the live
    # service publishes. A payload that omits it entirely means something
    # different (an older daemon) and is covered by its own test below.
    record: dict[str, object] = {
        "id": job_id,
        "source": "code",
        "phase": "running",
        "started_at": 1_000.0,
        "runtime_seconds": runtime,
        "admission_acquired_at": 1_001.0 if admitted else None,
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
    """A job queued for the GPU slot is never reported as working."""

    def test_queued_job_is_counted_as_waiting_not_active(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # One admitted job with real progress, three parked on the slot: the
        # exact shape a four-job feed takes on a single GPU.
        jobs = [
            _job(
                "aaaaaaaa",
                admitted=True,
                runtime=300.0,
                progress={"step": "hash documents", "completed": 40, "total": 100},
            ),
            _job("bbbbbbbb", admitted=False, runtime=280.0),
            _job("cccccccc", admitted=False, runtime=200.0),
            _job("dddddddd", admitted=False, runtime=60.0),
        ]
        _render(jobs)
        out = capsys.readouterr().out

        # The headline count is the number an operator reads first.
        assert "Displayed jobs: 1 active, 3 waiting" in out

    def test_queued_job_names_the_gpu_slot_as_what_it_waits_on(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _render([_job("bbbbbbbb", admitted=False, runtime=280.0)])
        out = capsys.readouterr().out

        assert "waiting" in out
        assert "for the GPU slot" in out
        # The duration must not be phrased as time spent working.
        assert "running for" not in out

    def test_admitted_job_still_reports_as_active_and_running(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The other direction: the fix must not relabel a genuinely working
        # job, which is what would happen if the predicate keyed on progress
        # being absent rather than on the admission stamp.
        _render(
            [
                _job(
                    "aaaaaaaa",
                    admitted=True,
                    runtime=300.0,
                    progress={"step": "embed", "completed": 7, "total": 20},
                )
            ]
        )
        out = capsys.readouterr().out

        assert "Displayed jobs: 1 active, 0 waiting" in out
        assert "running for" in out
        assert "for the GPU slot" not in out

    def test_a_payload_omitting_the_field_keeps_the_previous_reading(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # An older daemon - or any projection that does not carry the field -
        # says nothing about admission. Treating that silence as a wait would
        # relabel every running job on such a daemon as queued, which is how
        # this change first broke the status renderer's stale-progress warning.
        # Absent is unknown, and unknown keeps the existing reading.
        record: dict[str, object] = {
            "id": "eeeeeeee",
            "source": "code",
            "phase": "running",
            "started_at": 1_000.0,
            "runtime_seconds": 90.0,
            "progress": {"step": "embed", "completed": 3, "total": 9},
        }
        assert "admission_acquired_at" not in record
        _render([record])
        out = capsys.readouterr().out

        assert "Displayed jobs: 1 active, 0 waiting" in out
        assert "for the GPU slot" not in out

    def test_an_admitted_job_without_progress_is_not_called_waiting(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Guard against the cheap-but-wrong implementation. A job that has won
        # the slot but not yet published its first progress record is working,
        # not queued; keying on missing progress instead of the admission stamp
        # would report it as waiting for a slot it already holds.
        _render([_job("aaaaaaaa", admitted=True, runtime=5.0)])
        out = capsys.readouterr().out

        assert "Displayed jobs: 1 active, 0 waiting" in out
        assert "for the GPU slot" not in out
