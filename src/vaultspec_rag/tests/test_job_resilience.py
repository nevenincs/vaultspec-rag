"""Real-behavior coverage for canonical index resilience projections."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from ..cli._service_jobs import _resilience_summary_lines
from ..job_control import RunControlToken
from ..job_manager import JobManager
from ..job_models import (
    IndexResilienceSnapshot,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)
from ..jobs import index_job_status

pytestmark = [pytest.mark.unit]

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_resilience_is_owned_persisted_and_shared_by_status_adapters(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "jobs-state.json"
    manager = JobManager(max_nonterminal=2, state_path=state_path)
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.REBUILD,
        ),
        JobInitiator("cli", "server job create", str(tmp_path)),
    )
    assert created.job is not None
    owner_task = asyncio.create_task(asyncio.Event().wait())
    stale_task = asyncio.create_task(asyncio.Event().wait())
    resilience = IndexResilienceSnapshot(
        generation_id="generation-7",
        committed_units=41,
        replayed_units=13,
        checkpoint_compatible=True,
        last_durable_progress_at=1_722_000_000.0,
        no_progress_timeout_seconds=300.0,
        no_progress_remaining_seconds=287.5,
        circuit_state="closed",
        next_retry_at=1_722_000_060.0,
        peak_rss_mb=512.0,
        rss_ceiling_mb=2048.0,
        peak_cuda_allocated_mb=768.0,
        peak_cuda_reserved_mb=896.0,
        cuda_ceiling_mb=4096.0,
        support_profile="standard",
        terminal_outcome="incomplete",
    )
    try:
        assert (
            manager.start_attempt(
                created.job.id,
                task=owner_task,
                control=RunControlToken(),
            ).code
            == "attempt_started"
        )
        assert not manager.update_resilience(
            created.job.id,
            task=stale_task,
            resilience=resilience,
        )
        assert manager.update_resilience(
            created.job.id,
            task=owner_task,
            resilience=resilience,
        )

        owned = manager.get(created.job.id)
        assert owned is not None
        canonical = cast("dict[str, object]", owned.to_dict()["resilience"])
        assert canonical == {
            "generation_id": "generation-7",
            "committed_units": 41,
            "replayed_units": 13,
            "checkpoint_compatible": True,
            "last_durable_progress_at": 1_722_000_000.0,
            "no_progress_timeout_seconds": 300.0,
            "no_progress_remaining_seconds": 287.5,
            "circuit_state": "closed",
            "next_retry_at": 1_722_000_060.0,
            "peak_rss_mb": 512.0,
            "rss_ceiling_mb": 2048.0,
            "peak_cuda_allocated_mb": 768.0,
            "peak_cuda_reserved_mb": 896.0,
            "cuda_ceiling_mb": 4096.0,
            "support_profile": "standard",
            "terminal_outcome": "incomplete",
        }
        sources = cast(
            "dict[str, object]",
            index_job_status(tmp_path, manager=manager)["sources"],
        )
        domain = cast("dict[str, object]", sources["code"])
        assert domain["resilience"] == canonical
        assert _resilience_summary_lines(owned.to_dict()) == (
            "Index profile: standard",
            "Checkpoint generation: generation-7",
            "Checkpoint compatible: yes",
            "Checkpoint units: 41 committed, 13 resumed",
            "No-progress budget remaining: 4 minutes 47 seconds",
            "Retry circuit: closed",
            "Next retry: 2024-07-26 13:21:00 UTC",
            "RSS high-water / ceiling: 512.0 MB / 2048.0 MB",
            "CUDA allocated high-water: 768.0 MB",
            "CUDA reserved high-water / ceiling: 896.0 MB / 4096.0 MB",
            "Index outcome: incomplete",
        )

        assert (
            manager.finish_attempt(
                created.job.id,
                attempt=1,
                task=owner_task,
                state=JobState.FAILED,
                result="bounded failure",
            ).code
            == "job_finished"
        )
        settled_resilience = replace(
            resilience,
            circuit_state="open",
            next_retry_at=1_722_000_120.0,
            terminal_outcome="failed",
        )
        assert not manager.update_terminal_resilience(
            created.job.id,
            attempt=2,
            resilience=settled_resilience,
        )
        assert manager.update_terminal_resilience(
            created.job.id,
            attempt=1,
            resilience=settled_resilience,
        )

        restarted = JobManager(max_nonterminal=2, state_path=state_path)
        assert restarted.restore_persisted().code == "job_state_restored"
        restored = restarted.get(created.job.id)
        assert restored is not None
        assert restored.state is JobState.FAILED
        assert restored.resilience == settled_resilience
    finally:
        owner_task.cancel()
        stale_task.cancel()
        for task in (owner_task, stale_task):
            with pytest.raises(asyncio.CancelledError):
                await task


def test_resilience_rejects_invalid_operability_values() -> None:
    with pytest.raises(ValueError):
        IndexResilienceSnapshot(committed_units=True)
    with pytest.raises(ValueError):
        IndexResilienceSnapshot(replayed_units=-1)
    with pytest.raises(ValueError):
        IndexResilienceSnapshot(peak_rss_mb=float("inf"))
    with pytest.raises(ValueError):
        IndexResilienceSnapshot(cuda_ceiling_mb=-0.5)


def test_route_shaping_bounds_rounds_and_derives_remediation() -> None:
    """The REST job response shapes resilience explicitly, not by pass-through.

    The broker-facing job collection and detail responses must not leak
    the raw snapshot. The shaper names each field (so a field added to the
    snapshot later cannot leak without a deliberate change), rounds the
    megabyte and second measures to operator precision, and derives a
    remediation hint from the terminal outcome.
    """
    from ..server._routes_jobs import _job_resilience

    record: dict[str, object] = {
        "resilience": {
            "generation_id": "gen-1",
            "committed_units": 5,
            "replayed_units": 2,
            "checkpoint_compatible": True,
            "last_durable_progress_at": 1784.5,
            "no_progress_timeout_seconds": 30.049,
            "no_progress_remaining_seconds": 12.371,
            "circuit_state": "closed",
            "next_retry_at": None,
            "peak_rss_mb": 1215.52734375,
            "rss_ceiling_mb": 1940.5,
            "peak_cuda_allocated_mb": 1363.827,
            "peak_cuda_reserved_mb": 1368.0,
            "cuda_ceiling_mb": 1366.001,
            "support_profile": "managed-service",
            "terminal_outcome": "cuda_memory_ceiling",
            # A field the snapshot might grow later must not reach the broker.
            "an_internal_field_added_later": "must-not-leak",
        }
    }

    shaped = _job_resilience(record)
    assert shaped is not None
    # Bounded: only the named canonical fields plus the derived remediation.
    assert "an_internal_field_added_later" not in shaped
    assert set(shaped) == {
        "generation_id",
        "committed_units",
        "replayed_units",
        "checkpoint_compatible",
        "last_durable_progress_at",
        "no_progress_timeout_seconds",
        "no_progress_remaining_seconds",
        "circuit_state",
        "next_retry_at",
        "peak_rss_mb",
        "rss_ceiling_mb",
        "peak_cuda_allocated_mb",
        "peak_cuda_reserved_mb",
        "cuda_ceiling_mb",
        "support_profile",
        "terminal_outcome",
        "remediation",
    }
    # Rounded to one-decimal operator precision, the same the CLI renders.
    assert shaped["peak_rss_mb"] == 1215.5
    assert shaped["no_progress_remaining_seconds"] == 12.4
    assert shaped["cuda_ceiling_mb"] == 1366.0
    # State the operator reads unrounded is preserved exactly.
    assert shaped["generation_id"] == "gen-1"
    assert shaped["committed_units"] == 5
    assert shaped["circuit_state"] == "closed"
    # Remediation is derived from the terminal outcome so a broker can act.
    assert isinstance(shaped["remediation"], str)
    assert shaped["remediation"]


def test_route_shaping_is_absent_when_no_resilience_recorded() -> None:
    """A record without a resilience snapshot yields no shaped block."""
    from ..server._routes_jobs import _job_resilience

    assert _job_resilience({}) is None
    assert _job_resilience({"resilience": None}) is None


def test_budget_enforces_captured_job_peak_not_process_global_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-job contamination guard for CUDA ceiling enforcement.

    A checkpoint must enforce the job's own lock-bracketed forward peak,
    never a process-global reading that spans concurrent jobs. The patched
    live measurement plays a sibling's mid-flight forward (far above this
    job's ceiling); the assertion is narrow on purpose - it catches the
    mutation that re-points ``sample``'s enforced peak at any process-wide
    counter, which raises ``cuda_memory_ceiling`` here despite this job's
    own demand sitting well under its ceiling.
    """
    from .. import memory_probe
    from ..memory_probe import MemoryBudget

    monkeypatch.setattr(memory_probe, "_measure_rss_mb", lambda: 100.0)
    # A sibling job's forward is in flight at checkpoint time: the
    # process-global allocated reading dwarfs this job's ceiling.
    monkeypatch.setattr(
        memory_probe,
        "_measure_cuda_mb",
        lambda: (9000.0, 9500.0),
    )
    sibling = MemoryBudget(cuda_ceiling_mb=20000.0)
    sibling.record_forward_peak_mb(9000.0)
    budget = MemoryBudget(cuda_ceiling_mb=1000.0)
    budget.record_forward_peak_mb(500.0)
    # The field failure mode: a non-forward checkpoint taken while a
    # sibling holds the GPU. It must be admitted.
    snapshot = budget.sample("code producer queue wait")

    # Enforced peak is the job's own captured maximum...
    assert snapshot.peak_cuda_allocated_mb == 500.0
    # ...while the process-global reading stays visible as a diagnostic.
    assert snapshot.cuda_allocated_mb == 9000.0
    assert snapshot.cuda_reserved_mb == 9500.0


def test_runtime_cuda_peak_is_not_a_corpus_rejection_dimension() -> None:
    """Corpus-admission guard: a runtime CUDA peak must never reject.

    The code indexer projects the runtime allocated high-water into the
    measurement's ``cuda_bytes`` and republishes it through
    ``exceeded_by``. That value is runtime demand, owned by the per-job
    ceiling and forward-peak capture - not corpus size. The first
    assertion is the one that catches the mutation re-adding
    ``cuda_bytes`` to ``exceeded_by``'s rejection set: under that form a
    peak above the profile figure is refused as corpus_limit_exceeded.
    """
    from ..config import get_config
    from ..index_profiles import (
        SupportMeasurement,
        get_index_support_profile,
    )

    limits = get_index_support_profile(get_config().index_support_profile).code
    over_peak = SupportMeasurement(
        source_files=1,
        source_bytes=1,
        cuda_bytes=limits.cuda_bytes + 1,
    )
    assert limits.exceeded_by(over_peak) is None

    # The neighbouring dimensions still reject in their stable order.
    over_rss = SupportMeasurement(
        source_files=1,
        source_bytes=1,
        rss_bytes=limits.rss_bytes + 1,
        cuda_bytes=limits.cuda_bytes + 1,
    )
    exceeded = limits.exceeded_by(over_rss)
    assert exceeded is not None
    assert exceeded[0] == "rss_bytes"


def test_forward_peak_capture_routes_to_thread_recorder_and_keeps_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The capture bracket feeds the registered recorder, max across brackets.

    Guards two narrow properties: a bracket outside ``record_forward_peaks``
    must drop its capture (no recorder registered on the thread), and a
    later smaller bracket must not shrink the job's accumulated maximum.
    """
    from .. import memory_probe
    from ..memory_probe import (
        MemoryBudget,
        cuda_forward_peak_capture,
        record_forward_peaks,
    )

    monkeypatch.setattr(memory_probe, "_reset_cuda_peak_stats_bare", lambda: True)
    monkeypatch.setattr(
        memory_probe,
        "_read_cuda_peak_allocated_mb",
        lambda: 321.5,
    )
    budget = MemoryBudget(cuda_ceiling_mb=1000.0)
    with (
        record_forward_peaks(budget.record_forward_peak_mb),
        cuda_forward_peak_capture(),
    ):
        pass
    assert budget.captured_cuda_peak_mb == 321.5

    # A later, smaller forward must not shrink the job maximum.
    monkeypatch.setattr(
        memory_probe,
        "_read_cuda_peak_allocated_mb",
        lambda: 100.0,
    )
    with (
        record_forward_peaks(budget.record_forward_peak_mb),
        cuda_forward_peak_capture(),
    ):
        pass
    assert budget.captured_cuda_peak_mb == 321.5

    # Outside the recorder context a capture has nowhere to go and
    # must be dropped rather than credited to a stale recorder.
    monkeypatch.setattr(
        memory_probe,
        "_read_cuda_peak_allocated_mb",
        lambda: 9999.0,
    )
    with cuda_forward_peak_capture():
        pass
    assert budget.captured_cuda_peak_mb == 321.5
