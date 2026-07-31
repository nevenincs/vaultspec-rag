"""Focused real-behavior coverage for the jobs registry."""

from __future__ import annotations

import threading
from typing import cast

import pytest

from ... import jobs as _jobs
from ...job_models import JobSource
from ._jobs_registry_support import (
    assert_done_job_snapshot,
    assert_running_job_snapshot,
)


@pytest.mark.unit
def test_record_start_then_finish_produces_done_snapshot(_clean_jobs: None) -> None:
    job_id = _jobs.record_start(JobSource.VAULT, "tool")

    running = _jobs.snapshot()
    assert len(running) == 1
    assert_running_job_snapshot(running[0], job_id)

    _jobs.record_finish(job_id, result="+1 /0 -0 (5ms)")

    finished = _jobs.snapshot()
    assert len(finished) == 1
    assert_done_job_snapshot(finished[0], job_id)


@pytest.mark.unit
def test_record_finish_with_error_sets_error_phase(_clean_jobs: None) -> None:
    job_id = _jobs.record_start(JobSource.CODE, "watcher")
    _jobs.record_finish(job_id, error="boom")

    entry = _jobs.snapshot()[0]
    assert entry["source"] == "code"
    assert entry["trigger"] == "watcher"
    assert entry["phase"] == "error"
    assert entry["result"] == "boom"
    assert isinstance(entry["finished_at"], float)


@pytest.mark.unit
def test_record_finish_unknown_id_is_noop(_clean_jobs: None) -> None:
    job_id = _jobs.record_start(JobSource.VAULT, "tool")
    _jobs.record_finish("does-not-exist", result="ignored")

    entries = _jobs.snapshot()
    assert len(entries) == 1
    assert entries[0]["id"] == job_id
    assert entries[0]["phase"] == "running"


@pytest.mark.unit
def test_snapshot_is_newest_first(_clean_jobs: None) -> None:
    first = _jobs.record_start(JobSource.VAULT, "tool")
    second = _jobs.record_start(JobSource.CODE, "tool")
    third = _jobs.record_start(JobSource.VAULT, "watcher")

    ids = [entry["id"] for entry in _jobs.snapshot()]
    assert ids == [third, second, first]


@pytest.mark.unit
def test_snapshot_returns_independent_copies(_clean_jobs: None) -> None:
    _jobs.record_start(JobSource.VAULT, "tool", command="reindex_vault")
    snap = _jobs.snapshot()
    snap[0]["phase"] = "tampered"
    initiator = snap[0]["initiator"]
    assert isinstance(initiator, dict)
    initiator = cast("dict[str, object]", initiator)
    initiator["command"] = "tampered"
    resources = snap[0]["resources"]
    assert isinstance(resources, dict)
    resources = cast("dict[str, object]", resources)
    started_resources = resources["started"]
    assert isinstance(started_resources, dict)
    started_resources = cast("dict[str, object]", started_resources)
    started_resources["rss_mib"] = -1.0

    assert _jobs.snapshot()[0]["phase"] == "running"
    next_initiator = _jobs.snapshot()[0]["initiator"]
    assert isinstance(next_initiator, dict)
    next_initiator = cast("dict[str, object]", next_initiator)
    assert next_initiator["command"] == "reindex_vault"
    next_resources = _jobs.snapshot()[0]["resources"]
    assert isinstance(next_resources, dict)
    next_resources = cast("dict[str, object]", next_resources)
    next_started_resources = next_resources["started"]
    assert isinstance(next_started_resources, dict)
    next_started_resources = cast("dict[str, object]", next_started_resources)
    assert next_started_resources["rss_mib"] != -1.0


@pytest.mark.unit
def test_registry_is_bounded(_clean_jobs: None) -> None:
    overflow = _jobs.MAX_RECORDS + 50
    ids = [_jobs.record_start(JobSource.VAULT, "tool") for _ in range(overflow)]

    snap = _jobs.snapshot()
    assert len(snap) == _jobs.MAX_RECORDS

    # Newest-first: the most recent record must be the last id started, and
    # the oldest retained must be the first id NOT evicted.
    assert snap[0]["id"] == ids[-1]
    assert snap[-1]["id"] == ids[-_jobs.MAX_RECORDS]

    # Evicted ids are gone entirely.
    retained_ids = {entry["id"] for entry in snap}
    assert ids[0] not in retained_ids


@pytest.mark.unit
def test_concurrent_writers_do_not_corrupt(_clean_jobs: None) -> None:
    writers = 8
    per_writer = 100
    barrier = threading.Barrier(writers)

    def _worker() -> None:
        barrier.wait()
        for _ in range(per_writer):
            jid = _jobs.record_start(JobSource.VAULT, "tool")
            _jobs.record_finish(jid, result="ok")

    threads = [threading.Thread(target=_worker) for _ in range(writers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    snap = _jobs.snapshot()
    # The buffer is bounded, so the final count is exactly the cap (total
    # writes far exceed MAX_RECORDS).
    assert len(snap) == _jobs.MAX_RECORDS

    # No record is corrupt: every retained entry carries the full schema,
    # unique ids, and a consistent phase/result pairing.
    seen_ids: set[str] = set()
    for entry in snap:
        assert {
            "id",
            "source",
            "trigger",
            "phase",
            "started_at",
            "finished_at",
            "result",
            "progress",
            "initiator",
            "runtime",
            "resources",
        } <= set(entry)
        entry_id = entry["id"]
        assert isinstance(entry_id, str)
        assert entry_id not in seen_ids
        seen_ids.add(entry_id)
        assert entry["source"] == "vault"
        assert entry["trigger"] == "tool"
        # All work completed before join(), so every retained record is done.
        assert entry["phase"] == "done"
        assert entry["result"] == "ok"
        assert isinstance(entry["finished_at"], float)
