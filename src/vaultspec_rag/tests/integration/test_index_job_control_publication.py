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
    _AbortAfterFirstCommitReporter,
    _assert_code_resources_released,
    _assert_current_code_state,
    _CancelAfterCheckpoints,
    _write_code_files,
)


def test_clean_rebuild_reencodes_when_collection_vanished_under_the_ledger(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
) -> None:
    """A rebuild must not trust ledger evidence for a destroyed collection.

    External storage destruction (the storage delete verb) drops the code
    collection but leaves the per-root run ledger behind. Resuming the
    interrupted generation would skip its storage-confirmed units with zero
    encoding, publishing a "successful" index whose committed portion no
    longer exists anywhere. The rebuild must retire that generation and
    re-encode from scratch.
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
                reporter=_AbortAfterFirstCommitReporter(indexer),
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

        # Binds the staleness guard: without it the resumed generation skips
        # its committed units (resumed_units > 0, zero re-encode) and the
        # store is missing exactly those files' chunks while the run still
        # reports success.
        _assert_current_code_state(indexer, store, paths, "ledger-stale")
        fresh = indexer.last_checkpoint
        assert fresh is not None
        assert fresh.resumed_units == 0
        assert store.count_code() == result.added
    _assert_code_resources_released()


def test_incremental_reencodes_when_collection_vanished_under_published_metadata(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
) -> None:
    """An incremental run must not trust carried evidence for a destroyed collection.

    External storage destruction (the storage delete verb) drops the code
    collection but leaves the per-root metadata sidecar and run ledger
    behind. An incremental diff against that carried metadata classifies
    every surviving file as unchanged, skips all encoding, and reports
    success over a collection whose points no longer exist anywhere. The
    incremental path must detect the vanished collection and escalate to a
    full failure-safe reconciliation.
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

        indexer.incremental_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )

        # Binds the incremental staleness guard: without it the unchanged
        # scan trusts the carried metadata, skips every file, and reports a
        # mutation-free success while the store holds zero points.
        _assert_current_code_state(indexer, store, paths, "meta-stale")
        assert store.count_code() == published.added
    _assert_code_resources_released()


def test_an_unattended_gate_publishes_a_generation_without_emptying_the_served_one(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
) -> None:
    """A gate reached without an operator request must not destroy served data.

    The embed-format and config-drift gates fire on a run the watcher asked
    for, not one an operator asked for. Dropping the collection there empties
    it for the whole repopulation, and an interruption in that window leaves a
    fragment beneath a sidecar describing the whole corpus, which makes every
    later run reconcile the entire tree. Reconciling instead keeps every
    published point readable throughout.

    The stale marker is written to the real sidecar, the same class of
    out-of-band mutation as dropping the table above - real on-disk state, not
    a substituted function.

    Proven able to fail: restoring ``clean=True`` on the embed-format gate
    empties the collection and fails the mid-run count assertion below.
    """
    import json as _json

    from ..._index_breadth import code_meta_path
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
        meta_path = code_meta_path(tmp_path)
        raw = _json.loads(meta_path.read_text(encoding="utf-8"))
        raw[EMBED_SCHEMA_KEY] = "superseded-regime"
        meta_path.write_text(_json.dumps(raw), encoding="utf-8")

        # Interrupt the gate's run through the real cooperative-cancel path a
        # job uses. The end state alone cannot tell the two branches apart: a
        # destructive rebuild drops and then repopulates, so once it finishes
        # the count is back where it started. What separates them is the
        # window, and the window is exactly what production observes.
        with contextlib.suppress(CancelRequested):
            indexer.incremental_index(
                reporter=NullProgressReporter(),
                preflight=indexer.preflight_content(),
                run_control=_CancelAfterCheckpoints(40),
            )

        # The point of the whole change: the gate published a new generation
        # rather than dropping the served collection, so an interruption leaves
        # the corpus readable instead of a fragment for the completeness
        # predicate to chase.
        assert store.count_code() >= published.added

        # Give the next run real work, so it publishes rather than returning
        # the unchanged-tree early result. An unchanged incremental never
        # rewrites the sidecar, which is what made the first two placements of
        # the assertion below vacuous.
        paths = _write_code_files(tmp_path, 24, "unattended-gate-republish")

        indexer.incremental_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        _assert_current_code_state(indexer, store, paths, "unattended-gate-republish")
        # Asserted after a run that actually republishes the sidecar. Placed
        # after the cancelled run above it proved nothing: a cancelled run
        # never rewrites the sidecar, so the marker could not have appeared
        # there whether the mitigation existed or not.
        #
        # The gate reaches the non-destructive publication path, not the
        # interim compromise that left superseded points searchable beside the
        # re-encoded ones.
        assert "__code_superseded_regime__" not in indexer._read_meta_raw()

        # An operator asking for a rebuild still gets one; only the unattended
        # path is barred from destroying data.
        rebuilt = indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        assert rebuilt.added > 0
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
                run_control=_CancelAfterCheckpoints(40),
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
        _assert_current_code_state(indexer, store, paths, "interrupted-rebuild")
    _assert_code_resources_released()
