"""Restarted readiness retains only receipt-free, generation-fenced authority."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, cast

import pytest

from .. import _publication_state, store_schema
from .._index_integrity import (
    IntegrityVerdict,
    acquire_index_integrity_snapshot_if_proven,
)
from .._public_search import _combined_source_fact
from .._search_state import AbsenceAuthority, FreshnessWaitPolicy, SearchFreshness
from .._source_types import INDEX_SOURCES, PublicSourceType
from .._store_writes import workspace_volume_path
from ..indexer._document_checkpoint import DocumentRunCheckpoint
from ..indexer._document_indexer import DocumentIndexer
from ..indexer._run_ledger_models import (
    RunAuthority,
    RunOperation,
    RunTerminalState,
    index_run_ledger_path,
)
from ..indexer._run_ledger_runtime import RunLedger
from ..indexer._run_policy import RunPolicy
from ..job_control import PauseRequested, RunControlToken
from ..job_manager.manager import JobManager
from ..job_models import (
    DesiredJobState,
    IndexResilienceSnapshot,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)
from ..server import _routes
from ..server._routes_search import SearchRequest, _admit_requested_freshness
from ..server._search_route_availability import (
    SearchAvailabilityRequestFacts,
    SearchIndexStateInput,
    classify_search_result,
    readiness_snapshot,
    search_index_state_for_route,
)
from ..service import ServiceRegistry
from ..service_quiesce import ServiceQuiesceController
from ..store_runtime import configured_backend_identity
from ._job_manager_transition_helpers import pending_attempt
from ._run_ledger_test_support import (
    ledger_test_proof_key_for_signature,
    ledger_test_publish_and_compact,
    ledger_test_seed_publication_proof,
    ledger_test_signature,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .._source_types import IndexSource
    from ..embeddings import EmbeddingModel
    from ..indexer._publication_proof import ProofCompatibilityKey, ProofEvidence
    from ..indexer._run_ledger_models import RunSignature
    from ..store_runtime import VaultStore

pytestmark = pytest.mark.unit


def _published(
    root: Path,
    source: IndexSource,
    *,
    evidence: tuple[ProofEvidence, ...] = (),
    incompatible: str | None = None,
) -> tuple[RunLedger, RunSignature, ProofCompatibilityKey, str]:
    root = root.resolve()
    path = index_run_ledger_path(workspace_volume_path(root))
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger = RunLedger(path)
    collections = {
        "code": store_schema.CODE_COLLECTION,
        "vault": store_schema.VAULT_COLLECTION,
        "document": store_schema.DOCUMENT_COLLECTION,
    }
    signature = replace(
        ledger_test_signature(root, backend_identity=configured_backend_identity(root)),
        source_type=PublicSourceType(source),
        collection_identity=collections[source],
        payload_schema=store_schema.STORAGE_SCHEMA_VERSION,
    )
    generation = ledger.start_generation(signature)
    ledger_test_publish_and_compact(ledger, generation.generation_id)
    key = ledger_test_proof_key_for_signature(signature)
    changes: dict[str, object] = {
        "root_identity": str(root / "other-root"),
        "backend_identity": "other-backend",
        "collection_identity": "other-collection",
        "source_type": PublicSourceType.VAULT,
        "storage_schema": store_schema.STORAGE_SCHEMA_VERSION - 1,
        "payload_schema": store_schema.STORAGE_SCHEMA_VERSION - 1,
    }
    if incompatible is not None:
        key = replace(key, **{incompatible: changes[incompatible]})
    ledger_test_seed_publication_proof(
        ledger, generation_id=generation.generation_id, key=key, evidence=evidence
    )
    return ledger, signature, key, generation.generation_id


def _registry() -> ServiceRegistry:
    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    return registry


def _no_jobs() -> list[dict[str, object]]:
    return []


def _empty_result(root: Path, source: IndexSource) -> dict[str, object]:
    integrity = acquire_index_integrity_snapshot_if_proven(
        root, PublicSourceType(source)
    ).finish(0)
    return {
        "results": [],
        "index_state": search_index_state_for_route(
            SearchIndexStateInput(
                indexed_count=0,
                requested_root=root,
                search_type=source,
                integrity=integrity,
            )
        ),
    }


@pytest.mark.parametrize("source", INDEX_SOURCES)
async def test_restart_restores_verified_empty_concrete_and_combined_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: IndexSource
) -> None:
    _, _, _, generation = _published(tmp_path, source)
    monkeypatch.setattr(_routes, "canonical_job_snapshot", _no_jobs)
    registry = _registry()
    try:
        snapshot = readiness_snapshot(registry, tmp_path, source)
        assert snapshot is not None
        # Mutation: bypassing durable restoration leaves this source unknown.
        assert snapshot.published_generation == generation, "restore durable generation"
        assert snapshot.publication_revision == 0
        assert snapshot.controller_revision is None
        facts = SearchAvailabilityRequestFacts(
            [], tmp_path, source, "restart-empty", None, readiness_snapshot=snapshot
        )
        result = _empty_result(tmp_path, source)
        classified = classify_search_result(result, facts)
        # Mutation: removing the canonical served-target fallback loses absence.
        assert classified.status_code == 200, "verified empty remains successful"
        assert (
            classified.source_fact.absence_authority is AbsenceAuthority.AUTHORITATIVE
        )
        assert classified.response["empty"] == {
            "reason": "published_empty",
            "message": f"The published {source} index is empty.",
            "remediation": [],
        }
        observation = acquire_index_integrity_snapshot_if_proven(
            tmp_path, PublicSourceType(source)
        ).finish(0)
        combined = _combined_source_fact(
            tmp_path,
            PublicSourceType(source),
            registry,
            observation=observation,
            job_snapshot=[],
        )
        assert combined.absence_authority is AbsenceAuthority.AUTHORITATIVE, (
            "combined constituent uses the served-target fallback"
        )
    finally:
        registry.readiness_registry.close()


@pytest.mark.parametrize("source", [*INDEX_SOURCES, "combined"])
async def test_restart_bounded_admission_is_already_satisfied(
    tmp_path: Path, source: str
) -> None:
    for concrete in INDEX_SOURCES:
        _published(tmp_path, concrete)
    registry = _registry()
    try:
        admission = await _admit_requested_freshness(
            SearchRequest(
                tmp_path,
                "empty",
                1,
                {},
                PublicSourceType(source),
                "restart-bounded",
                freshness_policy=FreshnessWaitPolicy.BOUNDED,
                freshness_wait_seconds=0,
            ),
            registry,
        )
        assert admission.outcome == "satisfied", "restored bounded target is satisfied"
        assert registry.readiness_registry._observers == {}
        assert all(target.revision == 0 for target in admission.targets)
    finally:
        registry.readiness_registry.close()


async def test_restored_baseline_cannot_satisfy_a_newer_controller_target(
    tmp_path: Path,
) -> None:
    _, _, _, generation = _published(tmp_path, "document")
    registry = _registry()
    readiness = registry.readiness_registry
    try:
        pending = readiness.notify_controller(tmp_path, "document")
        snapshot = readiness.snapshot(tmp_path, "document")
        assert snapshot.published_generation == generation
        assert snapshot.controller_revision == pending.controller_revision
        target = snapshot.publication_target()
        assert target is not None
        # Mutation: promoting hydration to the controller revision falsely wins.
        assert not await readiness.published_at_least((target,), timeout_seconds=0), (
            "restoration must not satisfy a newer controller target"
        )
        assert snapshot.publication_revision == 0
        result = _empty_result(tmp_path, "document")
        state = cast("dict[str, object]", result["index_state"])
        facts = SearchAvailabilityRequestFacts(
            [], tmp_path, "document", "pending", None, readiness_snapshot=snapshot
        )
        assert not facts.to_context(
            after_snapshot=[], index_state=state
        ).canonical_evidence.desired_generation
        readiness.publish_next(tmp_path, "document", generation="new-publication")
        assert await readiness.published_at_least((target,), timeout_seconds=0)
    finally:
        readiness.close()


@pytest.mark.parametrize("source", INDEX_SOURCES)
async def test_noop_publication_callback_keeps_the_parent_proof_identity(
    tmp_path: Path,
    source: IndexSource,
) -> None:
    ledger, signature, key, parent = _published(tmp_path, source)
    registry = _registry()
    readiness = registry.readiness_registry
    try:
        readiness.snapshot(tmp_path, source)
        pending = readiness.notify_controller(tmp_path, source).publication_target()
        assert pending is not None
        successor = ledger.start_generation(signature)
        receipt = ledger.reserve_publication_receipt(
            key,
            successor.generation_id,
            expected_parent_revision=ledger.publication_proof(key).revision,
        )
        # The canonical no-op receipt closes without advancing the proof.
        ledger.begin_publication_rollback(receipt.receipt_id)
        ledger.roll_back_publication_receipt(receipt.receipt_id, compensated_units=())
        ledger_test_publish_and_compact(ledger, successor.generation_id)
        assert ledger.publication_proof(key).generation_id == parent
        notified = ServiceRegistry._publish_readiness(
            readiness, JobSource(source), tmp_path, successor.generation_id
        )
        assert notified is not None
        # Mutation: forwarding the completed attempt ID loses served identity.
        assert notified.published_generation == parent, (
            "no-op keeps served proof identity"
        )
        assert await readiness.published_at_least((pending,), timeout_seconds=0)
    finally:
        readiness.close()


async def test_resumed_document_noop_waits_for_actual_parent_publication(
    tmp_path: Path,
) -> None:
    ledger, signature, key, parent = _published(tmp_path, "document")
    registry = _registry()
    readiness = registry.readiness_registry
    readiness.snapshot(tmp_path, "document")
    child = ledger.start_generation(
        replace(signature, operation=RunOperation.INCREMENTAL)
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        child.generation_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )
    checkpoint = DocumentRunCheckpoint(
        ledger,
        child,
        None,
        RunPolicy(no_progress_timeout_seconds=60),
        RunAuthority.PUBLICATION,
        receipt,
    )
    indexer = DocumentIndexer(
        tmp_path,
        cast("EmbeddingModel", None),
        cast("VaultStore", None),
        publish_readiness=partial(
            ServiceRegistry._publish_readiness, readiness, JobSource.DOCUMENT
        ),
    )
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        state_path=tmp_path / "jobs.json",
        on_controller_target=partial(
            ServiceRegistry._notify_controller_target, readiness
        ),
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.DOCUMENT,
            str(tmp_path),
            JobMode.INCREMENTAL,
            RunAuthority.PUBLICATION,
        ),
        JobInitiator("test", "resumed-document-noop", str(tmp_path)),
    )
    assert created.job is not None
    job_id = created.job.id
    task = asyncio.create_task(pending_attempt())
    control = RunControlToken()
    try:
        started = manager.start_attempt(job_id, task=task, control=control)
        assert started.job is not None
        assert manager.update_resilience(
            job_id,
            task=task,
            resilience=IndexResilienceSnapshot(generation_id=checkpoint.generation_id),
        )
        assert (
            manager.set_desired_state(job_id, DesiredJobState.PAUSED).code
            == "pause_requested"
        )
        with pytest.raises(PauseRequested):
            control.checkpoint()
        paused = manager.acknowledge_control(
            job_id, attempt=started.job.attempt.number, task=task
        )
        assert paused.job is not None and paused.job.state is JobState.PAUSED
        resumed = manager.set_desired_state(job_id, DesiredJobState.RUNNING)
        assert resumed.job is not None and resumed.job.resilience is not None
        assert resumed.job.resilience.generation_id == child.generation_id
        target = readiness.snapshot(tmp_path, "document").publication_target()
        assert target is not None and target.revision > 0
        # Mutation: using the attempt identity poisons a legitimate no-op target.
        assert target.generation is None, (
            "attempt identity cannot name a future served proof"
        )
        assert not await readiness.published_at_least((target,), timeout_seconds=0), (
            "parent baseline cannot satisfy resumed controller revision"
        )
        request = SearchRequest(
            tmp_path,
            "resumed no-op",
            1,
            {},
            PublicSourceType.DOCUMENT,
            "resumed-noop",
            freshness_policy=FreshnessWaitPolicy.BOUNDED,
            freshness_wait_seconds=0,
        )
        assert (
            await _admit_requested_freshness(request, registry)
        ).outcome == "timeout"
        assert checkpoint.publish_proof_transition() == 0
        assert ledger.publication_proof(key).generation_id == parent
        assert not await readiness.published_at_least((target,), timeout_seconds=0)
        indexer._publish_generation(checkpoint)
        assert checkpoint.generation.terminal_state is RunTerminalState.SUCCEEDED
        assert await readiness.published_at_least((target,), timeout_seconds=0)
        admission = await _admit_requested_freshness(request, registry)
        assert admission.outcome == "satisfied"
        assert admission.snapshot is not None
        assert admission.snapshot.published_generation == parent
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        readiness.close()


@pytest.mark.parametrize("unreadable", ["missing", "incompatible", "open"])
async def test_publication_callback_cannot_notify_an_unreadable_proof(
    tmp_path: Path,
    unreadable: str,
) -> None:
    if unreadable != "missing":
        ledger, signature, key, _ = _published(
            tmp_path,
            "document",
            incompatible="backend_identity" if unreadable == "incompatible" else None,
        )
        if unreadable == "open":
            _reserve(ledger, signature, key)
    registry = _registry()
    readiness = registry.readiness_registry
    try:
        result = ServiceRegistry._publish_readiness(
            readiness, JobSource.DOCUMENT, tmp_path, "finished-attempt"
        )
        assert result is None, "unreadable publication cannot notify"
        assert readiness._snapshots == {}
    finally:
        readiness.close()


async def test_publication_callback_rechecks_its_read_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, signature, key, _ = _published(tmp_path, "document")
    acquire = _publication_state.acquire_publication_snapshot

    def change_after_acquire(
        root: Path,
        source: PublicSourceType,
    ) -> _publication_state.PublicationSnapshot:
        snapshot = acquire(root, source)
        _reserve(ledger, signature, key)
        return snapshot

    monkeypatch.setattr(
        _publication_state, "acquire_publication_snapshot", change_after_acquire
    )
    registry = _registry()
    try:
        result = ServiceRegistry._publish_readiness(
            registry.readiness_registry, JobSource.DOCUMENT, tmp_path, "attempt"
        )
        assert result is None, "changed proof token cannot notify publication"
        assert registry.readiness_registry._snapshots == {}
    finally:
        registry.readiness_registry.close()


async def test_active_job_preserves_updating_and_non_authoritative_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _published(tmp_path, "document")
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=1,
        state_path=None,
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.DOCUMENT,
            str(tmp_path),
            JobMode.INCREMENTAL,
            RunAuthority.PUBLICATION,
        ),
        JobInitiator("test", "readiness", str(tmp_path)),
        start_paused=True,
    )
    assert created.job is not None
    jobs = [created.job.to_dict()]
    monkeypatch.setattr(_routes, "canonical_job_snapshot", lambda: jobs)
    registry = _registry()
    try:
        facts = SearchAvailabilityRequestFacts(
            jobs,
            tmp_path,
            "document",
            "updating-empty",
            None,
            readiness_snapshot=readiness_snapshot(registry, tmp_path, "document"),
        )
        classified = classify_search_result(_empty_result(tmp_path, "document"), facts)
        assert classified.status_code == 503
        assert classified.source_fact.freshness is SearchFreshness.UPDATING
        assert (
            classified.source_fact.absence_authority
            is AbsenceAuthority.NON_AUTHORITATIVE
        )
        assert "results" not in classified.response
        combined = _combined_source_fact(
            tmp_path,
            PublicSourceType.DOCUMENT,
            registry,
            observation=acquire_index_integrity_snapshot_if_proven(
                tmp_path, PublicSourceType.DOCUMENT
            ).finish(0),
            job_snapshot=jobs,
        )
        assert combined.freshness is SearchFreshness.UPDATING
        assert combined.absence_authority is AbsenceAuthority.NON_AUTHORITATIVE
    finally:
        registry.readiness_registry.close()


@pytest.mark.parametrize(
    "incompatible",
    [
        "root_identity",
        "backend_identity",
        "collection_identity",
        "source_type",
        "storage_schema",
        "payload_schema",
    ],
)
async def test_incompatible_publication_never_restores_authority(
    tmp_path: Path, incompatible: str
) -> None:
    _published(tmp_path, "document", incompatible=incompatible)
    registry = _registry()
    try:
        assert (
            registry.readiness_registry.snapshot(
                tmp_path, "document"
            ).publication_revision
            is None
        )
    finally:
        registry.readiness_registry.close()


def _reserve(
    ledger: RunLedger, signature: RunSignature, key: ProofCompatibilityKey
) -> None:
    successor = ledger.start_generation(signature)
    ledger.reserve_publication_receipt(
        key,
        successor.generation_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )


@pytest.mark.parametrize("change_during_read", [False, True])
async def test_open_or_changed_receipt_prevents_restoration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change_during_read: bool
) -> None:
    ledger, signature, key, _ = _published(tmp_path, "document")
    acquire = _publication_state.acquire_publication_snapshot
    if change_during_read:

        def change_after_acquire(
            root: Path,
            source: PublicSourceType,
        ) -> _publication_state.PublicationSnapshot:
            snapshot = acquire(root, source)
            _reserve(ledger, signature, key)
            return snapshot

        monkeypatch.setattr(
            _publication_state, "acquire_publication_snapshot", change_after_acquire
        )
    else:
        _reserve(ledger, signature, key)
    registry = _registry()
    try:
        snapshot = registry.readiness_registry.snapshot(tmp_path, "document")
        assert snapshot.publication_revision is None, (
            "open or changed proof cannot restore publication"
        )
    finally:
        registry.readiness_registry.close()


async def test_concurrent_publication_wins_without_restoration_holding_the_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _published(tmp_path, "document")
    registry = _registry()
    readiness = registry.readiness_registry
    original = _publication_state.PublicationSnapshot.validate

    def publish_then_validate(snapshot: _publication_state.PublicationSnapshot) -> None:
        original(snapshot)
        # A different thread proves the proof read does not own the registry lock.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(
                readiness.publish_next, tmp_path, "document", generation="concurrent"
            ).result(timeout=2)

    monkeypatch.setattr(
        _publication_state.PublicationSnapshot, "validate", publish_then_validate
    )
    try:
        snapshot = readiness.snapshot(tmp_path, "document")
        assert snapshot.published_generation == "concurrent", "concurrent publish wins"
        assert snapshot.publication_revision == 1
    finally:
        readiness.close()


async def test_missing_publication_stays_unknown_without_creating_a_ledger(
    tmp_path: Path,
) -> None:
    path = index_run_ledger_path(workspace_volume_path(tmp_path.resolve()))
    registry = _registry()
    try:
        assert (
            registry.readiness_registry.snapshot(
                tmp_path, "document"
            ).publication_target()
            is None
        )
        assert not path.exists()
    finally:
        registry.readiness_registry.close()


@pytest.mark.parametrize(
    "verdict",
    [
        IntegrityVerdict.UNVERIFIABLE,
        IntegrityVerdict.SHRUNKEN,
        IntegrityVerdict.CONSISTENT,
    ],
)
async def test_changed_or_unverifiable_generation_never_proves_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verdict: IntegrityVerdict,
) -> None:
    _published(tmp_path, "document")
    registry = _registry()
    monkeypatch.setattr(_routes, "canonical_job_snapshot", _no_jobs)
    try:
        snapshot = readiness_snapshot(registry, tmp_path, "document")
        result = _empty_result(tmp_path, "document")
        state = cast("dict[str, object]", result["index_state"])
        integrity = cast("dict[str, object]", state["index_integrity"])
        integrity["verdict"] = verdict
        if verdict is IntegrityVerdict.CONSISTENT:
            integrity["generation_id"] = "different-generation"
        facts = SearchAvailabilityRequestFacts(
            [],
            tmp_path,
            "document",
            "mixed-generation",
            None,
            readiness_snapshot=snapshot,
        )
        classified = classify_search_result(result, facts)
        # Mutation: trusting a consistent verdict from another generation wins.
        assert classified.status_code == 503, (
            "different generation cannot prove absence"
        )
        assert "results" not in classified.response
        observation = replace(
            acquire_index_integrity_snapshot_if_proven(
                tmp_path, PublicSourceType.DOCUMENT
            ).finish(0),
            verdict=verdict,
            generation_id=cast("str", integrity["generation_id"]),
        )
        combined = _combined_source_fact(
            tmp_path,
            PublicSourceType.DOCUMENT,
            registry,
            observation=observation,
            job_snapshot=[],
        )
        assert combined.freshness is SearchFreshness.UNVERIFIABLE, (
            "combined generation must match the fenced proof"
        )
        assert combined.absence_authority is AbsenceAuthority.NON_AUTHORITATIVE
    finally:
        registry.readiness_registry.close()
