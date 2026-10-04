"""Payload batches preserve actual local storage and document receipt boundaries."""

from __future__ import annotations

import errno
import hashlib
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

import pytest
from qdrant_client import models

from .._job_errors import JobError, JobErrorKind
from .._store_models import VaultChunk, _vault_chunk_payload
from .._store_writes import StoreWritePolicy
from ..config._settings import get_config
from ..embeddings import EmbeddingModel
from ..indexer import VaultIndexer
from ..indexer._publication_proof import ProofMutationState
from ..indexer._run_ledger_models import (
    PublicationReceipt,
    RunAuthority,
    RunOperation,
    ledger_connection,
)
from ..indexer._run_ledger_publication_storage import (
    hydrate_receipt,
    receipt_row_by_id,
)
from ..indexer._vault_checkpoint import VaultRunCheckpoint
from ..indexer._vault_incremental import VaultReconcileInputs
from ..job_control import RunControlToken
from ..progress import NullProgressReporter
from ..store_runtime import IngestVerificationError, VaultStore

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Sequence
    from pathlib import Path

pytestmark = pytest.mark.unit

_CONFIG = {
    "qdrant_url": None,
    "embedding_dimension": 2,
    "sparse_enabled": True,
    "store_write_retry_attempts": 2,
    "store_write_retry_base_seconds": 0.001,
    "store_write_retry_max_seconds": 0.001,
    "index_no_progress_timeout_seconds": 60.0,
}


def _batch_size(size: int) -> None:
    get_config({**_CONFIG, "embedding_batch_size": size})


@dataclass(frozen=True)
class _Case:
    root: Path
    store: VaultStore
    indexer: VaultIndexer


@pytest.fixture
def case(tmp_path: Path, clean_config: None) -> Generator[_Case]:
    del clean_config
    cfg = get_config(_CONFIG)
    model = EmbeddingModel.__new__(EmbeddingModel)
    # No weights are loaded here, so there is no device to name.
    model._device = "unloaded"
    model._init_encode_state(cfg)
    with VaultStore(tmp_path, embedding_dim=2) as store:
        yield _Case(tmp_path, store, VaultIndexer(tmp_path, model, store))


def _chunks(doc_id: str, count: int) -> list[VaultChunk]:
    return [
        VaultChunk(
            doc_id=doc_id,
            ordinal=ordinal,
            chunk_count=count,
            text=f"Body section {ordinal}",
            doc_content="Complete original body" if ordinal == 0 else None,
            path=f"{doc_id}.md",
            doc_type="adr",
            feature="batching",
            date="2026-10-03",
            tags=["#old"],
            related=["[[old]]"],
            title="Payload batching",
            vector=[1.0, 0.0],
            sparse_indices=[1, 3],
            sparse_values=[0.5, 1.25],
        )
        for ordinal in range(count)
    ]


def _changed(chunks: list[VaultChunk]) -> list[VaultChunk]:
    return [
        replace(
            chunk,
            tags=["#new"],
            related=["[[new]]"],
            vector=[],
            sparse_indices=[99],
            sparse_values=[7.0],
        )
        for chunk in chunks
    ]


@dataclass(frozen=True)
class _Request:
    operations: tuple[models.UpdateOperation, ...]
    wait: bool
    timeout: int | None


class _Calls:
    """Observe requests while delegating every normal write to QdrantLocal."""

    def __init__(self, store: VaultStore) -> None:
        self.original = store.client.batch_update_points
        self.requests: list[_Request] = []
        self.before: Callable[[_Request], None] | None = None
        self.after: (
            Callable[[_Request, list[models.UpdateResult]], list[models.UpdateResult]]
            | None
        ) = None

    def __call__(
        self,
        collection_name: str,
        update_operations: Sequence[models.UpdateOperation],
        **kwargs: object,
    ) -> list[models.UpdateResult]:
        request = _Request(
            tuple(update_operations),
            cast("bool", kwargs.get("wait", True)),
            cast("int | None", kwargs.get("timeout")),
        )
        self.requests.append(request)
        if self.before is not None:
            self.before(request)
        results = self.original(
            collection_name,
            update_operations,
            wait=request.wait,
            timeout=request.timeout,
        )
        return self.after(request, results) if self.after is not None else results


def _stored(case: _Case, chunks: list[VaultChunk]) -> dict[str, models.Record]:
    points = case.store.client.retrieve(
        case.store.TABLE_NAME,
        ids=[case.store._stable_id(chunk.point_key) for chunk in chunks],
        with_payload=True,
        with_vectors=True,
    )
    return {str(point.id): point for point in points}


def test_default_batches_preserve_payloads_vectors_and_rpc_bound(
    case: _Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cap1, an unbounded batch, merging payloads, or waitFalse breaks a named guard."""
    assert get_config().embedding_batch_size == 64
    chunks = _chunks("adr/large", 359)
    case.store.upsert_document_chunks(chunks, write_policy=None)
    case.store.client.set_payload(
        case.store.TABLE_NAME,
        {"obsolete": "must disappear"},
        [case.store._stable_id(chunk.point_key) for chunk in chunks],
    )
    before = _stored(case, chunks)
    calls = _Calls(case.store)
    monkeypatch.setattr(case.store.client, "batch_update_points", calls)
    refreshed = _changed(chunks)
    case.store.overwrite_vault_chunk_payloads(refreshed, write_policy=None)

    assert (
        calls.requests
        and max(len(request.operations) for request in calls.requests) <= 64
    ), "payload request exceeded the configured chunk bound"
    assert len(calls.requests) == 6, "payload refresh regressed to per-chunk requests"
    assert all(request.wait for request in calls.requests), (
        "payload batches must wait for applied changes"
    )
    after = _stored(case, chunks)
    assert after.keys() == before.keys()
    for chunk in refreshed:
        point_id = str(case.store._stable_id(chunk.point_key))
        payload = after[point_id].payload
        assert payload is not None and "obsolete" not in payload, (
            "payload overwrite must remove obsolete keys"
        )
        assert payload == _vault_chunk_payload(chunk)
        assert after[point_id].vector == before[point_id].vector, (
            "payload refresh changed stored dense or sparse vectors"
        )
    addressed = [
        point_id
        for request in calls.requests
        for operation in request.operations
        if isinstance(operation, models.OverwritePayloadOperation)
        for point_id in operation.overwrite_payload.points or []
    ]
    assert addressed == [case.store._stable_id(chunk.point_key) for chunk in chunks]


def test_nondefault_batch_bound_is_frozen_for_one_write(
    case: _Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    _batch_size(4)
    chunks = _chunks("adr/frozen", 11)
    case.store.upsert_document_chunks(chunks, write_policy=None)
    calls = _Calls(case.store)

    def flip_config(_request: _Request) -> None:
        _batch_size(1)

    calls.before = flip_config
    monkeypatch.setattr(case.store.client, "batch_update_points", calls)
    case.store.overwrite_vault_chunk_payloads(_changed(chunks), write_policy=None)
    assert [len(request.operations) for request in calls.requests] == [4, 4, 3]


def _work(
    checkpoint: VaultRunCheckpoint, chunks: list[VaultChunk]
) -> VaultReconcileInputs:
    identities = {
        chunk.doc_id: hashlib.blake2b(
            f"{chunk.doc_id}:{chunk.tags}".encode()
        ).hexdigest()
        for chunk in chunks
    }
    return VaultReconcileInputs(
        {},
        {},
        int(get_config().embedding_batch_size),
        NullProgressReporter(),
        checkpoint.run_policy,
        checkpoint,
        identities,
    )


def _publication(case: _Case, chunks: list[VaultChunk]) -> VaultReconcileInputs:
    """Establish an actual parent proof, then reserve a real incremental receipt."""
    case.store.upsert_document_chunks(chunks, write_policy=None)
    first = VaultRunCheckpoint.open(
        case.root,
        backend_identity=case.store.backend_identity,
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=RunControlToken(),
    )
    case.indexer._apply_payload_refresh(chunks, _work(first, chunks))
    first.publish_proof_transition()
    first.publish_generation()
    current = VaultRunCheckpoint.open(
        case.root,
        backend_identity=case.store.backend_identity,
        authority=RunAuthority.PUBLICATION,
        operation=RunOperation.INCREMENTAL,
        run_control=RunControlToken(),
    )
    assert current.receipt is not None
    return _work(current, _changed(chunks))


def _receipt(work: VaultReconcileInputs) -> PublicationReceipt:
    checkpoint = work.checkpoint
    assert checkpoint.receipt is not None
    with ledger_connection(checkpoint.ledger.path) as connection:
        row = receipt_row_by_id(connection, checkpoint.receipt.receipt_id)
        assert row is not None
        return hydrate_receipt(connection, row)


def test_actual_caller_confirms_only_complete_documents(
    case: _Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    _batch_size(4)
    chunks = _chunks("adr/first", 5) + _chunks("adr/second", 3)
    work = _publication(case, chunks)
    calls = _Calls(case.store)
    units_at_request: list[int] = []

    def observe(_request: _Request) -> None:
        units_at_request.append(
            work.checkpoint.ledger.committed_unit_count(work.checkpoint.generation_id)
        )

    calls.before = observe
    monkeypatch.setattr(case.store.client, "batch_update_points", calls)
    case.indexer._apply_payload_refresh(_changed(chunks), work)
    assert [len(request.operations) for request in calls.requests] == [4, 1, 3]
    assert units_at_request == [0, 0, 5], (
        "payload receipt must confirm only after the whole document applies"
    )
    assert (
        work.checkpoint.ledger.committed_unit_count(work.checkpoint.generation_id) == 8
    )
    assert all(
        mutation.state is ProofMutationState.CONFIRMED
        for mutation in _receipt(work).mutations
    )


@pytest.mark.parametrize(
    "status",
    [models.UpdateStatus.ACKNOWLEDGED, models.UpdateStatus.WAIT_TIMEOUT, None],
    ids=["acknowledged", "wait-timeout", "short-result"],
)
def test_incomplete_results_never_confirm_current_document(
    case: _Case, monkeypatch: pytest.MonkeyPatch, status: models.UpdateStatus | None
) -> None:
    """Omitting actual result validation advances the forbidden receipt count."""
    _batch_size(4)
    chunks = _chunks("adr/first", 1) + _chunks("adr/second", 5)
    work = _publication(case, chunks)
    calls = _Calls(case.store)

    def incomplete(
        request: _Request, results: list[models.UpdateResult]
    ) -> list[models.UpdateResult]:
        if len(request.operations) == 1:
            return results
        if status is None:
            return results[:-1]
        return [result.model_copy(update={"status": status}) for result in results]

    calls.after = incomplete
    monkeypatch.setattr(case.store.client, "batch_update_points", calls)
    failure: IngestVerificationError | None = None
    try:
        case.indexer._apply_payload_refresh(_changed(chunks), work)
    except IngestVerificationError as exc:
        failure = exc
    assert (
        work.checkpoint.ledger.committed_unit_count(work.checkpoint.generation_id) == 1
    ), "incomplete payload batch confirmed the current document"
    assert failure is not None
    assert str(failure) == (
        f"payload overwrite in {case.store.TABLE_NAME} did not confirm "
        "all 4 operation(s) as completed"
    )
    assert [len(request.operations) for request in calls.requests] == [1, 4, 4]
    receipt = _receipt(work)
    assert all(
        mutation.state is ProofMutationState.PREPARED
        for mutation in receipt.mutations
        if mutation.unit.rel_path == "adr/second"
    )
    assert work.checkpoint.run_policy.snapshot().durable_progress_count == 1


def test_partially_applied_transport_failure_replays_exact_batch(
    case: _Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    _batch_size(4)
    chunks = _chunks("adr/replay", 5)
    work = _publication(case, chunks)
    before = _stored(case, chunks)
    calls = _Calls(case.store)
    partial_units: list[int] = []

    def partial(request: _Request) -> None:
        if len(calls.requests) == 1:
            calls.original(case.store.TABLE_NAME, request.operations[:2], wait=True)
            partial_units.append(
                work.checkpoint.ledger.committed_unit_count(
                    work.checkpoint.generation_id
                )
            )
            raise ConnectionError("response lost after partial payload apply")

    calls.before = partial
    monkeypatch.setattr(case.store.client, "batch_update_points", calls)
    refreshed = _changed(chunks)
    case.indexer._apply_payload_refresh(refreshed, work)
    assert partial_units == [0]
    assert [len(request.operations) for request in calls.requests] == [4, 4, 1]
    assert calls.requests[0].operations == calls.requests[1].operations
    assert (
        work.checkpoint.ledger.committed_unit_count(work.checkpoint.generation_id) == 5
    )
    after = _stored(case, chunks)
    for chunk in refreshed:
        point_id = str(case.store._stable_id(chunk.point_key))
        assert after[point_id].payload == _vault_chunk_payload(chunk)
        assert after[point_id].vector == before[point_id].vector


@pytest.mark.parametrize("disk_full", [False, True], ids=["transport", "disk-full"])
def test_original_write_error_leaves_current_document_unconfirmed(
    case: _Case, monkeypatch: pytest.MonkeyPatch, disk_full: bool
) -> None:
    chunks = _chunks("adr/refused", 2)
    work = _publication(case, chunks)
    calls = _Calls(case.store)
    original = (
        OSError(errno.ENOSPC, "No space left on device")
        if disk_full
        else ConnectionError("payload transport refused")
    )

    def refuse(_request: _Request) -> None:
        raise original

    calls.before = refuse
    monkeypatch.setattr(case.store.client, "batch_update_points", calls)
    with pytest.raises(type(original)) as raised:
        case.indexer._apply_payload_refresh(_changed(chunks), work)
    assert raised.value is original
    assert len(calls.requests) == (1 if disk_full else 2)
    assert (
        work.checkpoint.ledger.committed_unit_count(work.checkpoint.generation_id) == 0
    )
    assert all(
        mutation.state is ProofMutationState.PREPARED
        for mutation in _receipt(work).mutations
    )


class _BudgetClock:
    def __init__(self) -> None:
        self.remaining = 1.0005
        self.waits: list[float] = []

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.remaining -= seconds


def test_payload_retry_consumes_caller_deadline_and_timeout(
    case: _Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passing None to the retried operation loses the actual caller timeout."""
    chunks = _chunks("adr/deadline", 1)
    case.store.upsert_document_chunks(chunks, write_policy=None)
    calls = _Calls(case.store)
    clock = _BudgetClock()
    policy = StoreWritePolicy(
        remaining_seconds=lambda: clock.remaining, wait=clock.wait
    )

    def refuse(_request: _Request) -> None:
        raise ConnectionError("payload connection refused")

    calls.before = refuse
    monkeypatch.setattr(case.store.client, "batch_update_points", calls)
    failure: Exception | None = None
    try:
        case.store.overwrite_vault_chunk_payloads(_changed(chunks), write_policy=policy)
    except Exception as exc:
        failure = exc
    assert [request.timeout for request in calls.requests] == [1], (
        "payload retry lost the caller deadline timeout"
    )
    assert clock.waits == [0.0, 0.0, 0.001]
    assert isinstance(failure, JobError)
    assert failure.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
