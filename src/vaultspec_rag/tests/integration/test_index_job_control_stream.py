# ruff: noqa: E402
"""Real-behavior integration coverage for cooperative indexing control.

The tests use the production streaming and indexing paths with local Qdrant,
real vault and code files, and a CPU-backed SentenceTransformer model. Keeping
the model tiny makes the control races deterministic without substituting test
implementations for any production indexing behavior.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path  # noqa: TC003

import pytest

from ...embeddings import EmbeddingModel  # noqa: TC001
from ...indexer import VaultIndexer
from ...indexer._streaming import VaultStreamRequest, _stream_encode_and_upsert_vault
from ...job_control import (
    CancelRequested,
    ControlRequest,
    PauseRequested,
    RunControlSignal,
    RunControlToken,
)
from ...progress import NullProgressReporter
from ...store_runtime import VaultStore

pytestmark = pytest.mark.integration

_CONTROL_WAIT_SECONDS = 20.0
# Generous on purpose. These waits bound a real job - process-pool chunking, a
# real encode of the whole corpus, then publication - on whatever machine the
# suite happens to run on. A bound tuned to an idle machine turns ordinary load
# into a failure, and a suite that fails under load cannot be used to judge
# whether a change regressed anything: the A/B it is asked for returns noise.
# Sixty seconds was such a bound; a passing run of the managed rebuild took
# 68.8s wall-clock on a host also running the resident daemon. The only thing
# these should catch is a job that has genuinely stopped making progress.
_MANAGED_WAIT_SECONDS = 240.0
_CONTROL_POLL_SECONDS = 0.001

from ._index_job_control_support import (
    _RevisedVaultPublication,
    assert_revised_vault_publication,
    pause_clean_vault_rebuild,
    request_after_first_upsert,
    write_vault_documents,
)


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
    documents = write_vault_documents(tmp_path, 128)
    token = RunControlToken()

    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        store.ensure_table()
        with ThreadPoolExecutor(max_workers=1) as executor:
            requester = executor.submit(
                request_after_first_upsert,
                store,
                token,
                control_request,
            )
            with pytest.raises(signal_type):
                _stream_encode_and_upsert_vault(
                    VaultStreamRequest(
                        docs=documents,
                        slice_size=1,
                        model=cpu_embedding_model,
                        store=store,
                        gpu_lock=None,
                        reporter=NullProgressReporter(),
                        run_control=token,
                    )
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
    documents = write_vault_documents(tmp_path, 16)
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

        pause_clean_vault_rebuild(indexer, store, token, gpu_lock)
        assert_revised_vault_publication(
            indexer,
            store,
            _RevisedVaultPublication(
                expected_ids,
                revised_document.id,
                metadata_before,
                revised_marker,
            ),
            token,
        )
