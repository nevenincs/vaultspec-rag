"""Real-behavior coverage for canonical index resilience projections."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from ..cli._service_jobs_presentation import _resilience_summary_lines
from ..job_control import RunControlToken
from ..job_manager._control import AttemptTerminal
from ..job_manager.manager import JobManager
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
from ..service_quiesce import ServiceQuiesceController
from ._job_manager_transition_helpers import pending_attempt

pytestmark = [pytest.mark.unit]

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Literal

    from ..embeddings import EmbeddingModel
    from ..indexer import VaultIndexer
    from ..store_runtime import VaultStore


@pytest.mark.asyncio
async def test_resilience_is_owned_persisted_and_shared_by_status_adapters(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "jobs-state.json"
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=2,
        state_path=state_path,
    )
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
    owner_task = asyncio.create_task(pending_attempt())
    stale_task = asyncio.create_task(pending_attempt())
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
        peak_rss_mib=512.0,
        rss_ceiling_mib=2048.0,
        peak_cuda_allocated_mib=768.0,
        peak_cuda_reserved_mib=896.0,
        cuda_ceiling_mib=4096.0,
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
            "peak_rss_mib": 512.0,
            "rss_ceiling_mib": 2048.0,
            "peak_cuda_allocated_mib": 768.0,
            "peak_cuda_reserved_mib": 896.0,
            "cuda_ceiling_mib": 4096.0,
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
            "RSS high-water / ceiling: 512.0 MiB / 2.0 GiB",
            "CUDA allocated high-water: 768.0 MiB",
            "CUDA reserved high-water / ceiling: 896.0 MiB / 4.0 GiB",
            "Index outcome: incomplete",
        )

        assert (
            manager.finish_attempt(
                created.job.id,
                AttemptTerminal(
                    attempt=1,
                    task=owner_task,
                    state=JobState.FAILED,
                    result="bounded failure",
                ),
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

        restarted = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            state_path=state_path,
        )
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
        IndexResilienceSnapshot(peak_rss_mib=float("inf"))
    with pytest.raises(ValueError):
        IndexResilienceSnapshot(cuda_ceiling_mib=-0.5)


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
            "peak_rss_mib": 1215.52734375,
            "rss_ceiling_mib": 1940.5,
            "peak_cuda_allocated_mib": 1363.827,
            "peak_cuda_reserved_mib": 1368.0,
            "cuda_ceiling_mib": 1366.001,
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
        "peak_rss_mib",
        "rss_ceiling_mib",
        "peak_cuda_allocated_mib",
        "peak_cuda_reserved_mib",
        "cuda_ceiling_mib",
        "support_profile",
        "terminal_outcome",
        "remediation",
    }
    # Rounded to one-decimal operator precision, the same the CLI renders.
    assert shaped["peak_rss_mib"] == 1215.5
    assert shaped["no_progress_remaining_seconds"] == 12.4
    assert shaped["cuda_ceiling_mib"] == 1366.0
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


def test_budget_enforces_captured_job_peak_not_process_global_counter() -> None:
    """Cross-job contamination guard for CUDA ceiling enforcement.

    A checkpoint must enforce the job's own lock-bracketed forward peak,
    never a process-global reading that spans concurrent jobs. The readings
    below play a sibling's mid-flight forward (far above this job's ceiling);
    the assertion is narrow on purpose - it catches the mutation that
    re-points the enforced peak at any process-wide counter, which raises
    ``cuda_memory_ceiling`` here despite this job's own demand sitting well
    under its ceiling.

    The readings are stated rather than measured: what a given reading must
    mean for enforcement does not depend on a machine presenting it, and
    ``sample`` is exactly this call preceded by the two probes.
    """
    from ..memory_probe import MemoryBudget

    sibling = MemoryBudget(cuda_ceiling_mib=20000.0)
    sibling.record_forward_peak_mib(9000.0)
    budget = MemoryBudget(cuda_ceiling_mib=1000.0)
    budget.record_forward_peak_mib(500.0)
    # The field failure mode: a non-forward checkpoint taken while a
    # sibling holds the GPU. It must be admitted.
    snapshot = budget.sample_readings(
        label="code producer queue wait",
        rss_mib=100.0,
        cuda_mib=(9000.0, 9500.0),
    )

    # Enforced peak is the job's own captured maximum...
    assert snapshot.peak_cuda_allocated_mib == 500.0
    # ...while the process-global reading stays visible as a diagnostic.
    assert snapshot.cuda_allocated_mib == 9000.0
    assert snapshot.cuda_reserved_mib == 9500.0


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
    from ..config._settings import get_config
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


def test_forward_peak_routes_to_thread_recorder_and_keeps_maximum() -> None:
    """A captured peak reaches the capturing thread's recorder, max-wins.

    Guards two narrow properties: a capture taken outside
    ``record_forward_peaks`` must be dropped (no recorder registered on
    the thread) rather than credited to whichever recorder ran last, and a
    later smaller forward must not shrink the job's accumulated maximum.

    The readings are stated rather than measured: what a given reading must
    mean for attribution does not depend on a machine presenting it, and
    the capture bracket is exactly this call preceded by the two allocator
    probes.

    Proven able to fail: dropping the restore that ``record_forward_peaks``
    performs on exit leaves the departed job's recorder installed on the
    thread, so the orphan 9999.0 reading finds an owner and the assertion
    that it was dropped reports True against False. Restored, it passes.
    """
    from ..memory_probe import (
        MemoryBudget,
        record_forward_peaks,
        route_forward_peak_mib,
    )

    budget = MemoryBudget(cuda_ceiling_mib=1000.0)
    with record_forward_peaks(budget.record_forward_peak_mib):
        assert route_forward_peak_mib(321.5) is True
        # A later, smaller forward must not shrink the job maximum.
        assert route_forward_peak_mib(100.0) is True
    assert budget.captured_cuda_peak_mib == 321.5

    # Outside the recorder context a capture has nowhere to go and
    # must be dropped rather than credited to a stale recorder.
    assert route_forward_peak_mib(9999.0) is False
    assert budget.captured_cuda_peak_mib == 321.5


def test_unreadable_forward_peak_is_dropped_quietly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A miss is a miss: neither arm of the drop may raise an alarm.

    Two readings have no owner to credit - an allocator that transiently
    refused the read, and a capture taken on a thread with no recorder
    registered. Both already credit nothing. What the guard buys is
    silence: routed on regardless, each arrives at the failure branch and
    logs a warning once per forward, drowning the operator in an alarm
    about components that are working. The assertions are therefore on the
    log, since the return value is False under every form.

    Proven able to fail: dropping either arm of the guard sends that
    reading into the branch it was meant to skip - a rejected reading for
    the ``None`` peak, an uncallable recorder for the orphan - and the
    warning fires, failing the assertion that nothing was logged. Restored,
    both pass.
    """
    from ..memory_probe import (
        MemoryBudget,
        record_forward_peaks,
        route_forward_peak_mib,
    )

    budget = MemoryBudget(cuda_ceiling_mib=1000.0)
    with caplog.at_level(logging.WARNING, logger="vaultspec_rag.memory_probe"):
        with record_forward_peaks(budget.record_forward_peak_mib):
            assert route_forward_peak_mib(444.0) is True
            assert route_forward_peak_mib(None) is False
        assert route_forward_peak_mib(777.0) is False

    assert caplog.records == []
    assert budget.captured_cuda_peak_mib == 444.0


def _vault_indexer_for_telemetry(root: Path) -> VaultIndexer:
    """Build a real indexer; the telemetry seam reads neither model nor store."""
    from ..indexer import VaultIndexer

    return VaultIndexer(
        root,
        cast("EmbeddingModel", None),
        cast("VaultStore", None),
    )


def test_vault_run_registers_a_forward_recorder_and_publishes_a_snapshot(
    tmp_path: Path,
) -> None:
    """A vault run must publish the same snapshot attribute its siblings do.

    Before this wiring the vault indexer carried no budget at all, so a
    vault job's peak was unobservable in the field. The two assertions are
    separate on purpose: registering the recorder is what makes the encode
    path's already-existing capture bracket credit its peaks to this run,
    and publishing the snapshot is what lets the dispatcher read them.

    ``route_forward_peak_mib`` is the exact call the production capture
    bracket makes on exit, so driving it here exercises the real routing
    rather than a stand-in for it.

    Proven able to fail: dropping the ``record_forward_peaks`` wrapper from
    ``_memory_telemetry`` leaves no recorder on the thread, the routing call
    returns False, and this fails on the ``is True`` assertion. Dropping the
    ``_sample_memory`` calls leaves the snapshot ``None`` and it fails on
    ``snapshot is not None``.
    """
    from ..memory_probe import route_forward_peak_mib

    indexer = _vault_indexer_for_telemetry(tmp_path)
    assert indexer.memory_budget_snapshot is None

    with indexer._memory_telemetry():
        assert route_forward_peak_mib(4321.5) is True

    snapshot = indexer.memory_budget_snapshot
    assert snapshot is not None
    assert snapshot.label == "after vault dispatch"
    budget = indexer._memory_budget
    assert budget is not None
    assert budget.captured_cuda_peak_mib == 4321.5
    # RSS is genuinely measured here, so assert a real reading was taken
    # rather than a specific number.
    assert snapshot.rss_available is True
    assert snapshot.peak_rss_mib > 0.0

    # The recorder must not outlive the run, or a later unrelated forward
    # would be credited to a finished vault job.
    assert route_forward_peak_mib(999.0) is False


def test_vault_memory_telemetry_admits_no_ceiling_and_cannot_fail_a_run(
    tmp_path: Path,
) -> None:
    """Observe-only guard: vault telemetry must never terminate a run.

    The vault run has no support-profile limits and, before this telemetry,
    no way to be killed for memory. Publishing a peak must not change that.
    A budget carrying a ceiling would classify a large reading as a typed
    failure and latch it, so a run that previously completed would die - and
    it would die precisely on the large-corpus runs the peak exists to
    watch. The assertion is that neither admitted ceiling is present and
    that an absurd reading is still admitted.

    Proven able to fail: constructing the budget in ``_memory_telemetry``
    with any ``rss_ceiling_mib`` or ``cuda_ceiling_mib`` makes the reading
    below cross it, ``sample_readings`` raises ``JobError``, and this fails
    on that raise before reaching its assertions.
    """
    indexer = _vault_indexer_for_telemetry(tmp_path)

    with indexer._memory_telemetry():
        budget = indexer._memory_budget
        assert budget is not None
        assert budget.rss_ceiling_mib is None
        assert budget.cuda_ceiling_mib is None
        # Far above any plausible host or device ceiling; must be admitted.
        snapshot = budget.sample_readings(
            label="vault absurd reading",
            rss_mib=4_000_000.0,
            cuda_mib=(3_000_000.0, 3_500_000.0),
        )

    assert snapshot.rss_ceiling_mib is None
    assert snapshot.cuda_ceiling_mib is None
    assert snapshot.peak_rss_mib == 4_000_000.0


def test_vault_resilience_projects_observed_peaks_without_ceilings(
    tmp_path: Path,
) -> None:
    """The dispatcher projection carries peaks and claims no ceiling.

    The vault domain has no support-profile entry, so reporting a ceiling
    here could only mean borrowing another domain's, and the vault run has
    no checkpoint, so claiming one would be equally false. The projection
    must carry the three measured peaks and leave both groups absent.

    Proven able to fail: routing ``_vault_resilience`` through
    ``_admitted_resilience(JobSource.VAULT)`` populates ``cuda_ceiling_mib``
    and ``support_profile`` with the document domain's values, failing the
    ``is None`` assertions that name them.
    """
    from ..job_dispatch import _vault_resilience
    from ..memory_probe import MemoryBudget

    indexer = _vault_indexer_for_telemetry(tmp_path)
    budget = MemoryBudget()
    budget.record_forward_peak_mib(13_074.0)
    budget.sample_readings(
        label="after vault dispatch",
        rss_mib=2_048.0,
        cuda_mib=(12_000.0, 12_500.0),
    )
    indexer._memory_budget = budget

    resilience = _vault_resilience(indexer)

    assert resilience.peak_rss_mib == 2_048.0
    assert resilience.peak_cuda_allocated_mib == 13_074.0
    assert resilience.peak_cuda_reserved_mib == 12_500.0
    # No admitted ceiling is claimed for a domain that has no limits.
    assert resilience.rss_ceiling_mib is None
    assert resilience.cuda_ceiling_mib is None
    assert resilience.support_profile is None
    # No checkpoint exists for a vault run, so none is claimed.
    assert resilience.generation_id is None
    assert resilience.checkpoint_compatible is None


def test_vault_resilience_is_empty_before_any_observation(tmp_path: Path) -> None:
    """A vault run that observed nothing must project an empty snapshot."""
    from ..job_dispatch import _vault_resilience

    indexer = _vault_indexer_for_telemetry(tmp_path)

    assert _vault_resilience(indexer) == IndexResilienceSnapshot()


def test_resilience_domain_maps_only_the_profiled_sources() -> None:
    """The source-to-domain mapping is total and refuses what it cannot map.

    Only code and document have support-profile entries, so any other source
    has no admitted limits at all. Both mapped sources are asserted here
    because the snapshot cannot check them: code and document carry
    identical ceilings in every shipped profile, so swapping the two arms is
    invisible downstream and only the domain identity can catch it.

    Proven able to fail: replacing the body with the two-way fallback
    ``IndexDomain.CODE if source is JobSource.CODE else IndexDomain.DOCUMENT``
    returns ``IndexDomain.DOCUMENT`` for both unmapped sources, and this
    fails inside the ``pytest.raises`` block with DID NOT RAISE. Swapping
    the two mapped arms instead fails the first identity assertion above.
    """
    from ..index_profiles import IndexDomain
    from ..job_dispatch import _resilience_domain

    assert _resilience_domain(JobSource.CODE) is IndexDomain.CODE
    assert _resilience_domain(JobSource.DOCUMENT) is IndexDomain.DOCUMENT

    for unmapped in (JobSource.VAULT, JobSource.MAINTENANCE):
        # The checker rejects this call outright; the cast reproduces the
        # only way the refusal is reachable at all - a caller that got past
        # it - and the message must name the source that arrived.
        with pytest.raises(AssertionError, match=unmapped.value):
            _resilience_domain(cast("Literal[JobSource.CODE]", unmapped))


def test_admitted_resilience_refuses_a_source_with_no_admitted_limits() -> None:
    """Admission must never stamp another domain's ceilings onto a source.

    The failure this guards is silent by construction: the snapshot carries
    a real profile name and plausible ceilings, so a source that borrowed
    them reads exactly like one that owns them.

    Proven able to fail: restoring the two-way fallback in
    ``_resilience_domain`` makes this return a populated snapshot carrying
    the document domain's ``cuda_ceiling_mib`` and ``support_profile``, and
    this fails inside the ``pytest.raises`` block with DID NOT RAISE.
    """
    from ..job_dispatch import _admitted_resilience

    admitted = _admitted_resilience(JobSource.CODE)
    assert admitted.support_profile is not None

    with pytest.raises(AssertionError, match="vault"):
        _admitted_resilience(cast("Literal[JobSource.CODE]", JobSource.VAULT))
