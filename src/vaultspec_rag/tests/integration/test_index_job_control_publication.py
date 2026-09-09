# ruff: noqa: E402
"""Real-behavior integration coverage for cooperative indexing control.

The tests use the production streaming and indexing paths with local Qdrant,
real vault and code files, and a CPU-backed SentenceTransformer model. Keeping
the model tiny makes the control races deterministic without substituting test
implementations for any production indexing behavior.
"""

from __future__ import annotations

import contextlib
import threading
from pathlib import Path  # noqa: TC003

import pytest

from ..._job_errors import JobError, JobErrorKind
from ..._store_models import read_served_code_collection
from ...embeddings import EmbeddingModel  # noqa: TC001
from ...indexer import CodebaseIndexer
from ...job_control import (
    CancelRequested,
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
    AbortAfterFirstCommitReporter,
    CancelAfterCheckpoints,
    _assert_code_resources_released,
    _write_code_files,
    assert_current_code_state,
)


def test_clean_rebuild_resumes_durable_generation_when_served_collection_vanished(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
) -> None:
    """A rebuild may trust generation evidence that survives served deletion.

    External storage destruction (the storage delete verb) drops the code
    collection but leaves both the per-root run ledger and the generation-scoped
    staging collection behind. Its storage-confirmed units remain durable, so
    the rebuild should resume them and publish the completed generation.
    """
    paths = _write_code_files(tmp_path, 128, "ledger-stale")

    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        indexer = CodebaseIndexer(
            tmp_path,
            cpu_embedding_model,
            store,
            options=CodebaseIndexer.Options(gpu_lock=threading.Lock()),
        )
        with pytest.raises(RuntimeError, match="injected mid-rebuild crash"):
            indexer.full_index(
                clean=True,
                reporter=AbortAfterFirstCommitReporter(indexer),
                preflight=indexer.preflight_content(),
            )
        interrupted = indexer.last_checkpoint
        assert interrupted is not None
        committed = interrupted.ledger.committed_unit_count(interrupted.generation_id)
        assert committed > 0, "the crash must land after storage-confirmed progress"

        # The storage-delete equivalent: the collection vanishes out-of-band
        # while the per-root run ledger (index_runs.sqlite3) stays behind.
        store.drop_code_table()

        result = indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )

        # The completed generation contains every expected point, including the
        # durable units resumed from staging after the served collection was
        # removed.
        assert_current_code_state(indexer, store, paths, "ledger-stale")
        fresh = indexer.last_checkpoint
        assert fresh is not None
        assert fresh.resumed_units == committed
        assert store.count_code() == result.added
    _assert_code_resources_released()


def test_incremental_requires_explicit_rebuild_when_collection_vanished(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
) -> None:
    """An incremental run must not trust carried evidence for a destroyed collection.

    External storage destruction (the storage delete verb) drops the code
    collection but leaves the per-root metadata sidecar and run ledger
    behind. An incremental diff against that carried metadata classifies
    every surviving file as unchanged, skips all encoding, and reports
    success over a collection whose points no longer exist anywhere. The
    incremental path must detect the vanished collection and require an
    explicit full reconciliation.
    """
    paths = _write_code_files(tmp_path, 32, "meta-stale")

    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        indexer = CodebaseIndexer(
            tmp_path,
            cpu_embedding_model,
            store,
            options=CodebaseIndexer.Options(gpu_lock=threading.Lock()),
        )
        published = indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        assert published.added > 0

        # The storage-delete equivalent: the collection vanishes out-of-band
        # while the metadata sidecar and per-root run ledger stay behind.
        store.drop_code_table()

        with pytest.raises(JobError) as raised:
            indexer.incremental_index(
                reporter=NullProgressReporter(),
                preflight=indexer.preflight_content(),
            )
        assert raised.value.error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
        assert store.count_code() == 0

        indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )

        # After explicit operator authority, the full rebuild restores every
        # point described by the source tree.
        assert_current_code_state(indexer, store, paths, "meta-stale")
        assert store.count_code() == published.added
    _assert_code_resources_released()


def test_embed_format_gate_requires_explicit_rebuild_without_emptying_served_index(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
) -> None:
    """An embed-format gate refuses incrementals without destroying served data."""
    import json as _json

    from ..._index_breadth import index_meta_path
    from ..._source_types import PublicSourceType
    from ...indexer._code_meta import EMBED_SCHEMA_KEY

    paths = _write_code_files(tmp_path, 24, "unattended-gate")

    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        indexer = CodebaseIndexer(
            tmp_path,
            cpu_embedding_model,
            store,
            options=CodebaseIndexer.Options(gpu_lock=threading.Lock()),
        )
        published = indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        assert published.added > 0

        # Age the embed-format marker so the unattended gate fires on the next
        # incremental, exactly as it would after a format change shipped.
        meta_path = index_meta_path(tmp_path, PublicSourceType.CODE)
        raw = _json.loads(meta_path.read_text(encoding="utf-8"))
        raw[EMBED_SCHEMA_KEY] = "superseded-regime"
        meta_path.write_text(_json.dumps(raw), encoding="utf-8")

        with pytest.raises(JobError) as raised:
            indexer.incremental_index(
                reporter=NullProgressReporter(),
                preflight=indexer.preflight_content(),
            )
        assert raised.value.error_kind is JobErrorKind.FULL_REINDEX_REQUIRED

        assert store.count_code() == published.added

        paths = _write_code_files(tmp_path, 24, "explicit-gate-rebuild")
        rebuilt = indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        assert rebuilt.added > 0
        assert_current_code_state(indexer, store, paths, "explicit-gate-rebuild")
        assert "__code_superseded_regime__" not in indexer._read_meta_raw()
        assert store.count_code() == rebuilt.added
    _assert_code_resources_released()


def test_an_interrupted_rebuild_leaves_the_served_index_fully_readable(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
) -> None:
    """A rebuild interrupted mid-build must not cost the served index a point.

    This is what building beside the served collection buys. Before, a clean
    rebuild dropped first and repopulated after, so an interruption left a
    fragment beneath a sidecar describing the whole corpus - the latch that
    made every later run reconcile the entire tree.

    The interruption uses the real cooperative-cancel path a job uses, and the
    cancel point is past where the old destructive rebuild reached its drop.

    Proven able to fail: reverting the clean branch to the old destructive path
    - targeting the served collection and dropping it up front - empties it
    here and fails the served-count assertion with 0 == 24.
    """
    paths = _write_code_files(tmp_path, 24, "interrupted-rebuild")

    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        indexer = CodebaseIndexer(
            tmp_path,
            cpu_embedding_model,
            store,
            options=CodebaseIndexer.Options(gpu_lock=threading.Lock()),
        )
        published = indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        assert published.added > 0
        served_before = store.CODE_TABLE_NAME

        with contextlib.suppress(CancelRequested):
            indexer.full_index(
                clean=True,
                reporter=NullProgressReporter(),
                preflight=indexer.preflight_content(),
                run_control=CancelAfterCheckpoints(40),
            )

        # The served collection answered throughout and still holds everything
        # the previous publication claimed.
        assert store.count_code(served_before) == published.added
        # The pointer never moved, so a reader still resolves the old
        # collection rather than the abandoned generation.
        assert read_served_code_collection(tmp_path) in (None, served_before)

        # A later completed rebuild publishes and the pointer moves.
        rebuilt = indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        assert rebuilt.added > 0
        assert read_served_code_collection(tmp_path) == store.CODE_TABLE_NAME
        assert_current_code_state(indexer, store, paths, "interrupted-rebuild")
    _assert_code_resources_released()
