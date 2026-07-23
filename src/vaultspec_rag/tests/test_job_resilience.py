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

    S33: the broker-facing job collection and detail responses must not leak
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
