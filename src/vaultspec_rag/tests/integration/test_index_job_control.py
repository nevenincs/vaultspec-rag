"""Real-behavior integration coverage for cooperative indexing control.

The tests use the production streaming and indexing paths with local Qdrant,
real vault and code files, and a CPU-backed SentenceTransformer model. Keeping
the model tiny makes the control races deterministic without substituting test
implementations for any production indexing behavior.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest
from sentence_transformers.sentence_transformer import SentenceTransformer
from sentence_transformers.sentence_transformer.modules import BoW

from ...config import get_config
from ...embeddings import EmbeddingModel, QueryEmbeddingCache
from ...indexer import CodebaseIndexer, VaultIndexer
from ...indexer._streaming import _stream_encode_and_upsert_vault
from ...indexer._vault_prep import prepare_document
from ...job_control import (
    CancelRequested,
    ControlRequest,
    PauseRequested,
    RunControlSignal,
    RunControlToken,
)
from ...progress import NullProgressReporter
from ...store import VaultStore

if TYPE_CHECKING:
    from pathlib import Path

    from ...store import VaultDocument

pytestmark = pytest.mark.integration

_CONTROL_WAIT_SECONDS = 20.0
_CONTROL_POLL_SECONDS = 0.001


@pytest.fixture
def cpu_embedding_model(clean_config: None) -> EmbeddingModel:
    """Build a real production embedding path around a tiny CPU BoW model."""
    del clean_config
    vocabulary = [
        "alpha",
        "beta",
        "gamma",
        "delta",
        "index",
        "control",
        "document",
        "content",
    ]
    backend = SentenceTransformer(modules=[BoW(vocabulary)], device="cpu")
    dimension = backend.get_embedding_dimension()
    assert dimension is not None
    get_config(
        {
            "data_dir": ".index-control",
            "embedding_batch_size": 1,
            "embedding_dimension": dimension,
            "embedding_encode_batch_size": 1,
            "index_chunk_workers": 2,
            "qdrant_url": None,
            "sparse_enabled": False,
            "vault_chunk_chars": 10_000,
        }
    )

    model = EmbeddingModel.__new__(EmbeddingModel)
    model._dense_model = backend
    model._device = "cpu"
    model.dimension = dimension
    model.query_cache = QueryEmbeddingCache()
    return model


def _write_vault_documents(root: Path, count: int) -> list[VaultDocument]:
    """Create and parse a small real vault corpus through production code."""
    adr_dir = root / ".vault" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    documents: list[VaultDocument] = []
    for ordinal in range(count):
        path = adr_dir / f"control-{ordinal:03d}.md"
        path.write_text(
            "---\n"
            "tags: ['#adr', '#index-control']\n"
            "---\n"
            f"# Control document {ordinal}\n\n"
            f"alpha beta gamma index control document content {ordinal}\n",
            encoding="utf-8",
        )
        document = prepare_document(path, root)
        assert document is not None
        documents.append(document)
    return documents


def _request_after_first_upsert(
    store: VaultStore,
    token: RunControlToken,
    control_request: ControlRequest,
) -> None:
    """Request control only after production storage publishes one slice."""
    deadline = time.monotonic() + _CONTROL_WAIT_SECONDS
    while time.monotonic() < deadline:
        if store.count() > 0:
            if control_request is ControlRequest.PAUSE:
                assert token.request_pause()
            else:
                assert token.request_cancel()
            return
        time.sleep(_CONTROL_POLL_SECONDS)
    raise AssertionError("streaming never published a slice before the deadline")


def _write_code_files(root: Path, count: int, revision: str) -> list[Path]:
    """Create a real Python corpus with unique content markers."""
    source_dir = root / "src"
    source_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for ordinal in range(count):
        path = source_dir / f"control_{ordinal:03d}.py"
        path.write_text(
            f"def control_{ordinal:03d}() -> str:\n"
            f'    """alpha beta index control {revision}-{ordinal:03d}."""\n'
            f'    return "{revision}-{ordinal:03d}"\n',
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def _request_after_first_code_upsert(
    store: VaultStore,
    token: RunControlToken,
    control_request: ControlRequest,
) -> None:
    """Request control after the real code consumer publishes its first slice."""
    deadline = time.monotonic() + _CONTROL_WAIT_SECONDS
    while time.monotonic() < deadline:
        if store.count_code() > 0:
            accepted = (
                token.request_pause()
                if control_request is ControlRequest.PAUSE
                else token.request_cancel()
            )
            assert accepted
            return
        time.sleep(_CONTROL_POLL_SECONDS)
    raise AssertionError("code pipeline never published a slice before the deadline")


def _code_consumer_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "codebase-indexer-consumer"
    ]


def _assert_code_resources_released() -> None:
    """Require all process-pool and sole-consumer resources to be gone."""
    deadline = time.monotonic() + _CONTROL_WAIT_SECONDS
    while time.monotonic() < deadline:
        if not _code_consumer_threads() and not multiprocessing.active_children():
            return
        time.sleep(_CONTROL_POLL_SECONDS)
    assert not _code_consumer_threads()
    assert not multiprocessing.active_children()


def _stored_code_content(store: VaultStore) -> dict[str, str]:
    """Read the real Qdrant payloads and combine content by source path."""
    content_by_path: dict[str, list[str]] = {}
    offset: object | None = None
    while True:
        records, next_offset = store.client.scroll(
            collection_name=store.CODE_TABLE_NAME,
            limit=64,
            offset=offset,
            with_payload=["path", "content"],
            with_vectors=False,
        )
        for record in records:
            payload = record.payload
            assert payload is not None
            path = str(payload["path"])
            content_by_path.setdefault(path, []).append(str(payload["content"]))
        if next_offset is None:
            break
        offset = next_offset
    return {path: "\n".join(parts) for path, parts in content_by_path.items()}


def _assert_current_code_state(
    indexer: CodebaseIndexer,
    store: VaultStore,
    paths: list[Path],
    revision: str,
) -> None:
    """Verify complete metadata and current source text through production output."""
    expected_paths = {
        str(path.relative_to(indexer.root_dir)).replace("\\", "/") for path in paths
    }
    assert set(indexer._load_meta()) == expected_paths
    stored = _stored_code_content(store)
    assert set(stored) == expected_paths
    for ordinal, path in enumerate(paths):
        rel_path = str(path.relative_to(indexer.root_dir)).replace("\\", "/")
        assert f"{revision}-{ordinal:03d}" in stored[rel_path]


@pytest.mark.parametrize(
    ("control_request", "signal_type"),
    [
        pytest.param(ControlRequest.PAUSE, PauseRequested, id="pause"),
        pytest.param(ControlRequest.CANCEL, CancelRequested, id="cancel"),
    ],
)
def test_vault_stream_observes_control_between_published_slices(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
    control_request: ControlRequest,
    signal_type: type[RunControlSignal],
) -> None:
    """Pause and cancel stop real streaming only at a safe slice boundary."""
    documents = _write_vault_documents(tmp_path, 128)
    token = RunControlToken()

    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        store.ensure_table()
        with ThreadPoolExecutor(max_workers=1) as executor:
            requester = executor.submit(
                _request_after_first_upsert,
                store,
                token,
                control_request,
            )
            with pytest.raises(signal_type):
                _stream_encode_and_upsert_vault(
                    docs=documents,
                    slice_size=1,
                    model=cpu_embedding_model,
                    store=store,
                    gpu_lock=None,
                    reporter=NullProgressReporter(),
                    run_control=token,
                )
            requester.result(timeout=_CONTROL_WAIT_SECONDS)

        published = store.count()
        assert 0 < published < len(documents)
        assert token.snapshot().delivered is control_request


def test_clean_rebuild_defers_pause_until_complete_publication(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
) -> None:
    """A clean rebuild publishes all points and metadata before pausing."""
    documents = _write_vault_documents(tmp_path, 16)
    expected_ids = {document.id for document in documents}
    token = RunControlToken()
    gpu_lock = threading.Lock()

    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        indexer = VaultIndexer(
            tmp_path,
            cpu_embedding_model,
            store,
            gpu_lock=gpu_lock,
        )
        seeded = indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
        )
        assert seeded.added == len(documents)
        assert store.get_all_ids() == expected_ids
        metadata_before = indexer._load_meta()
        revised_document = documents[0]
        revised_path = tmp_path / ".vault" / revised_document.path
        revised_marker = "delta content published by the protected rebuild"
        revised_path.write_text(
            f"{revised_path.read_text(encoding='utf-8')}\n{revised_marker}\n",
            encoding="utf-8",
        )

        with ThreadPoolExecutor(max_workers=1) as executor:
            gpu_lock.acquire()
            try:
                rebuild = executor.submit(
                    indexer.full_index,
                    True,
                    reporter=NullProgressReporter(),
                    run_control=token,
                )

                deadline = time.monotonic() + _CONTROL_WAIT_SECONDS
                publication_started = False
                while time.monotonic() < deadline:
                    state = token.snapshot()
                    if state.protected_depth == 1 and store.count() == 0:
                        publication_started = True
                        break
                    time.sleep(_CONTROL_POLL_SECONDS)
                assert publication_started, (
                    "clean rebuild did not reach its protected empty-collection span"
                )

                assert token.request_pause()
                pending = token.snapshot()
                assert pending.desired is ControlRequest.PAUSE
                assert pending.delivered is None
                assert pending.protected_depth == 1

                gpu_lock.release()
                with pytest.raises(PauseRequested):
                    rebuild.result(timeout=_CONTROL_WAIT_SECONDS)
            finally:
                if gpu_lock.locked():
                    gpu_lock.release()

        assert store.get_all_ids() == expected_ids
        metadata_after = indexer._load_meta()
        assert set(metadata_after) == expected_ids
        assert (
            metadata_after[revised_document.id] != metadata_before[revised_document.id]
        )
        stored_document = store.get_by_id(revised_document.id)
        assert stored_document is not None
        assert revised_marker in stored_document["content"]
        final = token.snapshot()
        assert final.delivered is ControlRequest.PAUSE
        assert final.protected_depth == 0


@pytest.mark.parametrize(
    ("control_request", "signal_type"),
    [
        pytest.param(ControlRequest.PAUSE, PauseRequested, id="pause"),
        pytest.param(ControlRequest.CANCEL, CancelRequested, id="cancel"),
    ],
)
def test_code_pipeline_control_unwinds_and_reconciliation_converges(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
    control_request: ControlRequest,
    signal_type: type[RunControlSignal],
) -> None:
    """Pause/cancel unwind producers and consumer before a fresh attempt converges."""
    paths = _write_code_files(tmp_path, 192, "initial")
    token = RunControlToken()

    assert not _code_consumer_threads()
    assert not multiprocessing.active_children()
    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        indexer = CodebaseIndexer(tmp_path, cpu_embedding_model, store)
        with ThreadPoolExecutor(max_workers=1) as executor:
            requester = executor.submit(
                _request_after_first_code_upsert,
                store,
                token,
                control_request,
            )
            with pytest.raises(signal_type):
                indexer.full_index(
                    reporter=NullProgressReporter(),
                    run_control=token,
                )
            requester.result(timeout=_CONTROL_WAIT_SECONDS)

        assert token.snapshot().delivered is control_request
        _assert_code_resources_released()
        published_count = store.count_code()
        published_ids = store.get_all_code_ids()
        assert 0 < published_count < len(paths)
        assert len(published_ids) == published_count

        time.sleep(0.25)
        assert store.count_code() == published_count
        assert store.get_all_code_ids() == published_ids

        reconciled = indexer.full_index(
            reporter=NullProgressReporter(),
            run_control=RunControlToken(),
        )
        assert reconciled.files == len(paths)
        _assert_current_code_state(indexer, store, paths, "initial")

    _assert_code_resources_released()


def test_code_clean_rebuild_defers_pause_until_publication_is_current(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
) -> None:
    """Clean code publication cannot expose an empty or stale collection."""
    paths = _write_code_files(tmp_path, 24, "seed")
    token = RunControlToken()
    gpu_lock = threading.Lock()

    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        indexer = CodebaseIndexer(
            tmp_path,
            cpu_embedding_model,
            store,
            gpu_lock=gpu_lock,
        )
        indexer.full_index(clean=True, reporter=NullProgressReporter())
        _assert_current_code_state(indexer, store, paths, "seed")
        metadata_before = indexer._load_meta()
        paths = _write_code_files(tmp_path, len(paths), "clean-current")

        with ThreadPoolExecutor(max_workers=1) as executor:
            gpu_lock.acquire()
            try:
                rebuild = executor.submit(
                    indexer.full_index,
                    True,
                    reporter=NullProgressReporter(),
                    run_control=token,
                )
                deadline = time.monotonic() + _CONTROL_WAIT_SECONDS
                while time.monotonic() < deadline:
                    state = token.snapshot()
                    if state.protected_depth == 1 and store.count_code() == 0:
                        break
                    time.sleep(_CONTROL_POLL_SECONDS)
                else:
                    raise AssertionError(
                        "clean code rebuild never exposed its protected empty span"
                    )

                assert token.request_pause()
                pending = token.snapshot()
                assert pending.desired is ControlRequest.PAUSE
                assert pending.delivered is None
                assert pending.protected_depth == 1
                assert not rebuild.done()

                gpu_lock.release()
                with pytest.raises(PauseRequested):
                    rebuild.result(timeout=_CONTROL_WAIT_SECONDS)
            finally:
                if gpu_lock.locked():
                    gpu_lock.release()

        _assert_current_code_state(indexer, store, paths, "clean-current")
        metadata_after = indexer._load_meta()
        assert metadata_after.keys() == metadata_before.keys()
        assert all(
            metadata_after[path] != old_hash
            for path, old_hash in metadata_before.items()
        )
        final = token.snapshot()
        assert final.delivered is ControlRequest.PAUSE
        assert final.protected_depth == 0

    _assert_code_resources_released()


def test_code_scoped_replacement_defers_pause_until_data_and_metadata_are_current(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
) -> None:
    """A scoped replacement delivers pause only after new chunks and metadata."""
    paths = _write_code_files(tmp_path, 4, "seed")
    token = RunControlToken()
    gpu_lock = threading.Lock()

    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        indexer = CodebaseIndexer(
            tmp_path,
            cpu_embedding_model,
            store,
            gpu_lock=gpu_lock,
        )
        indexer.full_index(clean=True, reporter=NullProgressReporter())
        changed_path = paths[0]
        rel_path = str(changed_path.relative_to(tmp_path)).replace("\\", "/")
        old_ids = set(store.get_code_ids_by_paths({rel_path}))
        assert old_ids
        metadata_before = indexer._load_meta()
        paths = _write_code_files(tmp_path, len(paths), "scoped-current")

        with ThreadPoolExecutor(max_workers=1) as executor:
            gpu_lock.acquire()
            try:
                replacement = executor.submit(
                    indexer.incremental_index,
                    reporter=NullProgressReporter(),
                    changed_paths=paths,
                    run_control=token,
                )
                deadline = time.monotonic() + _CONTROL_WAIT_SECONDS
                while time.monotonic() < deadline:
                    state = token.snapshot()
                    if state.protected_depth == 1 and not store.get_code_ids_by_paths(
                        {rel_path}
                    ):
                        break
                    time.sleep(_CONTROL_POLL_SECONDS)
                else:
                    raise AssertionError(
                        "scoped replacement never exposed its protected delete span"
                    )

                assert token.request_pause()
                pending = token.snapshot()
                assert pending.desired is ControlRequest.PAUSE
                assert pending.delivered is None
                assert pending.protected_depth == 1
                assert not replacement.done()

                gpu_lock.release()
                with pytest.raises(PauseRequested):
                    replacement.result(timeout=_CONTROL_WAIT_SECONDS)
            finally:
                if gpu_lock.locked():
                    gpu_lock.release()

        new_ids = set(store.get_code_ids_by_paths({rel_path}))
        assert new_ids
        assert new_ids.isdisjoint(old_ids)
        _assert_current_code_state(indexer, store, paths, "scoped-current")
        metadata_after = indexer._load_meta()
        assert metadata_after.keys() == metadata_before.keys()
        assert all(
            metadata_after[path] != old_hash
            for path, old_hash in metadata_before.items()
        )
        final = token.snapshot()
        assert final.delivered is ControlRequest.PAUSE
        assert final.protected_depth == 0

    _assert_code_resources_released()
