"""The jobs surface must tell a starved encode from a dead backend or a hang.

Progress ticks only at slice boundaries, and one forward pass can legitimately
run for minutes under GPU contention - so a boolean stall flag with a single
hard threshold shows nothing for the whole window in which an operator is
deciding what is wrong. These tests pin the three-way ``degradation`` verdict,
the forward-pass runtime telemetry that feeds it, and the evidence block that
attributes cause when the verdict is not healthy.

No mocks, stubs, or patches: real registry records, the production enrichment,
real threads, and (for the backend probe) a real local store.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, cast

import pytest

from .._job_errors import DEGRADED_THRESHOLD_SECONDS, STALL_THRESHOLD_SECONDS
from ..job_models import JobSource
from ..jobs import (
    JobProgressReporter,
    degradation_evidence,
    forward_telemetry,
    record_progress,
    record_start,
    reset,
)
from ..server._routes_jobs import _job_degradation, _job_summary, _job_with_liveness

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ..embeddings import EmbeddingModel

pytestmark = [pytest.mark.unit]

_EVIDENCE_KEYS = {"forward", "gpu", "backend"}
_FORWARD_KEYS = {"in_flight", "age_seconds", "slice_ordinal", "items", "thread_alive"}
_GPU_KEYS = {"available", "utilization_percent", "memory_used_mb", "memory_total_mb"}
_BACKEND_KEYS = {"alive", "latency_seconds", "detail"}


def _as_map(value: object) -> dict[str, object]:
    """Assert one payload member is a mapping and type it as one."""
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


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


def _running_record(
    *,
    progress_at: float,
    forward: dict[str, object] | None = None,
    step: str = "embed + upsert documents",
) -> dict[str, object]:
    """One running activity record in the shape the registry snapshots."""
    record: dict[str, object] = {
        "id": "j1",
        "phase": "running",
        "started_at": progress_at - 30.0,
        "finished_at": None,
        "progress": {
            "step": step,
            "completed": 192,
            "total": 4609,
            "last_updated": progress_at,
        },
    }
    if forward is not None:
        record["forward"] = forward
    return record


def _forward_block(
    *,
    entered_at: float,
    exited_at: float | None,
    thread_ident: int | None = None,
) -> dict[str, object]:
    return {
        "entered_at": entered_at,
        "exited_at": exited_at,
        "slice_ordinal": 3,
        "items": 64,
        "thread_ident": (
            thread_ident if thread_ident is not None else threading.get_ident()
        ),
        "thread_name": "encode",
    }


class TestForwardTelemetry:
    """The encode path publishes forward boundaries into the job record."""

    def test_reporter_publishes_an_open_forward_window(self) -> None:
        job_id = record_start(JobSource.VAULT, "tool", command="reindex_vault")
        record_progress(job_id, "embed + upsert documents", 192, 4609)
        reporter = JobProgressReporter(job_id)

        reporter.forward_started(ordinal=3, items=64)
        forward = forward_telemetry(job_id)
        assert forward is not None
        assert isinstance(forward["entered_at"], float)
        assert forward["exited_at"] is None
        assert forward["slice_ordinal"] == 3
        assert forward["items"] == 64
        assert forward["thread_ident"] == threading.get_ident()

        reporter.forward_finished(ordinal=3, items=64)
        forward = forward_telemetry(job_id)
        assert forward is not None
        entered = cast("float", forward["entered_at"])
        exited = forward["exited_at"]
        assert isinstance(exited, float)
        assert exited >= entered

    def test_the_encode_slice_reports_entry_before_the_forward_runs(self) -> None:
        """Entry must precede the model call, or a stuck forward is invisible.

        Mutation check: moving the ``before_forward`` call in
        ``_encode_slice_vector_fields`` after the encode (or dropping it)
        makes this fail on the event-order assertion below, not on an import.
        """
        from .._store_models import VaultChunk
        from ..indexer._streaming import (
            _encode_slice_vector_fields,
            _VectorEncodeRequest,
        )

        events: list[str] = []

        class SliceEncoder:
            """Deterministic encoder exposing the dense-encode call surface."""

            def encode_documents_on_device(
                self,
                texts: list[str],
                batch_size: int | None = None,
            ) -> list[list[float]]:
                del batch_size
                events.append("forward")
                return [[0.0, 1.0] for _ in texts]

        chunk = VaultChunk(
            doc_id="doc",
            ordinal=0,
            chunk_count=1,
            text="body",
            path="adr/doc.md",
            doc_type="adr",
            feature="search",
            date="2026-01-01",
            tags=[],
            related=[],
            title="doc",
        )
        _encode_slice_vector_fields(
            _VectorEncodeRequest(
                chunks=[chunk],
                slice_texts=["doc\n\nbody"],
                model=cast("EmbeddingModel", SliceEncoder()),
                gpu_lock=None,
                sparse_enabled=False,
                encode_batch_size=None,
                before_forward=lambda kind: events.append(f"enter-{kind}"),
                after_forward=lambda kind: events.append(f"exit-{kind}"),
            )
        )
        assert events == ["enter-dense", "forward", "exit-dense"]
        assert chunk.vector == [0.0, 1.0]

    def test_the_vault_stream_wires_the_reporter_boundaries(self) -> None:
        """The vault slice loop hands the reporter both forward boundaries.

        Asserted at the request-construction seam the stream uses, with the
        production adapter functions, so the wiring cannot silently drop to
        ``None`` again (which is exactly how the incident's slice ran dark).
        """
        from functools import partial

        from ..indexer._streaming import _report_forward_entry, _report_forward_exit

        job_id = record_start(JobSource.VAULT, "tool", command="reindex_vault")
        reporter = JobProgressReporter(job_id)
        entry = partial(_report_forward_entry, reporter, 5, 48)
        exit_ = partial(_report_forward_exit, reporter, 5, 48)

        entry("dense")
        forward = forward_telemetry(job_id)
        assert forward is not None
        assert forward["exited_at"] is None
        assert forward["slice_ordinal"] == 5
        assert forward["items"] == 48
        exit_("dense")
        forward = forward_telemetry(job_id)
        assert forward is not None
        assert isinstance(forward["exited_at"], float)


class TestDegradationVerdict:
    """Three tiers: healthy, degraded with cause, stalled at the hard bound."""

    def test_fresh_progress_is_healthy(self) -> None:
        record = _running_record(progress_at=1000.0)
        shaped = _job_with_liveness(record, now=1010.0)
        assert shaped["degradation"] == "healthy"
        # Present-and-null, never absent: absent is the older-daemon signal.
        assert "degradation_evidence" in shaped
        assert shaped["degradation_evidence"] is None

    def test_silent_beyond_the_short_threshold_is_degraded(self) -> None:
        record = _running_record(progress_at=1000.0)
        now = 1000.0 + DEGRADED_THRESHOLD_SECONDS + 30.0
        assert _job_degradation(record, now) == "degraded"
        shaped = _job_with_liveness(record, now=now)
        assert shaped["degradation"] == "degraded"
        assert shaped["stalled"] is False

    def test_a_recent_forward_keeps_old_progress_healthy(self) -> None:
        # The forward exited seconds ago: the slice is in its CPU/storage
        # tail, which is activity, not silence - whatever the progress stamp
        # says. This is the branch that stops the verdict flapping mid-slice.
        record = _running_record(
            progress_at=1000.0,
            forward=_forward_block(entered_at=1080.0, exited_at=1085.0),
        )
        assert _job_degradation(record, 1090.0) == "healthy"

    def test_a_long_in_flight_forward_is_degraded_with_evidence(self) -> None:
        entered = 1000.0
        now = entered + DEGRADED_THRESHOLD_SECONDS + 30.0
        record = _running_record(
            progress_at=990.0,
            forward=_forward_block(entered_at=entered, exited_at=None),
        )
        shaped = _job_with_liveness(record, now=now)
        assert shaped["degradation"] == "degraded"
        evidence = _as_map(shaped["degradation_evidence"])
        assert set(evidence.keys()) == _EVIDENCE_KEYS
        forward = _as_map(evidence["forward"])
        assert set(forward.keys()) == _FORWARD_KEYS
        assert forward["in_flight"] is True
        assert forward["age_seconds"] == pytest.approx(now - entered)
        assert forward["slice_ordinal"] == 3
        assert forward["items"] == 64
        # The block was stamped with this test's own thread.
        assert forward["thread_alive"] is True

    def test_a_dead_encode_thread_is_reported_dead(self) -> None:
        worker = threading.Thread(target=lambda: None)
        worker.start()
        worker.join()
        ident = worker.ident
        assert ident is not None
        record = _running_record(
            progress_at=990.0,
            forward=_forward_block(
                entered_at=1000.0,
                exited_at=None,
                thread_ident=ident,
            ),
        )
        shaped = _job_with_liveness(record, now=1090.1)
        evidence = _as_map(shaped["degradation_evidence"])
        forward = _as_map(evidence["forward"])
        assert forward["thread_alive"] is False

    def test_the_hard_threshold_still_reads_stalled(self) -> None:
        record = _running_record(progress_at=1000.0)
        now = 1000.0 + STALL_THRESHOLD_SECONDS + 10.0
        shaped = _job_with_liveness(record, now=now)
        assert shaped["stalled"] is True
        assert shaped["degradation"] == "stalled"
        assert isinstance(shaped["degradation_evidence"], dict)

    def test_waiting_and_terminal_work_is_inert_not_degraded(self) -> None:
        waiting = _running_record(progress_at=1000.0, step="queued")
        assert _job_degradation(waiting, 2000.0) == "healthy"
        finished: dict[str, object] = {
            "id": "j2",
            "phase": "done",
            "started_at": 100.0,
            "finished_at": 200.0,
            "progress": {
                "step": "embed + upsert documents",
                "completed": 10,
                "total": 10,
                "last_updated": 190.0,
            },
        }
        assert _job_degradation(finished, 5000.0) == "healthy"
        shaped = _job_with_liveness(finished, now=5000.0)
        assert shaped["degradation_evidence"] is None

    def test_gpu_and_backend_evidence_sections_keep_their_shape(self) -> None:
        record = _running_record(progress_at=1000.0)
        shaped = _job_with_liveness(
            record,
            now=1000.0 + DEGRADED_THRESHOLD_SECONDS + 5.0,
        )
        evidence = _as_map(shaped["degradation_evidence"])
        gpu = _as_map(evidence["gpu"])
        assert set(gpu.keys()) == _GPU_KEYS
        assert isinstance(gpu["available"], bool)
        backend = _as_map(evidence["backend"])
        assert set(backend.keys()) == _BACKEND_KEYS
        # This record names no project root, so the probe declines rather
        # than guessing at a store.
        assert backend["alive"] is None
        assert backend["latency_seconds"] is None
        assert isinstance(backend["detail"], str)

    def test_the_summary_counts_degraded_beside_stalled(self) -> None:
        healthy = _running_record(progress_at=1000.0)
        degraded = dict(
            _running_record(progress_at=1000.0 - DEGRADED_THRESHOLD_SECONDS - 30.0)
        )
        degraded["id"] = "j-degraded"
        stalled = dict(
            _running_record(progress_at=1000.0 - STALL_THRESHOLD_SECONDS - 30.0)
        )
        stalled["id"] = "j-stalled"
        summary = _job_summary([healthy, degraded, stalled], now=1010.0)
        assert summary["degraded"] == 1
        assert summary["stalled"] == 1


class TestBackendEvidence:
    """The bounded probe answers from a real store and declines when it can't."""

    def test_a_live_local_backend_answers_the_probe(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ..config._settings import reset_config

        monkeypatch.setenv(
            "VAULTSPEC_RAG_QDRANT_STORAGE_DIR",
            str(tmp_path / "qdrant" / "storage"),
        )
        monkeypatch.setenv("VAULTSPEC_RAG_LOCAL_ONLY", "1")
        reset_config()
        try:
            root = tmp_path / "project"
            root.mkdir()
            evidence = degradation_evidence(
                now=time.time(),
                forward=None,
                project_root=str(root),
                source="vault",
            )
            backend = _as_map(evidence["backend"])
            assert backend["alive"] is True
            assert backend["detail"] is None
            latency = backend["latency_seconds"]
            assert isinstance(latency, float)
            assert latency >= 0.0

            # A second sample inside the cache window reuses the answer, so a
            # polling operator view cannot stack probe threads.
            again = degradation_evidence(
                now=time.time(),
                forward=None,
                project_root=str(root),
                source="vault",
            )
            backend_again = _as_map(again["backend"])
            assert backend_again["latency_seconds"] == latency
        finally:
            reset_config()
