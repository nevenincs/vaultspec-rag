"""Progress counters must reach the log and the durable snapshot mid-phase.

The progress write path used to gate both the log line and the fsynced
active-jobs snapshot on the step NAME changing. That gate admits exactly one
write per phase - the phase-start report, whose count is zero by
construction - so in a whole service-log history no progress event ever
carried a nonzero count, the snapshot sat frozen at zero for the life of a
job, and an interrupted job always restored as zero progress. These tests
pin the decoupled behaviour: a step transition writes both outputs
immediately, counter advances reach each output at its own bounded rate, and
a nonzero count actually lands in the log and on disk mid-phase.

No mocks, patches, or fakes: the real registry, the real atomic snapshot
write, and the real log emission; time is injected through the production
``now`` parameter rather than slept for.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, cast

import pytest

from .._job_progress import record_progress
from ..config._settings import managed_status_dir
from ..job_models import JobSource
from ..jobs import record_start, reset, snapshot

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_JOBS_LOGGER = "vaultspec_rag.jobs"


@pytest.fixture(autouse=True)
def own_status_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    from ..config._settings import reset_config

    monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
    reset_config()
    reset()
    yield
    reset()
    reset_config()


def _snapshot_entry(job_id: str) -> dict[str, object]:
    payload = json.loads(
        (managed_status_dir() / "jobs-active.json").read_text(encoding="utf-8")
    )
    active = cast("list[dict[str, object]]", payload["active"])
    return next(entry for entry in active if entry["id"] == job_id)


def _snapshot_progress(job_id: str) -> dict[str, object]:
    return cast("dict[str, object]", _snapshot_entry(job_id)["progress"])


def _progress_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if "event=progress" in record.getMessage()
    ]


class TestProgressEmission:
    """Mid-phase counter advances reach both outputs, at bounded rates."""

    def test_a_nonzero_count_reaches_the_log_and_the_snapshot_mid_phase(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The regression whose absence let the zero-only history ship.

        Mutation check: re-gating the log fields or the persist decision in
        ``record_progress`` on the step name changing alone makes this fail
        on the ``completed=42`` log assertion and the snapshot ``completed``
        assertion below respectively - not on an import - and restoring the
        interval throttles returns it to green.
        """
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        t0 = time.time()
        record_progress(job_id, "chunk + embed", 0, 4703, now=t0)
        # Both windows have elapsed: the advance must write both outputs.
        with caplog.at_level(logging.INFO, logger=_JOBS_LOGGER):
            record_progress(job_id, "chunk + embed", 42, 4703, now=t0 + 31.0)
        messages = _progress_messages(caplog)
        assert any("completed=42" in message for message in messages)
        progress = _snapshot_progress(job_id)
        assert progress["completed"] == 42
        assert progress["total"] == 4703

    def test_advances_inside_both_windows_write_neither_output(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The throttle is real: a one-second-later advance is coalesced.

        Mutation check: dropping either interval comparison (writing every
        call unconditionally) makes this fail on the no-log or the
        snapshot-still-zero assertion below by name; restoring the
        comparisons returns it to green. The in-memory record must still
        carry the newest count - only the write-out is coalesced.
        """
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        t0 = time.time()
        record_progress(job_id, "chunk + embed", 0, 100, now=t0)
        # Drop the phase-start emission so only the throttled call is judged.
        caplog.clear()
        with caplog.at_level(logging.INFO, logger=_JOBS_LOGGER):
            record_progress(job_id, "chunk + embed", 5, 100, now=t0 + 1.0)
        assert _progress_messages(caplog) == []
        assert _snapshot_progress(job_id)["completed"] == 0
        live = next(entry for entry in snapshot() if entry["id"] == job_id)
        live_progress = cast("dict[str, object]", live["progress"])
        assert live_progress["completed"] == 5

    def test_the_log_ticks_before_the_snapshot_does(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Between the two intervals the cheap output writes, the fsync waits."""
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        t0 = time.time()
        record_progress(job_id, "chunk + embed", 0, 100, now=t0)
        with caplog.at_level(logging.INFO, logger=_JOBS_LOGGER):
            record_progress(job_id, "chunk + embed", 7, 100, now=t0 + 6.0)
        messages = _progress_messages(caplog)
        assert any("completed=7" in message for message in messages)
        assert _snapshot_progress(job_id)["completed"] == 0

    def test_a_step_transition_writes_both_outputs_immediately(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        t0 = time.time()
        record_progress(job_id, "hash files", 3, 10, now=t0)
        with caplog.at_level(logging.INFO, logger=_JOBS_LOGGER):
            record_progress(job_id, "chunk + embed", 0, 100, now=t0 + 0.5)
        messages = _progress_messages(caplog)
        assert any("chunk + embed" in message for message in messages)
        assert _snapshot_progress(job_id)["step"] == "chunk + embed"

    def test_throttle_state_never_reaches_a_snapshot(self) -> None:
        # Mutation check: removing the ``item.pop`` of the throttle key in
        # the shared record copier makes this fail on the key assertion
        # below, not on an import.
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        record_progress(job_id, "chunk + embed", 1, 10)
        entries = snapshot()
        assert entries
        assert all("progress_emitted" not in entry for entry in entries)
