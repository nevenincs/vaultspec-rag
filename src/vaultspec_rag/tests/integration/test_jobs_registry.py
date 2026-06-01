"""Tests for the in-flight activity registry (#142, plan P01).

Two layers, no mocks/skips/monkeypatch:

- Unit-style: drive ``_jobs.record_start`` / ``record_finish`` / ``snapshot``
  directly to assert the record schema, the bounded ring-buffer behaviour, and
  thread-safety under real concurrent writers.
- Integration (GPU): call the real ``reindex_vault`` / ``reindex_codebase``
  MCP tools against a real indexed workspace (reusing the session-scoped
  ``embedding_model`` fixture and the global-registry pattern from
  ``test_watcher_control.py``) and assert a finished ``trigger="tool"`` entry
  lands in the snapshot.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from vaultspec_rag import mcp_server
from vaultspec_rag.mcp_server import _jobs

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from vaultspec_rag.embeddings import EmbeddingModel


@pytest.fixture
def _clean_jobs() -> Iterator[None]:
    """Reset the registry before/after each test and stop any watcher.

    The reindex tools start a filesystem watcher via ``_ensure_watcher``
    as a side effect; stop them on teardown so the GPU integration tests
    do not leak watcher tasks across the session (mirrors
    ``test_watcher_control.py``).
    """
    _jobs.reset()
    yield
    mcp_server._stop_all_watchers()
    _jobs.reset()


def _make_root(tmp_path: Path) -> Path:
    """Create a minimal vaultspec project root with one indexable doc."""
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "x.md").write_text(
        "---\ntags: ['#adr', '#t']\n---\n# x\n\nbody\n",
        encoding="utf-8",
    )
    return tmp_path


# --------------------------------------------------------------------------- #
# Unit-style: schema, bounding, concurrency                                   #
# --------------------------------------------------------------------------- #


def test_record_start_then_finish_produces_done_snapshot(_clean_jobs: None) -> None:
    job_id = _jobs.record_start("vault", "tool")

    running = _jobs.snapshot()
    assert len(running) == 1
    entry = running[0]
    assert entry["id"] == job_id
    assert entry["source"] == "vault"
    assert entry["trigger"] == "tool"
    assert entry["phase"] == "running"
    assert isinstance(entry["started_at"], float)
    assert entry["finished_at"] is None
    assert entry["result"] is None

    _jobs.record_finish(job_id, result="+1 /0 -0 (5ms)")

    finished = _jobs.snapshot()
    assert len(finished) == 1
    done = finished[0]
    assert done["id"] == job_id
    assert done["phase"] == "done"
    finished_at = done["finished_at"]
    started_at = done["started_at"]
    assert isinstance(finished_at, float)
    assert isinstance(started_at, float)
    assert finished_at >= started_at
    assert done["result"] == "+1 /0 -0 (5ms)"


def test_record_finish_with_error_sets_error_phase(_clean_jobs: None) -> None:
    job_id = _jobs.record_start("code", "watcher")
    _jobs.record_finish(job_id, error="boom")

    entry = _jobs.snapshot()[0]
    assert entry["source"] == "code"
    assert entry["trigger"] == "watcher"
    assert entry["phase"] == "error"
    assert entry["result"] == "boom"
    assert isinstance(entry["finished_at"], float)


def test_record_finish_unknown_id_is_noop(_clean_jobs: None) -> None:
    job_id = _jobs.record_start("vault", "tool")
    _jobs.record_finish("does-not-exist", result="ignored")

    entries = _jobs.snapshot()
    assert len(entries) == 1
    assert entries[0]["id"] == job_id
    assert entries[0]["phase"] == "running"


def test_snapshot_is_newest_first(_clean_jobs: None) -> None:
    first = _jobs.record_start("vault", "tool")
    second = _jobs.record_start("code", "tool")
    third = _jobs.record_start("vault", "watcher")

    ids = [entry["id"] for entry in _jobs.snapshot()]
    assert ids == [third, second, first]


def test_snapshot_returns_independent_copies(_clean_jobs: None) -> None:
    _jobs.record_start("vault", "tool")
    snap = _jobs.snapshot()
    snap[0]["phase"] = "tampered"

    assert _jobs.snapshot()[0]["phase"] == "running"


def test_registry_is_bounded(_clean_jobs: None) -> None:
    overflow = _jobs.MAX_RECORDS + 50
    ids = [_jobs.record_start("vault", "tool") for _ in range(overflow)]

    snap = _jobs.snapshot()
    assert len(snap) == _jobs.MAX_RECORDS

    # Newest-first: the most recent record must be the last id started, and
    # the oldest retained must be the first id NOT evicted.
    assert snap[0]["id"] == ids[-1]
    assert snap[-1]["id"] == ids[-_jobs.MAX_RECORDS]

    # Evicted ids are gone entirely.
    retained_ids = {entry["id"] for entry in snap}
    assert ids[0] not in retained_ids


def test_concurrent_writers_do_not_corrupt(_clean_jobs: None) -> None:
    writers = 8
    per_writer = 100
    barrier = threading.Barrier(writers)

    def _worker() -> None:
        barrier.wait()
        for _ in range(per_writer):
            jid = _jobs.record_start("vault", "tool")
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
        assert set(entry) == {
            "id",
            "source",
            "trigger",
            "phase",
            "started_at",
            "finished_at",
            "result",
        }
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


# --------------------------------------------------------------------------- #
# Integration (GPU): real reindex tools write tool-triggered records          #
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_reindex_vault_records_finished_tool_job(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
    _clean_jobs: None,
) -> None:
    root = _make_root(tmp_path)
    mcp_server._registry._model = embedding_model

    response = await mcp_server.reindex_vault(project_root=str(root))
    assert isinstance(response, mcp_server.IndexResponse)

    vault_tool_jobs = [
        entry
        for entry in _jobs.snapshot()
        if entry["source"] == "vault" and entry["trigger"] == "tool"
    ]
    assert len(vault_tool_jobs) == 1
    job = vault_tool_jobs[0]
    assert job["phase"] == "done"
    assert isinstance(job["finished_at"], float)
    assert isinstance(job["result"], str)


@pytest.mark.integration
async def test_reindex_codebase_records_finished_tool_job(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
    _clean_jobs: None,
) -> None:
    root = _make_root(tmp_path)
    mcp_server._registry._model = embedding_model

    response = await mcp_server.reindex_codebase(project_root=str(root))
    assert isinstance(response, mcp_server.IndexResponse)

    code_tool_jobs = [
        entry
        for entry in _jobs.snapshot()
        if entry["source"] == "code" and entry["trigger"] == "tool"
    ]
    assert len(code_tool_jobs) == 1
    job = code_tool_jobs[0]
    assert job["phase"] == "done"
    assert isinstance(job["finished_at"], float)
    assert isinstance(job["result"], str)
