"""Interrupted publications recover through real source entry points and storage."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from .._job_errors import JobError, JobErrorKind
from .._publication_state import acquire_publication_snapshot
from .._source_types import PublicSourceType
from .._store_models import CodeChunk, DocumentChunk, DocumentPayload, VaultChunk
from ..config._settings import get_config
from ..embeddings import EmbeddingModel
from ..indexer import CodebaseIndexer, DocumentIndexer, VaultIndexer
from ..indexer._checkpoint_common import RunCheckpointBase
from ..indexer._content_policy import ContentKind
from ..indexer._file_state import FileState
from ..indexer._publication_proof import (
    PathDelta,
    PathOutcome,
    ProofEvidence,
    ProofMutationState,
    ProofReadConflictError,
    ProofReceiptState,
)
from ..indexer._run_ledger_models import (
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    RunAuthority,
    RunLedgerStateError,
    RunOperation,
    RunTerminalState,
)
from ..indexer._vault_checkpoint import VaultRunCheckpoint
from ..job_control import NO_RUN_CONTROL, RunControlToken
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore
from ._sqlite_state import assert_sqlite_unchanged, sqlite_contents
from .integration._helpers import _document_policy

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..indexer._publication_proof import ProofCompatibilityKey
    from ..indexer._run_ledger_models import PublicationReceipt
    from ..indexer._run_ledger_runtime import RunLedger

pytestmark = [pytest.mark.unit]


def _configure_model(dimension: int) -> None:
    get_config(
        {
            "embedding_dimension": dimension,
            "qdrant_url": None,
            "sparse_enabled": False,
            "index_chunk_workers": 1,
        }
    )


@pytest.fixture
def recovery_model(clean_config: None) -> EmbeddingModel:
    """An unloaded production encoder: empty source scopes never encode."""
    del clean_config
    _configure_model(2)
    model = EmbeddingModel.__new__(EmbeddingModel)
    # No weights are loaded here, so there is no device to name.
    model._device = "unloaded"
    model._init_encode_state(get_config())
    return model


@pytest.fixture(params=list(PublicSourceType)[:3])
def publication_source(request: pytest.FixtureRequest) -> PublicSourceType:
    assert isinstance(request.param, PublicSourceType)
    return request.param


@pytest.fixture
def published_indexer(
    tmp_path: Path,
    recovery_model: EmbeddingModel,
    publication_source: PublicSourceType,
) -> Generator[CodebaseIndexer | DocumentIndexer | VaultIndexer]:
    (tmp_path / ".vault").mkdir()
    with VaultStore(tmp_path, embedding_dim=recovery_model.dimension) as store:
        if publication_source is PublicSourceType.CODE:
            indexer = CodebaseIndexer(tmp_path, recovery_model, store)
            indexer.full_index(
                reporter=NullProgressReporter(), preflight=indexer.preflight_content()
            )
        elif publication_source is PublicSourceType.DOCUMENT:
            indexer = DocumentIndexer(
                tmp_path,
                recovery_model,
                store,
                content_policy=_document_policy("*.txt"),
            )
            indexer.full_index(reporter=NullProgressReporter())
        else:
            indexer = VaultIndexer(tmp_path, recovery_model, store)
            indexer.full_index(reporter=NullProgressReporter())
        yield indexer


def _reserve(
    indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    source: PublicSourceType,
) -> tuple[RunLedger, PublicationReceipt]:
    snapshot = acquire_publication_snapshot(indexer.root_dir, source)
    parent = snapshot.ledger.generation(snapshot.proof.generation_id)
    successor = snapshot.ledger.start_generation(
        replace(
            parent.signature, clean=False, operation=RunOperation.SCOPED_INCREMENTAL
        )
    )
    receipt = snapshot.ledger.reserve_publication_receipt(
        snapshot.proof.compatibility_key,
        successor.generation_id,
        expected_parent_revision=snapshot.proof.revision,
    )
    return snapshot.ledger, receipt


def _incremental(
    indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
) -> None:
    if isinstance(indexer, CodebaseIndexer):
        indexer.incremental_index(
            reporter=NullProgressReporter(),
            changed_paths=[],
            preflight=indexer.preflight_changed_paths([]),
        )
    else:
        indexer.incremental_index(reporter=NullProgressReporter(), changed_paths=[])


def _upsert_recorded_point(
    store: VaultStore,
    source: PublicSourceType,
    unit: CommitUnit,
) -> None:
    """Apply one real synchronous point write before recording acknowledgement."""
    vector = [1.0, 0.0]
    if source is PublicSourceType.CODE:
        store.upsert_code_chunks(
            [
                CodeChunk(
                    id=unit.point_ids[0],
                    path=unit.rel_path,
                    language="python",
                    content="alpha beta",
                    line_start=1,
                    line_end=1,
                    vector=vector,
                )
            ],
            write_policy=None,
        )
    elif source is PublicSourceType.DOCUMENT:
        store.upsert_document_content_chunks(
            [
                DocumentChunk(
                    id=unit.point_ids[0],
                    payload=DocumentPayload(
                        source_path=unit.rel_path,
                        unit_ordinal=0,
                        content_fingerprint=unit.source_digest or "",
                        content="alpha beta",
                    ),
                    vector=vector,
                )
            ],
            write_policy=None,
        )
    else:
        chunk = VaultChunk(
            doc_id=unit.rel_path,
            ordinal=0,
            chunk_count=1,
            text="alpha beta",
            path=f"{unit.rel_path}.md",
            doc_type="adr",
            feature="",
            date="",
            tags=[],
            related=[],
            title=unit.rel_path,
            vector=vector,
        )
        assert chunk.point_key == unit.point_ids[0]
        store.upsert_document_chunks([chunk], write_policy=None)


@pytest.mark.parametrize("rolling_back", [False, True])
def test_source_entry_recovers_an_abandoned_empty_reservation(
    published_indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    publication_source: PublicSourceType,
    rolling_back: bool,
) -> None:
    """Mutation: removing recovery from an entry point leaves its fence open."""
    root = published_indexer.root_dir
    before = acquire_publication_snapshot(root, publication_source)
    ledger, receipt = _reserve(published_indexer, publication_source)
    if rolling_back:
        ledger.begin_publication_rollback(receipt.receipt_id)
    with pytest.raises(ProofReadConflictError):
        acquire_publication_snapshot(root, publication_source)

    _incremental(published_indexer)

    after = acquire_publication_snapshot(root, publication_source)
    assert after.proof.revision == before.proof.revision
    assert after.proof.aggregate == before.proof.aggregate
    assert ledger.active_publication_receipt(receipt.compatibility_key) is None
    assert ledger.generation(receipt.generation_id).terminal_state is (
        RunTerminalState.INVALIDATED
    )
    with pytest.raises(ProofReadConflictError):
        before.validate()


@pytest.mark.parametrize("state", list(ProofMutationState))
def test_unsealed_receipt_recovers_through_source_entry(
    published_indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    publication_source: PublicSourceType,
    state: ProofMutationState,
) -> None:
    """Confirmed complete work rolls forward; uncertain absent work replays."""
    ledger, receipt = _reserve(published_indexer, publication_source)
    unit = CommitUnit(
        rel_path="lost.txt",
        kind=CommitUnitKind.UPSERT,
        source_digest="1" * 128,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("lost.txt#c0",),
    )
    ledger.prepare_publication_mutation(receipt.receipt_id, unit)
    if state is not ProofMutationState.PREPARED:
        _upsert_recorded_point(published_indexer.store, publication_source, unit)
        ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
    if state is ProofMutationState.CONFIRMED:
        ledger.confirm_publication_mutation(receipt.receipt_id, unit)

    _incremental(published_indexer)

    after = acquire_publication_snapshot(published_indexer.root_dir, publication_source)
    assert ledger.active_publication_receipt(receipt.compatibility_key) is None
    if state is ProofMutationState.PREPARED:
        assert after.proof.aggregate.retained_points == 0
    else:
        assert after.proof.aggregate.retained_points == 1
        assert after.proof.generation_id == receipt.generation_id
        assert ledger.unit_committed(receipt.generation_id, unit)


@pytest.mark.parametrize(
    "is_file_end,sealed", [(False, False), (True, False), (True, True)]
)
def test_uncertain_write_replays_after_source_disappears(
    published_indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    publication_source: PublicSourceType,
    is_file_end: bool,
    sealed: bool,
) -> None:
    """Unacknowledged storage is removed by ordinary replay, never certified."""
    ledger, receipt = _reserve(published_indexer, publication_source)
    unit = CommitUnit(
        rel_path="vanished.txt",
        kind=CommitUnitKind.UPSERT,
        source_digest="3" * 128,
        segment_ordinal=0,
        is_file_end=is_file_end,
        point_ids=("vanished.txt#c0",),
    )
    ledger.prepare_publication_mutation(receipt.receipt_id, unit)
    _upsert_recorded_point(published_indexer.store, publication_source, unit)
    if not is_file_end:
        ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
        ledger.confirm_publication_mutation(receipt.receipt_id, unit)
    if sealed:
        ledger.seal_publication_receipt(
            receipt.receipt_id,
            (
                PathDelta(
                    PathOutcome.ADD,
                    receipt.parent_revision,
                    unit.rel_path,
                    new=ProofEvidence(
                        unit.rel_path, unit.source_digest or "", unit.point_ids
                    ),
                ),
            ),
        )
    _incremental(published_indexer)
    after = acquire_publication_snapshot(published_indexer.root_dir, publication_source)
    assert after.proof.aggregate.retained_points == 0
    assert ledger.active_publication_receipt(receipt.compatibility_key) is None
    store = published_indexer.store
    count = {
        PublicSourceType.VAULT: store.count,
        PublicSourceType.CODE: store.count_code,
        PublicSourceType.DOCUMENT: store.count_document,
    }[publication_source]
    assert count() == 0


@pytest.mark.parametrize("after_reset", [False, True])
def test_interrupted_receipt_reset_replays_durable_paths(
    published_indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    publication_source: PublicSourceType,
    after_reset: bool,
) -> None:
    """Reset markers survive both sides of the storage/checkpoint boundary."""
    ledger, receipt = _reserve(published_indexer, publication_source)
    unit = CommitUnit(
        rel_path="interrupted.txt",
        kind=CommitUnitKind.UPSERT,
        source_digest="4" * 128,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("interrupted.txt#c0",),
    )
    ledger.prepare_publication_mutation(receipt.receipt_id, unit)
    _upsert_recorded_point(published_indexer.store, publication_source, unit)
    ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
    ledger.confirm_publication_mutation(receipt.receipt_id, unit)
    ledger.begin_publication_storage_reset(receipt.receipt_id, (unit.rel_path,))
    published_indexer.store.delete_publication_points(
        publication_source, list(unit.point_ids)
    )
    if after_reset:
        ledger.reopen_publication_after_storage_reset(
            receipt.receipt_id, (unit.rel_path,)
        )
    _incremental(published_indexer)
    after = acquire_publication_snapshot(published_indexer.root_dir, publication_source)
    assert after.proof.aggregate.retained_points == 0
    assert ledger.active_publication_receipt(receipt.compatibility_key) is None


@pytest.mark.parametrize("state", list(ProofMutationState))
def test_explicit_rebuild_discards_unfinished_receipt_without_touching_siblings(
    published_indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    publication_source: PublicSourceType,
    state: ProofMutationState,
) -> None:
    """The recovery fallback resets only the explicitly selected index."""
    ledger, receipt = _reserve(published_indexer, publication_source)
    unit = CommitUnit(
        rel_path="lost.txt",
        kind=CommitUnitKind.UPSERT,
        source_digest="1" * 128,
        segment_ordinal=0,
        is_file_end=False,
        point_ids=("lost.txt#c0",),
    )
    ledger.prepare_publication_mutation(receipt.receipt_id, unit)
    _upsert_recorded_point(published_indexer.store, publication_source, unit)
    if state is not ProofMutationState.PREPARED:
        ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
    if state is ProofMutationState.CONFIRMED:
        ledger.confirm_publication_mutation(receipt.receipt_id, unit)
    sibling = (
        PublicSourceType.CODE
        if publication_source is not PublicSourceType.CODE
        else PublicSourceType.DOCUMENT
    )
    _upsert_recorded_point(published_indexer.store, sibling, unit)
    sibling_count = (
        published_indexer.store.count_code
        if sibling is PublicSourceType.CODE
        else published_indexer.store.count_document
    )
    before = sibling_count()
    if isinstance(published_indexer, CodebaseIndexer):
        published_indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=published_indexer.preflight_content(),
        )
    else:
        published_indexer.full_index(reporter=NullProgressReporter())
    after = acquire_publication_snapshot(published_indexer.root_dir, publication_source)
    assert after.proof.aggregate.retained_points == 0
    assert ledger.active_publication_receipt(receipt.compatibility_key) is None
    assert sibling_count() == before == 1


def test_recovery_validates_complete_file_stream_before_sealing(
    published_indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    publication_source: PublicSourceType,
) -> None:
    """Accepting a truncated stream failed the assertion; restoring the guard passed."""
    ledger, receipt = _reserve(published_indexer, publication_source)
    unit = CommitUnit(
        rel_path="partial.txt",
        kind=CommitUnitKind.UPSERT,
        source_digest="5" * 128,
        segment_ordinal=0,
        is_file_end=False,
        point_ids=("partial.txt#c0",),
    )
    ledger.prepare_publication_mutation(receipt.receipt_id, unit)
    _upsert_recorded_point(published_indexer.store, publication_source, unit)
    ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
    ledger.confirm_publication_mutation(receipt.receipt_id, unit)
    current = ledger.active_publication_receipt(receipt.compatibility_key)
    assert current is not None
    delta = PathDelta(
        PathOutcome.ADD,
        receipt.parent_revision,
        unit.rel_path,
        new=ProofEvidence(unit.rel_path, unit.source_digest or "", unit.point_ids),
    )
    assert not RunCheckpointBase._complete_mutation_streams(current, (delta,))


def test_reset_marker_blocks_forward_certification_of_removed_points(
    published_indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    publication_source: PublicSourceType,
) -> None:
    """Ignoring reset intent failed the state assertion; restoring the guard passed."""
    ledger, receipt = _reserve(published_indexer, publication_source)
    unit = CommitUnit(
        rel_path="partial.txt",
        kind=CommitUnitKind.UPSERT,
        source_digest="5" * 128,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("partial.txt#c0",),
    )
    ledger.prepare_publication_mutation(receipt.receipt_id, unit)
    _upsert_recorded_point(published_indexer.store, publication_source, unit)
    ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
    ledger.confirm_publication_mutation(receipt.receipt_id, unit)
    ledger.begin_publication_storage_reset(receipt.receipt_id, (unit.rel_path,))
    published_indexer.store.delete_publication_points(
        publication_source, list(unit.point_ids)
    )
    current = ledger.active_publication_receipt(receipt.compatibility_key)
    assert current is not None
    recovered = RunCheckpointBase._recover_unsealed_publication(
        ledger,
        current,
        NO_RUN_CONTROL,
        lambda ids: published_indexer.store.delete_publication_points(
            publication_source, ids
        ),
    )
    assert recovered.state is ProofReceiptState.RESERVED


def test_parent_replay_cannot_close_when_current_source_was_skipped(
    published_indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    publication_source: PublicSourceType,
) -> None:
    """Skipping coverage raised DID NOT RAISE; restoring coverage passed."""
    ledger, receipt = _reserve(published_indexer, publication_source)
    unit = CommitUnit(
        rel_path="parent.txt",
        kind=CommitUnitKind.UPSERT,
        source_digest="6" * 128,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("parent.txt#c0",),
    )
    ledger.prepare_publication_mutation(receipt.receipt_id, unit)
    _upsert_recorded_point(published_indexer.store, publication_source, unit)
    ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
    ledger.confirm_publication_mutation(receipt.receipt_id, unit)
    _incremental(published_indexer)
    ledger, receipt = _reserve(published_indexer, publication_source)
    ledger.begin_publication_storage_reset(receipt.receipt_id, (unit.rel_path,))
    published_indexer.store.delete_publication_points(
        publication_source, list(unit.point_ids)
    )
    empty = ledger.reopen_publication_after_storage_reset(
        receipt.receipt_id, (unit.rel_path,)
    )
    with pytest.raises(
        RunLedgerStateError, match=r"unresolved parent path 'parent\.txt'"
    ):
        RunCheckpointBase._assert_replayed_parent_paths(
            ledger, empty, frozenset((unit.rel_path,))
        )
    assert ledger.active_publication_receipt(receipt.compatibility_key) is not None
    assert ledger.publication_replay_paths(receipt.receipt_id) == (unit.rel_path,)
    # The next genuine discovery sees the removed source and confirms deletion.
    _incremental(published_indexer)
    after = acquire_publication_snapshot(published_indexer.root_dir, publication_source)
    assert after.proof.aggregate.retained_points == 0


def test_receipt_recovery_refuses_missing_untouched_parent_storage(
    published_indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    publication_source: PublicSourceType,
) -> None:
    """A journal cannot repair a collection removed outside its recorded paths."""
    ledger, receipt = _reserve(published_indexer, publication_source)
    unit = CommitUnit(
        rel_path="parent.txt",
        kind=CommitUnitKind.UPSERT,
        source_digest="6" * 128,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("parent.txt#c0",),
    )
    ledger.prepare_publication_mutation(receipt.receipt_id, unit)
    _upsert_recorded_point(published_indexer.store, publication_source, unit)
    ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
    ledger.confirm_publication_mutation(receipt.receipt_id, unit)
    _incremental(published_indexer)
    ledger, pending = _reserve(published_indexer, publication_source)
    published_indexer.store.delete_publication_points(
        publication_source, list(unit.point_ids)
    )
    before = sqlite_contents(ledger.path)
    with pytest.raises(
        JobError, match="storage no longer backs untouched publication proof paths"
    ):
        _incremental(published_indexer)
    assert_sqlite_unchanged(ledger.path, before)
    assert ledger.active_publication_receipt(pending.compatibility_key) is not None


class _MakeVaultPathUnreadable(NullProgressReporter):
    def __init__(self, path: Path, phase: str = "hash documents") -> None:
        self.path = path
        self.phase = phase
        self.failed = False

    def phase_start(self, name: str, total: int | None = None) -> None:
        del total
        if name == self.phase and not self.failed:
            self.path.unlink()
            self.path.mkdir()
            self.failed = True


def test_vault_hash_failure_retains_replay_fence_until_next_reconciliation(
    tmp_path: Path,
    recovery_model: EmbeddingModel,
) -> None:
    """Real filesystem hash failure cannot re-certify removed parent storage."""
    (tmp_path / ".vault").mkdir()
    with VaultStore(tmp_path, embedding_dim=recovery_model.dimension) as store:
        indexer = VaultIndexer(tmp_path, recovery_model, store)
        indexer.full_index(reporter=NullProgressReporter())
        ledger, receipt = _reserve(indexer, PublicSourceType.VAULT)
        unit = CommitUnit(
            rel_path="adr/broken",
            kind=CommitUnitKind.UPSERT,
            source_digest="7" * 128,
            segment_ordinal=0,
            is_file_end=True,
            point_ids=("adr/broken#c0",),
        )
        ledger.prepare_publication_mutation(receipt.receipt_id, unit)
        _upsert_recorded_point(store, PublicSourceType.VAULT, unit)
        ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
        ledger.confirm_publication_mutation(receipt.receipt_id, unit)
        _incremental(indexer)
        source = tmp_path / ".vault" / "adr" / "broken.md"
        source.parent.mkdir()
        source.write_text(
            "---\ntags: ['#adr', '#recovery']\n---\n# Recovery\nsource content\n"
        )
        ledger, receipt = _reserve(indexer, PublicSourceType.VAULT)
        ledger.prepare_publication_mutation(
            receipt.receipt_id, replace(unit, source_digest="8" * 128)
        )
        reporter = _MakeVaultPathUnreadable(source)
        with pytest.raises(OSError):
            indexer.incremental_index(reporter=reporter, changed_paths=[])
        assert reporter.failed
        assert store.count() == 0
        assert ledger.active_publication_receipt(receipt.compatibility_key) is not None
        assert ledger.publication_replay_paths(receipt.receipt_id) == (unit.rel_path,)
        with pytest.raises(ProofReadConflictError):
            acquire_publication_snapshot(tmp_path, PublicSourceType.VAULT)
        source.rmdir()
        _incremental(indexer)
        after = acquire_publication_snapshot(tmp_path, PublicSourceType.VAULT)
        assert after.proof.aggregate.retained_points == store.count() == 0


@pytest.mark.parametrize(
    "phase", ["ingesting", "stale", "committed", "metadata", "generation"]
)
def test_sealed_confirmed_receipt_replays_outcomes_before_certification(
    published_indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    publication_source: PublicSourceType,
    phase: str,
) -> None:
    """The storage-confirmed delta remains exact even after source bytes change."""
    ledger, receipt = _reserve(published_indexer, publication_source)
    unit = CommitUnit(
        rel_path="confirmed.txt",
        kind=CommitUnitKind.UPSERT,
        source_digest="2" * 128,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("confirmed.txt#c0",),
    )
    ledger.prepare_publication_mutation(receipt.receipt_id, unit)
    _upsert_recorded_point(published_indexer.store, publication_source, unit)
    ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
    ledger.confirm_publication_mutation(receipt.receipt_id, unit)
    evidence = ProofEvidence(unit.rel_path, unit.source_digest or "", unit.point_ids)
    ledger.seal_publication_receipt(
        receipt.receipt_id,
        (
            PathDelta(
                PathOutcome.ADD,
                receipt.parent_revision,
                unit.rel_path,
                new=evidence,
            ),
        ),
    )
    if phase != "ingesting":
        ledger.record_storage_confirmed_unit(receipt.generation_id, unit)
        if publication_source is not PublicSourceType.VAULT:
            ledger.record_file_state(
                receipt.generation_id,
                FileState.indexed(
                    unit.rel_path,
                    ContentKind(publication_source.value),
                    unit.source_digest or "",
                ),
            )
        ledger.advance_finalization(
            receipt.generation_id, FinalizationPhase.STALE_RECONCILED
        )
    if phase in {"committed", "metadata", "generation"}:
        ledger.commit_publication_receipt(receipt.receipt_id)
    if phase in {"metadata", "generation"}:
        ledger.advance_finalization(
            receipt.generation_id, FinalizationPhase.METADATA_PUBLISHED
        )
    if phase == "generation":
        ledger.advance_finalization(
            receipt.generation_id, FinalizationPhase.GENERATION_PUBLISHED
        )
    ledger.finish_generation(
        receipt.generation_id, RunTerminalState.FAILED, detail="interrupted"
    )
    (published_indexer.root_dir / unit.rel_path).write_text("new source bytes")
    _incremental(published_indexer)

    after = acquire_publication_snapshot(published_indexer.root_dir, publication_source)
    assert after.proof.revision == receipt.target_revision
    assert after.proof.generation_id == receipt.generation_id
    assert ledger.publication_evidence_for_paths(
        receipt.compatibility_key, (unit.rel_path,)
    ) == {unit.rel_path: evidence}
    assert ledger.unit_committed(receipt.generation_id, unit)
    assert ledger.generation(receipt.generation_id).terminal_state is (
        RunTerminalState.SUCCEEDED
    )
    assert ledger.active_publication_receipt(receipt.compatibility_key) is None


@pytest.mark.parametrize("broken_parent", [False, True])
def test_receipt_recovery_refuses_incompatible_or_corrupt_ancestry_without_mutation(
    published_indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    publication_source: PublicSourceType,
    broken_parent: bool,
) -> None:
    """Mutation proved: bypassing both ancestry checks failed; restoration passed."""
    ledger, receipt = _reserve(published_indexer, publication_source)
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        if broken_parent:
            connection.execute(
                "UPDATE generations SET parent_generation_id = NULL "
                "WHERE generation_id = ?",
                (receipt.generation_id,),
            )
        else:
            connection.execute(
                "UPDATE publication_receipts "
                "SET parent_revision = parent_revision + 1, "
                "target_revision = target_revision + 1 WHERE receipt_id = ?",
                (receipt.receipt_id,),
            )
    before = sqlite_contents(ledger.path)
    with pytest.raises(JobError) as caught:
        _incremental(published_indexer)
    assert caught.value.error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert "cannot recover safely" in str(caught.value)
    assert_sqlite_unchanged(ledger.path, before)


@pytest.fixture
def unpublished_checkpoint(tmp_path: Path) -> VaultRunCheckpoint:
    checkpoint = VaultRunCheckpoint.open(
        tmp_path,
        backend_identity="backend-v1",
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=NO_RUN_CONTROL,
    )
    checkpoint.ledger.advance_finalization(
        checkpoint.generation_id, FinalizationPhase.STALE_RECONCILED
    )
    checkpoint.generation = checkpoint.ledger.advance_finalization(
        checkpoint.generation_id, FinalizationPhase.METADATA_PUBLISHED
    )
    return checkpoint


def test_checkpoint_publication_requires_its_committed_proof(
    tmp_path: Path,
) -> None:
    """A completed phase cannot certify a proof lost before terminal publication.

    Removing the checkpoint proof guard failed with DID NOT RAISE; restoring it
    passed. The completed phase prevents the ledger transition from masking it.
    """
    checkpoint = VaultRunCheckpoint.open(
        tmp_path,
        backend_identity="backend-v1",
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=NO_RUN_CONTROL,
    )
    checkpoint.publish_proof_transition()
    checkpoint.generation = checkpoint.ledger.advance_finalization(
        checkpoint.generation_id, FinalizationPhase.GENERATION_PUBLISHED
    )
    # The phase was valid when committed; a later damaged proof must still be
    # detected by terminal publication without another phase transition.
    with closing(sqlite3.connect(checkpoint.ledger.path)) as connection, connection:
        connection.execute(
            "DELETE FROM publication_proofs WHERE generation_id = ?",
            (checkpoint.generation_id,),
        )
    before = sqlite_contents(checkpoint.ledger.path)
    with pytest.raises(RunLedgerStateError, match="proof must commit"):
        checkpoint.publish_generation()
    generation = checkpoint.ledger.generation(checkpoint.generation_id)
    assert generation.finalization_phase is FinalizationPhase.GENERATION_PUBLISHED
    assert_sqlite_unchanged(checkpoint.ledger.path, before)


def test_ledger_publication_phase_requires_its_committed_proof(
    unpublished_checkpoint: VaultRunCheckpoint,
) -> None:
    """The ledger independently refuses an uncertified publication phase.

    Removing the ledger proof guard failed with DID NOT RAISE; restoring it passed.
    """
    checkpoint = unpublished_checkpoint
    before = sqlite_contents(checkpoint.ledger.path)
    with pytest.raises(RunLedgerStateError, match="proof must commit"):
        checkpoint.ledger.advance_finalization(
            checkpoint.generation_id, FinalizationPhase.GENERATION_PUBLISHED
        )
    generation = checkpoint.ledger.generation(checkpoint.generation_id)
    assert generation.finalization_phase is FinalizationPhase.METADATA_PUBLISHED
    assert_sqlite_unchanged(checkpoint.ledger.path, before)


def test_noop_checkpoint_does_not_certify_unreceipted_storage_units(
    tmp_path: Path,
) -> None:
    """Mutation proved: ignoring stored-unit absence failed; restoration passed."""
    rebuilt = VaultRunCheckpoint.open(
        tmp_path,
        backend_identity="backend-v1",
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=NO_RUN_CONTROL,
    )
    rebuilt.publish_proof_transition()
    rebuilt.publish_generation()
    checkpoint = VaultRunCheckpoint.open(
        tmp_path,
        backend_identity="backend-v1",
        authority=RunAuthority.PUBLICATION,
        operation=RunOperation.SCOPED_INCREMENTAL,
        run_control=NO_RUN_CONTROL,
    )
    checkpoint.ledger.record_storage_confirmed_unit(
        checkpoint.generation_id,
        CommitUnit(
            rel_path="unreceipted",
            kind=CommitUnitKind.UPSERT,
            source_digest="3" * 128,
            segment_ordinal=0,
            is_file_end=True,
            point_ids=("unreceipted#c0",),
        ),
    )
    checkpoint.publish_proof_transition()
    with pytest.raises(RunLedgerStateError, match="proof must commit"):
        checkpoint.publish_generation()


class _ReservationControl(RunControlToken):
    """Pause a real cooperative checkpoint once this caller reserves publication."""

    def __init__(self, ledger: RunLedger, key: ProofCompatibilityKey) -> None:
        super().__init__()
        self.ledger = ledger
        self.key = key
        self.reserved = threading.Event()
        self.release = threading.Event()

    def checkpoint(self) -> None:
        super().checkpoint()
        if self.reserved.is_set():
            return
        receipt = self.ledger.active_publication_receipt(self.key)
        if receipt is not None:
            self.reserved.set()
            assert self.release.wait(timeout=10), "publication control was not released"


def test_document_recovery_cannot_reclaim_a_concurrent_callers_live_reservation(
    tmp_path: Path,
    recovery_model: EmbeddingModel,
) -> None:
    """Mutation proved: releasing the writer lease failed; restoration passed."""
    with VaultStore(tmp_path, embedding_dim=recovery_model.dimension) as store:
        indexer = DocumentIndexer(
            tmp_path,
            recovery_model,
            store,
            content_policy=_document_policy("*.txt"),
        )
        indexer.full_index(reporter=NullProgressReporter())
        parent = acquire_publication_snapshot(tmp_path, PublicSourceType.DOCUMENT)
        control = _ReservationControl(parent.ledger, parent.proof.compatibility_key)
        second_started = threading.Event()
        second_finished = threading.Event()
        failures: list[BaseException] = []

        def first_call() -> None:
            try:
                indexer.incremental_index(
                    reporter=NullProgressReporter(),
                    changed_paths=[],
                    run_control=control,
                )
            except BaseException as exc:
                failures.append(exc)

        def second_call() -> None:
            second_started.set()
            try:
                indexer.incremental_index(
                    reporter=NullProgressReporter(), changed_paths=[]
                )
            except BaseException as exc:
                failures.append(exc)
            finally:
                second_finished.set()

        first = threading.Thread(target=first_call)
        second = threading.Thread(target=second_call)
        first.start()
        try:
            assert control.reserved.wait(timeout=10)
            acquired = indexer._writer_lock.acquire(blocking=False)
            if acquired:
                indexer._writer_lock.release()
            assert not acquired, (
                "checkpoint reservation escaped the document writer lease"
            )
            second.start()
            assert second_started.wait(timeout=10)
            assert not second_finished.wait(timeout=0.25)
            pending = parent.ledger.active_publication_receipt(control.key)
            assert pending is not None
            assert parent.ledger.generation(pending.generation_id).terminal_state is (
                RunTerminalState.RUNNING
            )
        finally:
            control.release.set()
            first.join(timeout=10)
            if second.ident is not None:
                second.join(timeout=10)
        assert not first.is_alive()
        assert not second.is_alive()
        assert failures == []
        after = acquire_publication_snapshot(tmp_path, PublicSourceType.DOCUMENT)
        assert after.proof.revision == parent.proof.revision


@pytest.mark.parametrize("phase", ["parse documents", "hash documents"])
def test_full_vault_read_failure_preserves_confirmed_rebuild_work(
    tmp_path: Path, recovery_model: EmbeddingModel, phase: str
) -> None:
    """Unreadable scanned input cannot become an apparent source deletion.

    Swallowing strict read errors failed DID NOT RAISE; restoring passed.
    """
    source = tmp_path / ".vault" / "adr" / "broken.md"
    source.parent.mkdir(parents=True)
    source.write_text("---\ntype: adr\ntitle: Broken\n---\n# Broken\nsource bytes\n")
    with VaultStore(tmp_path, embedding_dim=recovery_model.dimension) as store:
        checkpoint = VaultRunCheckpoint.open(
            tmp_path,
            backend_identity=store.backend_identity,
            authority=RunAuthority.REBUILD,
            operation=RunOperation.FULL,
            run_control=NO_RUN_CONTROL,
        )
        unit = CommitUnit(
            rel_path="adr/broken",
            kind=CommitUnitKind.UPSERT,
            source_digest="7" * 128,
            segment_ordinal=0,
            is_file_end=True,
            point_ids=("adr/broken#c0",),
        )
        _upsert_recorded_point(store, PublicSourceType.VAULT, unit)
        checkpoint.ledger.record_storage_confirmed_unit(checkpoint.generation_id, unit)
        before = sqlite_contents(checkpoint.ledger.path)
        reporter = _MakeVaultPathUnreadable(source, phase)
        with pytest.raises(OSError):
            VaultIndexer(tmp_path, recovery_model, store).full_index(
                clean=True, reporter=reporter
            )
        assert reporter.failed
        assert store.count() == 1
        assert_sqlite_unchanged(checkpoint.ledger.path, before)
