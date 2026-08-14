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

from .._job_errors import (
    DEGRADED_THRESHOLD_SECONDS,
    RATE_COLLAPSE_RATIO,
    STALL_THRESHOLD_SECONDS,
)
from .._job_evidence import DegradationInputs, degradation_evidence
from .._job_progress import progress_rates, record_progress, telemetry_block
from ..job_models import JobSource
from ..jobs import TERMINAL_PHASES, JobProgressReporter, record_start, reset, snapshot
from ..server._routes_jobs import (
    _LEGACY_TERMINAL_PHASES,
    _job_degradation,
    _job_summary,
    _job_with_liveness,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    import httpx

    from ..embeddings import EmbeddingModel

pytestmark = [pytest.mark.unit]

_EVIDENCE_KEYS = {"forward", "cpu", "gpu", "backend"}
_FORWARD_KEYS = {
    "in_flight",
    "age_seconds",
    "slice_ordinal",
    "items",
    "thread_alive",
    "expected",
}
_CPU_KEYS = {"available", "utilization_percent"}
_ENCODE_KEYS = {
    "token_budget",
    "bucket_items",
    "items_done",
    "items_total",
    "oom_count",
}
_RATE_KEYS = {"recent_per_second", "median_per_second", "ratio"}
_GPU_KEYS = {"available", "utilization_percent", "memory_used_mib", "memory_total_mib"}
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
        forward = telemetry_block(job_id, "forward")
        assert forward is not None
        assert isinstance(forward["entered_at"], float)
        assert forward["exited_at"] is None
        assert forward["slice_ordinal"] == 3
        assert forward["items"] == 64
        assert forward["thread_ident"] == threading.get_ident()

        reporter.forward_finished(ordinal=3, items=64)
        forward = telemetry_block(job_id, "forward")
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
                gpu_lock: object | None = None,
                on_bucket: object | None = None,
            ) -> list[list[float]]:
                del batch_size, gpu_lock, on_bucket
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

    def test_the_encode_slice_hands_the_bucket_seam_to_the_sparse_encode(
        self,
    ) -> None:
        """The sparse encode publishes through the same bucket seam as dense.

        A sparse CUDA OOM lowers the sparse ceiling and retries without any
        dense boundary firing; evidence fed only through the dense seam then
        carries a zero retry count and a healthy budget while the sparse
        ceiling is the collapsing one, pointing the operator away from the
        memory squeeze. Half-populated evidence misdirects, so the sparse
        call must receive the slice's bucket callback.

        Mutation check: dropping ``on_bucket=request.on_encode_bucket`` from
        the sparse call in ``_encode_slice_vector_fields`` makes this fail
        on the sparse-events assertion below - the sparse encoder receives
        no callback and publishes nothing - and restoring it returns the
        test to green.
        """
        from .._store_models import VaultChunk
        from ..embeddings import EncodeBucketProgress
        from ..indexer._streaming import (
            _encode_slice_vector_fields,
            _VectorEncodeRequest,
        )

        observed: list[tuple[str, str, int]] = []

        def _bucket_progress(kind: str, oom_count: int) -> EncodeBucketProgress:
            return EncodeBucketProgress(
                kind=kind,
                items_done=0,
                items_total=1,
                bucket_items=1,
                bucket_estimated_tokens=500,
                token_budget=1000,
                oom_count=oom_count,
            )

        class SliceEncoder:
            """Deterministic encoder replaying one bucket per encode kind."""

            def encode_documents_on_device(
                self,
                texts: list[str],
                batch_size: int | None = None,
                gpu_lock: object | None = None,
                on_bucket: Callable[[str, EncodeBucketProgress], None] | None = None,
            ) -> list[list[float]]:
                del batch_size, gpu_lock
                if on_bucket is not None:
                    on_bucket("before", _bucket_progress("dense", 0))
                    on_bucket("after", _bucket_progress("dense", 0))
                return [[0.0, 1.0] for _ in texts]

            def encode_documents_sparse(
                self,
                texts: list[str],
                batch_size: int | None = None,
                gpu_lock: object | None = None,
                on_bucket: Callable[[str, EncodeBucketProgress], None] | None = None,
            ) -> list[None]:
                del batch_size, gpu_lock
                if on_bucket is not None:
                    on_bucket("before", _bucket_progress("sparse", 1))
                    on_bucket("after", _bucket_progress("sparse", 1))
                return [None for _ in texts]

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
                sparse_enabled=True,
                encode_batch_size=None,
                on_encode_bucket=lambda phase, progress: observed.append(
                    (progress.kind, phase, progress.oom_count)
                ),
            )
        )
        # The sparse boundaries - and the retry count they carry - reach the
        # slice's callback, after the dense ones.
        assert [event for event in observed if event[0] == "sparse"] == [
            ("sparse", "before", 1),
            ("sparse", "after", 1),
        ]
        assert [event for event in observed if event[0] == "dense"] == [
            ("dense", "before", 0),
            ("dense", "after", 0),
        ]

    def test_the_vault_stream_wires_the_reporter_boundaries(self) -> None:
        """The vault slice loop hands the reporter both forward boundaries.

        Asserted at the request-construction seam the stream uses, with the
        production adapter functions, so the wiring cannot silently drop to
        ``None`` again (which is exactly how the incident's slice ran dark).
        """
        from functools import partial

        from ..indexer._streaming import report_forward_entry, report_forward_exit

        job_id = record_start(JobSource.VAULT, "tool", command="reindex_vault")
        reporter = JobProgressReporter(job_id)
        entry = partial(report_forward_entry, reporter, 5, 48)
        exit_ = partial(report_forward_exit, reporter, 5, 48)

        entry("dense")
        forward = telemetry_block(job_id, "forward")
        assert forward is not None
        assert forward["exited_at"] is None
        assert forward["slice_ordinal"] == 5
        assert forward["items"] == 48
        exit_("dense")
        forward = telemetry_block(job_id, "forward")
        assert forward is not None
        assert isinstance(forward["exited_at"], float)


class TestEncodeEvidence:
    """The encode section carries the sub-slice climb with its denominator."""

    def test_the_climb_is_shaped_with_the_total_it_is_read_against(self) -> None:
        evidence = degradation_evidence(
            now=1000.0,
            inputs=DegradationInputs(
                source="code",
                step="chunk + embed",
                encode={
                    "token_budget": 2000,
                    "bucket_items": 1,
                    "items_done": 64,
                    "items_total": 512,
                    "oom_count": 1,
                },
            ),
        )
        encode = _as_map(evidence["encode"])
        assert set(encode.keys()) == _ENCODE_KEYS
        assert encode["items_done"] == 64
        assert encode["items_total"] == 512

    def test_a_block_predating_the_pair_reports_neither_as_a_number(self) -> None:
        # A record written before the encode block carried sub-slice progress
        # has no such reading, and a shaped null is how that is said. Inventing
        # one from the batch size would be the same untruth the forward
        # window's item count used to tell.
        evidence = degradation_evidence(
            now=1000.0,
            inputs=DegradationInputs(
                source="code",
                step="chunk + embed",
                encode={"token_budget": 2000, "bucket_items": 1, "oom_count": 1},
            ),
        )
        encode = _as_map(evidence["encode"])
        assert set(encode.keys()) == _ENCODE_KEYS
        assert encode["items_done"] is None
        assert encode["items_total"] is None
        assert encode["token_budget"] == 2000


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
        shaped = _job_with_liveness(record, now=now)
        assert shaped["degradation"] == "degraded"
        assert shaped["stalled"] is False

    def test_a_recent_forward_keeps_old_progress_healthy(self) -> None:
        # The forward exited seconds ago: the slice is in its CPU/storage
        # tail, which is activity, not silence - whatever the progress stamp
        # says. This is the branch that stops the verdict flapping mid-slice.
        # Read as the route reads it: the verdict is a function of the
        # window and the comparison handed to it, and nothing else.
        forward = _forward_block(entered_at=1080.0, exited_at=1085.0)
        record = _running_record(progress_at=1000.0, forward=forward)
        verdict = _job_degradation(
            record,
            1090.0,
            forward=forward,
            rate_baseline=None,
        )
        assert verdict == "healthy"

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
        assert _job_with_liveness(waiting, now=2000.0)["degradation"] == "healthy"
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
        shaped = _job_with_liveness(finished, now=5000.0)
        assert shaped["degradation"] == "healthy"
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


class TestPhaseAwareEvidence:
    """A CPU-bound phase is never judged by a signal it cannot produce."""

    def test_a_cpu_bound_step_marks_the_forward_signal_not_expected(self) -> None:
        """The hashing-phase incident: silence there is the phase's shape.

        Mutation check: hard-coding ``expected`` to ``True`` in
        ``degradation_evidence`` makes this fail on the ``expected is
        False`` assertion below, not on an import; restoring the step
        classifier returns it to green.
        """
        record = _running_record(progress_at=1000.0, step="hash files")
        now = 1000.0 + DEGRADED_THRESHOLD_SECONDS + 30.0
        shaped = _job_with_liveness(record, now=now)
        assert shaped["degradation"] == "degraded"
        evidence = _as_map(shaped["degradation_evidence"])
        forward = _as_map(evidence["forward"])
        assert forward["expected"] is False

    def test_an_encoding_step_keeps_the_forward_signal_expected(self) -> None:
        record = _running_record(progress_at=1000.0)
        now = 1000.0 + DEGRADED_THRESHOLD_SECONDS + 30.0
        shaped = _job_with_liveness(record, now=now)
        evidence = _as_map(shaped["degradation_evidence"])
        forward = _as_map(evidence["forward"])
        assert forward["expected"] is True

    def test_the_published_step_vocabulary_classifies_both_ways(self) -> None:
        from .._job_evidence import _forward_pass_expected

        encoding = {
            "chunk + embed",
            "embed",
            "embed + upsert chunks",
            "embed + upsert documents",
            "embed + upsert document chunks",
        }
        cpu_bound = {
            "queued",
            "discover",
            "scan codebase",
            "scan changed",
            "hash files",
            "prepare collection",
            "purge stale chunks",
            "delete removed",
            "write metadata",
            "resolve workspace",
            "resume document publication",
        }
        for step in encoding:
            assert _forward_pass_expected(step) is True, step
        for step in cpu_bound:
            assert _forward_pass_expected(step) is False, step
        # No step reported means no basis to suppress the signal.
        assert _forward_pass_expected(None) is None
        assert _forward_pass_expected("") is None

    def test_the_cpu_section_reports_a_reading_after_priming(self) -> None:
        import vaultspec_rag._job_evidence as jobs_module

        from .._job_evidence import _process_cpu_evidence

        jobs_module._cpu_snapshot_cache = None
        jobs_module._cpu_probe_process = None
        first = _process_cpu_evidence(now=1000.0)
        assert set(first) == _CPU_KEYS
        assert first["available"] is True
        # The first sample only primes the interval counter; a fabricated
        # zero here would read as a dead process.
        assert first["utilization_percent"] is None
        second = _process_cpu_evidence(now=1000.0 + 6.0)
        assert second["available"] is True
        percent = second["utilization_percent"]
        assert isinstance(percent, float)
        assert percent >= 0.0

    def test_polling_inside_the_window_reuses_the_cpu_reading(self) -> None:
        import vaultspec_rag._job_evidence as jobs_module

        from .._job_evidence import _process_cpu_evidence

        jobs_module._cpu_snapshot_cache = None
        jobs_module._cpu_probe_process = None
        _process_cpu_evidence(now=2000.0)
        _process_cpu_evidence(now=2002.0)
        cached = jobs_module._cpu_snapshot_cache
        assert cached is not None
        assert cached[0] == 2000.0, (
            "a poll inside the window must not pay the probe again"
        )

    def test_evidence_carries_the_cpu_section_beside_the_others(self) -> None:
        record = _running_record(progress_at=1000.0, step="hash files")
        now = 1000.0 + DEGRADED_THRESHOLD_SECONDS + 30.0
        shaped = _job_with_liveness(record, now=now)
        evidence = _as_map(shaped["degradation_evidence"])
        assert set(evidence.keys()) == _EVIDENCE_KEYS
        cpu = _as_map(evidence["cpu"])
        assert set(cpu.keys()) == _CPU_KEYS


class TestGpuPressureSnapshot:
    """The listing-level GPU block: evidence-shaped, cached, unpoisonable."""

    @staticmethod
    def _reset_cache() -> None:
        import vaultspec_rag._job_evidence as jobs_module

        jobs_module._gpu_snapshot_cache = None

    def test_the_snapshot_carries_the_evidence_shape(self) -> None:
        from .._job_evidence import gpu_pressure_snapshot

        self._reset_cache()
        snapshot = gpu_pressure_snapshot(now=1000.0)
        assert set(snapshot) == _GPU_KEYS, (
            "the header block and the evidence block must be the same shape"
        )

    def test_polling_inside_the_window_reuses_the_reading(self) -> None:
        """The stamp moves only when the probe actually re-runs."""
        import vaultspec_rag._job_evidence as jobs_module

        from .._job_evidence import gpu_pressure_snapshot

        self._reset_cache()
        gpu_pressure_snapshot(now=2000.0)
        gpu_pressure_snapshot(now=2002.0)
        cached = jobs_module._gpu_snapshot_cache
        assert cached is not None
        assert cached[0] == 2000.0, (
            "a poll inside the window must not pay the probe again"
        )
        gpu_pressure_snapshot(now=2006.0)
        cached = jobs_module._gpu_snapshot_cache
        assert cached is not None
        assert cached[0] == 2006.0, "the window's end re-runs the probe"

    def test_a_caller_cannot_poison_the_cache(self) -> None:
        """The snapshot handed out is a copy, never the cached mapping.

        Proven able to fail: returning ``cached[1]`` and ``snapshot``
        directly instead of copies hands every caller the cached mapping,
        the mutation below lands in the cache, and the assertion fails by
        name; restored, it passes.
        """
        from .._job_evidence import gpu_pressure_snapshot

        self._reset_cache()
        first = gpu_pressure_snapshot(now=3000.0)
        first["available"] = "poisoned"
        second = gpu_pressure_snapshot(now=3001.0)
        assert second["available"] != "poisoned", (
            "mutating a handed-out snapshot must not rewrite the cache"
        )


class TestJobsRouteGpuExposure:
    """GET /jobs carries the GPU block beside the work list."""

    def test_the_listing_envelope_carries_the_gpu_block(self) -> None:
        from starlette.testclient import TestClient

        from ..server import ServerRouteRuntime, create_http_app
        from ..service import ServiceRegistry

        token = "gpu-exposure-test-token"
        app = create_http_app(
            ServerRouteRuntime(token=token, registry=ServiceRegistry(), port=8765),
            lifespan=None,
        )
        client: httpx.Client = cast("httpx.Client", TestClient(app))
        response: httpx.Response = client.get(
            "/jobs", headers={"Authorization": f"Bearer {token}"}
        )
        payload = _as_map(cast("object", response.json()))
        gpu = _as_map(payload["gpu"])
        assert set(gpu) == _GPU_KEYS, (
            "the polled listing is where the header reads GPU pressure from"
        )


# The measured shape of a tail-throughput collapse: a code index clearing
# most of a 4,703-file corpus at ~13 files/s, then dropping by roughly an
# order of magnitude for the tail while continuing to report normally. The
# reporting cadence is the production one (every few seconds), which is what
# keeps the rate window short and the retained baseline long.
_CORPUS = 4703
_FAST_RATE = 13.3
_COLLAPSED_RATE = 1.9
_REPORT_INTERVAL = 5.0
_ENCODING_STEP = "chunk + embed"


def _replay_rate(
    job_id: str,
    *,
    start_at: float,
    completed: float,
    rate: float,
    seconds: float,
) -> tuple[float, float]:
    """Report real progress at *rate* for *seconds*; return the end state.

    Drives the production reporting path at injected times, so the rate
    window, the retained baseline, and the verdict are all computed by the
    service from progress it actually observed.
    """
    at = start_at
    done = completed
    while at < start_at + seconds:
        at += _REPORT_INTERVAL
        done += rate * _REPORT_INTERVAL
        record_progress(job_id, _ENCODING_STEP, int(done), _CORPUS, now=at)
    return at, done


def _replayed_record(job_id: str) -> dict[str, object]:
    return next(entry for entry in snapshot() if entry["id"] == job_id)


class TestRateBaselineVerdict:
    """A run that collapses against itself is degraded, not healthy.

    The recency inputs cannot see this: a clamped encode stage keeps ticking
    progress, so every age stays fresh while the run delivers a fraction of
    the work it was delivering minutes earlier. These replays drive real
    progress through the real registry and read the service verdict.
    """

    def test_a_collapsed_rate_is_degraded_while_progress_stays_fresh(self) -> None:
        """The incident shape: reporting normally at a tenth of its own rate.

        Mutation check: replacing the final line of ``_job_degradation`` with
        a bare ``return "healthy"`` (dropping the ``_rate_collapsed`` input)
        makes this fail on the ``degradation == "degraded"`` assertion below,
        not on an import or a collection error; restoring it returns to green.
        """
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        record_progress(job_id, _ENCODING_STEP, 0, _CORPUS, now=0.0)
        at, done = _replay_rate(
            job_id,
            start_at=0.0,
            completed=0.0,
            rate=_FAST_RATE,
            seconds=300.0,
        )
        at, done = _replay_rate(
            job_id,
            start_at=at,
            completed=done,
            rate=_COLLAPSED_RATE,
            seconds=120.0,
        )

        record = _replayed_record(job_id)
        now = at + 1.0
        shaped = _job_with_liveness(record, now=now)

        # Every recency input is healthy: the run reported a second ago and
        # is nowhere near either threshold, so the verdict below can only
        # have been earned by the throughput comparison.
        age = shaped["last_progress_age_seconds"]
        assert isinstance(age, float)
        assert age < DEGRADED_THRESHOLD_SECONDS
        assert shaped["stalled"] is False

        assert shaped["degradation"] == "degraded"

        baseline = _as_map(shaped["progress_rate_baseline"])
        assert set(baseline) == _RATE_KEYS
        recent = baseline["recent_per_second"]
        median = baseline["median_per_second"]
        ratio = baseline["ratio"]
        assert isinstance(recent, float)
        assert isinstance(median, float)
        assert isinstance(ratio, float)
        assert recent == pytest.approx(_COLLAPSED_RATE, rel=0.15)
        assert median == pytest.approx(_FAST_RATE, rel=0.15)
        assert ratio <= RATE_COLLAPSE_RATIO

    def test_the_collapse_is_named_in_the_evidence_block(self) -> None:
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        record_progress(job_id, _ENCODING_STEP, 0, _CORPUS, now=0.0)
        at, done = _replay_rate(
            job_id,
            start_at=0.0,
            completed=0.0,
            rate=_FAST_RATE,
            seconds=300.0,
        )
        at, done = _replay_rate(
            job_id,
            start_at=at,
            completed=done,
            rate=_COLLAPSED_RATE,
            seconds=120.0,
        )

        shaped = _job_with_liveness(_replayed_record(job_id), now=at + 1.0)
        evidence = _as_map(shaped["degradation_evidence"])
        rate = _as_map(evidence["rate"])
        assert set(rate) == _RATE_KEYS
        # The evidence must carry the same numbers the projection published,
        # not a second reading taken a moment later.
        assert rate == _as_map(shaped["progress_rate_baseline"])

    def test_a_steady_run_at_the_same_cadence_is_healthy(self) -> None:
        # The control for the replay above: identical reporting, identical
        # recency, no collapse - so the verdict must not fire.
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        record_progress(job_id, _ENCODING_STEP, 0, _CORPUS, now=0.0)
        at, _done = _replay_rate(
            job_id,
            start_at=0.0,
            completed=0.0,
            rate=_FAST_RATE,
            seconds=420.0,
        )

        shaped = _job_with_liveness(_replayed_record(job_id), now=at + 1.0)
        assert shaped["degradation"] == "healthy"
        baseline = _as_map(shaped["progress_rate_baseline"])
        ratio = baseline["ratio"]
        assert isinstance(ratio, float)
        assert ratio == pytest.approx(1.0, rel=0.05)

    def test_a_run_too_young_to_have_a_baseline_declines_to_compare(self) -> None:
        # A median over a handful of observations describes a moment, not a
        # run. Until the service has enough of them it states no baseline,
        # which is what stops one slow stretch early in a run from firing.
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        record_progress(job_id, _ENCODING_STEP, 0, _CORPUS, now=0.0)
        at, done = _replay_rate(
            job_id,
            start_at=0.0,
            completed=0.0,
            rate=_FAST_RATE,
            seconds=120.0,
        )
        at, done = _replay_rate(
            job_id,
            start_at=at,
            completed=done,
            rate=_COLLAPSED_RATE,
            seconds=60.0,
        )

        _recent, median_rate = progress_rates(job_id)
        assert median_rate is None
        shaped = _job_with_liveness(_replayed_record(job_id), now=at + 1.0)
        assert shaped["degradation"] == "healthy"
        baseline = _as_map(shaped["progress_rate_baseline"])
        assert baseline["median_per_second"] is None
        assert baseline["ratio"] is None

    def test_a_changed_step_starts_a_new_baseline(self) -> None:
        # Steps have very different per-unit costs, so a baseline carried
        # from one into the next would report every transition as a collapse.
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        record_progress(job_id, _ENCODING_STEP, 0, _CORPUS, now=0.0)
        at, _done = _replay_rate(
            job_id,
            start_at=0.0,
            completed=0.0,
            rate=_FAST_RATE,
            seconds=300.0,
        )
        _recent, median_rate = progress_rates(job_id)
        assert median_rate is not None

        record_progress(job_id, "write metadata", 0, _CORPUS, now=at + 1.0)
        _recent, median_rate = progress_rates(job_id)
        assert median_rate is None


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
                inputs=DegradationInputs(
                    source="vault",
                    project_root=str(root),
                    step="embed + upsert documents",
                ),
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
                inputs=DegradationInputs(
                    source="vault",
                    project_root=str(root),
                    step="embed + upsert documents",
                ),
            )
            backend_again = _as_map(again["backend"])
            assert backend_again["latency_seconds"] == latency
        finally:
            reset_config()


def test_legacy_terminal_phase_table_covers_every_terminal_phase() -> None:
    # ``jobs.TERMINAL_PHASES`` is derived from the ``Phase`` literal and is
    # documented there as "the sole definition of that set" that deletion,
    # retention, and the read surface all agree on. The read surface's own
    # ``_LEGACY_TERMINAL_PHASES`` translation table restates the same phase
    # spellings as a second, hand-maintained set of keys rather than deriving
    # them - a phase added to ``Phase`` without a matching key here would
    # read as "unknown" (not terminal) through ``job_state`` instead of
    # through whatever alias it should carry.
    assert set(_LEGACY_TERMINAL_PHASES) == TERMINAL_PHASES
