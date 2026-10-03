"""Real CPU vault storage, deadline, publication, and cleanup boundaries."""

from __future__ import annotations

import hashlib
import sqlite3
import sys
import threading
import time
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING

import pytest

from .._job_errors import JobError, JobErrorKind
from .._store_models import VaultChunk
from ..config._settings import get_config
from ..embeddings import EmbeddingModel
from ..indexer import VaultIndexer
from ..indexer._reuse import DonorReuseContext
from ..indexer._run_ledger_models import (
    FinalizationPhase,
    RunAuthority,
    RunOperation,
    RunTerminalState,
)
from ..indexer._run_policy import DurableProgressKind
from ..indexer._streaming import (
    StoreWriteTask,
    _SliceWriter,
    _stream_encode_and_upsert_vault,
    execute_store_mutation,
)
from ..indexer._streaming_types import VaultStreamRequest
from ..indexer._vault_checkpoint import VaultRunCheckpoint
from ..indexer._vault_incremental import VaultReconcileInputs
from ..indexer._vault_prep import prepare_document, split_documents
from ..job_control import CancelRequested, RunControlToken
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore

if TYPE_CHECKING:
    from pathlib import Path
    from types import FrameType

    from .._store_writes import StoreWritePolicy

pytestmark = [pytest.mark.unit]


@pytest.fixture
def unloaded_model(clean_config: None) -> EmbeddingModel:
    del clean_config
    cfg = get_config(
        {
            "embedding_dimension": 2,
            "qdrant_url": None,
            "sparse_enabled": False,
            "index_no_progress_timeout_seconds": 2.0,
        }
    )
    model = EmbeddingModel.__new__(EmbeddingModel)
    model._init_encode_state(cfg, device="unloaded")
    return model


def _open(
    root: Path, store: VaultStore, control: RunControlToken
) -> VaultRunCheckpoint:
    store.ensure_table()
    return VaultRunCheckpoint.open(
        root,
        backend_identity=store.backend_identity,
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=control,
    )


def _chunk(ordinal: int = 0, count: int = 1) -> VaultChunk:
    return VaultChunk(
        doc_id="adr/notes",
        ordinal=ordinal,
        chunk_count=count,
        text=f"durable notes {ordinal}",
        path="adr/notes.md",
        doc_type="adr",
        feature="liveness",
        date="2026-10-03",
        tags=[],
        related=[],
        title="Durable notes",
        vector=[1.0, 0.0],
    )


def _confirm(
    store: VaultStore, checkpoint: VaultRunCheckpoint, chunk: VaultChunk
) -> None:
    identities = {chunk.doc_id: hashlib.blake2b(b"durable vault source").hexdigest()}
    execute_store_mutation(
        partial(
            store.upsert_document_chunks,
            [chunk],
            write_policy=checkpoint.run_policy.store_write_policy,
        ),
        checkpoint.chunk_lifecycle([chunk], identities),
        after_acknowledgement=partial(
            checkpoint.record_confirmed_chunks, [chunk], identities
        ),
    )


def test_confirmed_vault_units_extend_a_run_beyond_its_timeout(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """Removing inserted-unit renewal fails on the first real durable count."""
    del unloaded_model
    with VaultStore(tmp_path, embedding_dim=2) as store:
        checkpoint = _open(tmp_path, store, RunControlToken())
        started = time.monotonic()
        run = checkpoint.run_policy.snapshot()
        for ordinal in range(5):
            checkpoint.run_policy.wait(0.55)
            _confirm(store, checkpoint, _chunk(ordinal, 5))
            run = checkpoint.run_policy.snapshot()
            assert run.durable_progress_count == ordinal + 1, (
                "confirmed vault unit did not renew clock"
            )
            assert run.last_progress_kind is DurableProgressKind.LEDGER_UNIT_COMMITTED
            assert (
                checkpoint.ledger.committed_unit_count(checkpoint.generation_id)
                == ordinal + 1
            )
        assert time.monotonic() - started > run.timeout_seconds
        checkpoint.publish_proof_transition()
        assert (
            checkpoint.publish_generation().terminal_state is RunTerminalState.SUCCEEDED
        )


def test_duplicate_or_empty_confirmation_does_not_renew(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """Unconditional renewal gives a replay credit it did not earn."""
    del unloaded_model
    with VaultStore(tmp_path, embedding_dim=2) as store:
        checkpoint = _open(tmp_path, store, RunControlToken())
        chunk = _chunk()
        _confirm(store, checkpoint, chunk)
        before = checkpoint.run_policy.snapshot()
        time.sleep(0.05)
        _confirm(store, checkpoint, chunk)
        identities = {
            chunk.doc_id: hashlib.blake2b(b"durable vault source").hexdigest()
        }
        with pytest.raises(ValueError, match="must contain units"):
            checkpoint.record_confirmed_chunks([], identities)
        after = checkpoint.run_policy.snapshot()
        assert after.last_durable_progress_at == before.last_durable_progress_at, (
            "replayed vault unit renewed clock"
        )
        assert after.durable_progress_count == before.durable_progress_count


def test_silence_refuses_publication_before_terminal_success(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """Skipping the prepublication budget check certifies expired work."""
    del unloaded_model
    with VaultStore(tmp_path, embedding_dim=2) as store:
        checkpoint = _open(tmp_path, store, RunControlToken())
        _confirm(store, checkpoint, _chunk())
        checkpoint.publish_proof_transition()
        checkpoint.generation = checkpoint.ledger.advance_finalization(
            checkpoint.generation_id, FinalizationPhase.GENERATION_PUBLISHED
        )
        time.sleep(2.05)
        failure: JobError | None = None
        try:
            checkpoint.publish_generation()
        except JobError as exc:
            failure = exc
        assert failure is not None, "expired vault work committed terminal success"
        assert failure.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
        assert (
            checkpoint.ledger.generation(checkpoint.generation_id).terminal_state
            is RunTerminalState.RUNNING
        )
        assert checkpoint.run_policy._completed is False


def test_successful_publication_retires_deadline_but_preserves_control(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """Dropping terminal completion makes a slow successful epilogue time out."""
    del unloaded_model
    with VaultStore(tmp_path, embedding_dim=2) as store:
        control = RunControlToken()
        checkpoint = _open(tmp_path, store, control)
        failure: JobError | None = None
        try:
            with checkpoint.run_policy.protected():
                _confirm(store, checkpoint, _chunk())
                checkpoint.publish_proof_transition()
                checkpoint.publish_generation()
                time.sleep(2.05)
                checkpoint.run_policy.checkpoint()
        except JobError as exc:
            failure = exc
        assert failure is None, "successful vault epilogue raised a deadline failure"
        assert (
            checkpoint.ledger.generation(checkpoint.generation_id).terminal_state
            is RunTerminalState.SUCCEEDED
        )
        assert checkpoint.run_policy.snapshot().expired is False
        assert control.request_cancel()
        cancelled = False
        try:
            checkpoint.run_policy.checkpoint()
        except CancelRequested:
            cancelled = True
        assert cancelled, "completed policy lost cooperative cancellation"
        # Completion retires epilogues, not the store's admission budget.
        assert checkpoint.run_policy.store_write_policy.remaining_seconds() == 0.0


def test_successful_publication_closes_actual_storage_admission(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """Terminal clock publication does not grant another real storage write."""
    del unloaded_model
    with VaultStore(tmp_path, embedding_dim=2) as store:
        checkpoint = _open(tmp_path, store, RunControlToken())
        _confirm(store, checkpoint, _chunk())
        checkpoint.publish_proof_transition()
        checkpoint.publish_generation()
        failure: JobError | None = None
        try:
            store.upsert_document_chunks(
                [_chunk(1, 2)], write_policy=checkpoint.run_policy.store_write_policy
            )
        except JobError as exc:
            failure = exc
        assert failure is not None, "completed policy admitted another store write"
        assert store.get_chunk_counts() == {"adr/notes": 1}
        assert checkpoint.run_policy.snapshot().expired is False


def test_failed_store_or_ledger_never_renews_or_completes(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """The real Qdrant/SQLite failures precede every durable-clock update."""
    del unloaded_model
    with VaultStore(tmp_path, embedding_dim=2) as store:
        checkpoint = _open(tmp_path, store, RunControlToken())
        before = checkpoint.run_policy.snapshot()
        broken = replace(_chunk(), vector=[1.0, 0.0, 0.0])
        with pytest.raises((ValueError, JobError)):
            _confirm(store, checkpoint, broken)
        assert checkpoint.run_policy.snapshot().durable_progress_count == 0, (
            "failed vault store renewed clock"
        )
        assert (
            checkpoint.run_policy.snapshot().last_durable_progress_at
            == before.last_durable_progress_at
        )
        assert checkpoint.ledger.committed_unit_count(checkpoint.generation_id) == 0
        assert not checkpoint.run_policy._completed
        # A new genuine attempt budget is needed after the failed store retry.
        checkpoint = _open(tmp_path, store, RunControlToken())
        before = checkpoint.run_policy.snapshot()
        checkpoint.ledger.path.unlink()
        checkpoint.ledger.path.mkdir()
        with pytest.raises(sqlite3.OperationalError):
            _confirm(store, checkpoint, _chunk())
        after = checkpoint.run_policy.snapshot()
        assert after.last_durable_progress_at == before.last_durable_progress_at, (
            "failed vault ledger renewed clock"
        )
        assert after.durable_progress_count == 0
        assert not checkpoint.run_policy._completed


def test_failed_terminal_commit_never_retires_the_deadline(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """A genuine SQLite terminal-write failure cannot authorize epilogues."""
    del unloaded_model
    with VaultStore(tmp_path, embedding_dim=2) as store:
        checkpoint = _open(tmp_path, store, RunControlToken())
        _confirm(store, checkpoint, _chunk())
        checkpoint.publish_proof_transition()
        with sqlite3.connect(checkpoint.ledger.path) as connection:
            connection.execute(
                "CREATE TRIGGER fail_terminal BEFORE UPDATE ON generations "
                "WHEN NEW.terminal_state = 'succeeded' "
                "BEGIN SELECT RAISE(ABORT, 'terminal write refused'); END"
            )
        with pytest.raises(sqlite3.IntegrityError, match="terminal write refused"):
            checkpoint.publish_generation()
        assert not checkpoint.run_policy._completed, (
            "failed terminal commit retired its deadline"
        )
        assert (
            checkpoint.ledger.generation(checkpoint.generation_id).terminal_state
            is RunTerminalState.RUNNING
        )


def test_completion_preserves_a_previously_latched_failure(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """The in-memory API retains a latched failure even on erroneous completion."""
    del unloaded_model
    with VaultStore(tmp_path, embedding_dim=2) as store:
        checkpoint = _open(tmp_path, store, RunControlToken())
        time.sleep(2.05)
        with pytest.raises(JobError) as latched:
            checkpoint.run_policy.checkpoint()
        checkpoint.run_policy.complete(label="incorrect completion caller")
        failure: JobError | None = None
        try:
            checkpoint.run_policy.checkpoint()
        except JobError as exc:
            failure = exc
        assert failure is not None, "completion cleared a latched deadline failure"
        assert failure.detail == latched.value.detail
        assert checkpoint.run_policy.snapshot().expired


def test_actual_stream_and_payload_writes_receive_exact_checkpoint_policy(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """Observe real argument delivery with genuine donor adoption and Qdrant writes."""
    path = tmp_path / ".vault" / "adr" / "notes.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\ndate: '2026-10-03'\ntags: []\n---\n# Notes\n\nreal donor text\n"
    )
    doc = prepare_document(path, tmp_path)
    assert doc is not None
    cfg = get_config()
    with VaultStore(tmp_path, embedding_dim=2) as store:
        chunks = split_documents([doc], int(cfg.vault_chunk_chars))
        for chunk in chunks:
            chunk.vector = [1.0, 0.0]
        store.upsert_document_chunks(chunks, write_policy=None)
        checkpoint = _open(tmp_path, store, RunControlToken())
        reuse = DonorReuseContext(store, (store.TABLE_NAME,))
        writes: list[object] = []
        controls: list[object] = []

        def observe(frame: FrameType, event: str, _arg: object) -> None:
            if event != "call":
                return
            if frame.f_code.co_name in {
                "upsert_document_chunks",
                "overwrite_vault_chunk_payloads",
            }:
                writes.append(frame.f_locals["write_policy"])
            elif (
                frame.f_code.co_name in {"submit", "close"}
                and frame.f_locals.get("self").__class__ is _SliceWriter
            ):
                controls.append(frame.f_locals["run_control"])

        identities = {doc.id: hashlib.blake2b(path.read_bytes()).hexdigest()}
        previous = sys.getprofile()
        previous_thread = threading.getprofile()
        sys.setprofile(observe)
        threading.setprofile(observe)
        try:
            _stream_encode_and_upsert_vault(
                VaultStreamRequest(
                    [doc],
                    1,
                    unloaded_model,
                    store,
                    None,
                    NullProgressReporter(),
                    checkpoint=checkpoint,
                    content_identities=identities,
                    reuse=reuse,
                )
            )
            # Both the queue writer and payload-only execution deliver the
            # same checkpoint's write capability to actual storage methods.
            indexer = VaultIndexer(tmp_path, unloaded_model, store)
            indexer._apply_payload_refresh(
                chunks,
                VaultReconcileInputs(
                    {},
                    {},
                    1,
                    NullProgressReporter(),
                    checkpoint.run_policy,
                    checkpoint,
                    identities,
                ),
            )
        finally:
            sys.setprofile(previous)
            threading.setprofile(previous_thread)
        assert reuse.stats.reuse_hits == len(chunks)
        assert reuse.stats.reuse_misses == 0
        assert writes and all(
            value is checkpoint.run_policy.store_write_policy for value in writes
        ), "vault write lost its checkpoint policy"
        assert controls and all(value is checkpoint.run_policy for value in controls), (
            "vault writer wait lost its checkpoint policy"
        )
        assert checkpoint.ledger.committed_unit_count(checkpoint.generation_id) == len(
            chunks
        )


@pytest.mark.parametrize("mode", ["full", "incremental", "scoped"])
def test_actual_vault_entries_adopt_the_opened_checkpoint_policy(
    tmp_path: Path, unloaded_model: EmbeddingModel, mode: str
) -> None:
    """Real source entries reach their post-open cooperative boundary on one policy."""
    path = tmp_path / ".vault" / "adr" / "notes.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\ndate: '2026-10-03'\n---\n# Notes\n\nreal source\n")
    with VaultStore(tmp_path, embedding_dim=2) as store:
        seed = _open(tmp_path, store, RunControlToken())
        _confirm(store, seed, _chunk())
        seed.publish_proof_transition()
        seed.publish_generation()
        indexer = VaultIndexer(tmp_path, unloaded_model, store)
        control = RunControlToken()
        opened: list[VaultRunCheckpoint] = []

        def observe(frame: FrameType, event: str, arg: object) -> None:
            if (
                event == "return"
                and frame.f_code.co_name == "open"
                and frame.f_locals.get("cls") is VaultRunCheckpoint
                and isinstance(arg, VaultRunCheckpoint)
            ):
                opened.append(arg)
                assert control.request_cancel()

        previous = sys.getprofile()
        sys.setprofile(observe)
        try:
            with pytest.raises(CancelRequested) as stopped:
                if mode == "full":
                    indexer.full_index(
                        clean=True,
                        authority=RunAuthority.REBUILD,
                        reporter=NullProgressReporter(),
                        run_control=control,
                    )
                else:
                    indexer.incremental_index(
                        reporter=NullProgressReporter(),
                        changed_paths=[path] if mode == "scoped" else None,
                        run_control=control,
                    )
        finally:
            sys.setprofile(previous)
        assert len(opened) == 1
        trace = stopped.value.__traceback__
        source_controls: list[object] = []
        while trace is not None:
            values = trace.tb_frame.f_locals
            if values.get("self") is indexer and "checkpoint" in values:
                source_controls.append(values["run_control"])
            trace = trace.tb_next
        assert source_controls and all(
            value is opened[0].run_policy for value in source_controls
        ), "vault source entry lost its checkpoint policy"
        assert not opened[0].run_policy._completed


@pytest.mark.parametrize("payload_only", [False, True])
def test_vault_point_lock_wait_is_bounded_by_its_run_policy(
    tmp_path: Path, unloaded_model: EmbeddingModel, payload_only: bool
) -> None:
    """Replacing the timed canonical lock with an ordinary lock loses the deadline."""
    del unloaded_model
    with VaultStore(tmp_path, embedding_dim=2) as store:
        store.upsert_document_chunks([_chunk()], write_policy=None)
        checkpoint = _open(tmp_path, store, RunControlToken())
        entered = threading.Event()
        finished = threading.Event()
        failures: list[BaseException] = []
        capability: StoreWritePolicy = checkpoint.run_policy.store_write_policy

        def write() -> None:
            entered.set()
            try:
                if payload_only:
                    store.overwrite_vault_chunk_payloads(
                        [_chunk()], write_policy=capability
                    )
                else:
                    store.upsert_document_chunks([_chunk()], write_policy=capability)
            except BaseException as exc:
                failures.append(exc)
            finally:
                finished.set()

        with store._point_lock(store.TABLE_NAME):
            worker = threading.Thread(target=write, daemon=True)
            worker.start()
            assert entered.wait(timeout=1.0)
            expired_while_held = finished.wait(timeout=2.3)
        worker.join(timeout=1.0)
        assert not worker.is_alive()
        assert expired_while_held, "vault point lock ignored the run deadline"
        assert len(failures) == 1 and isinstance(failures[0], JobError)
        assert failures[0].error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
        assert checkpoint.run_policy.snapshot().durable_progress_count == 0


def test_expired_writer_cleanup_settles_and_releases_real_work(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """Deadline-aware close still uses independent bounded cleanup on unwind."""
    del unloaded_model
    with VaultStore(tmp_path, embedding_dim=2) as store:
        checkpoint = _open(tmp_path, store, RunControlToken())
        writer = _SliceWriter(
            name="vault-deadline-cpu-writer", shutdown_timeout_seconds=2.0
        )
        released = threading.Event()
        writer.submit(
            StoreWriteTask(
                partial(_confirm, store, checkpoint, _chunk()), released.set
            ),
            run_control=checkpoint.run_policy,
        )
        assert released.wait(timeout=1.0)
        time.sleep(2.05)
        with pytest.raises(JobError) as failure:
            writer.close(run_control=checkpoint.run_policy)
        assert failure.value.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
        assert not writer._thread.is_alive(), (
            "expired writer cleanup left a thread alive"
        )
        assert released.is_set()
        assert checkpoint.ledger.committed_unit_count(checkpoint.generation_id) == 1
