"""A never-built source's first index runs as its full build, end to end.

The jobs are the production managed jobs: real admission, real local Qdrant,
the session's real GPU embedding model, and the canonical publication
authority. Nothing here stands in for indexing behaviour.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

import pytest

from ... import jobs
from ..._source_types import PublicSourceType
from ..._store_models import CodeChunk, generation_code_collection
from ...indexer._run_ledger_models import (
    RunAuthority,
    RunOperation,
    RunTerminalState,
)
from ...indexer._vault_checkpoint import VaultRunCheckpoint
from ...job_control import NO_RUN_CONTROL
from ...job_models import FIRST_BUILD_OPERATION, JobState
from ...progress import NullProgressReporter
from ...store_runtime import configured_backend_identity
from .._publication_assertions import published_content_identities
from ._index_job_control_support import (
    _wait_for_managed_job,
    _write_code_files,
    write_vault_documents,
)

if TYPE_CHECKING:
    from ...job_manager.manager import JobManager
    from ...job_models import JobSnapshot
    from ...service import ServiceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.timeout(600)]


def _succeeded(snapshot: JobSnapshot) -> bool:
    return snapshot.state is JobState.SUCCEEDED


def _terminal(snapshot: JobSnapshot) -> bool:
    return snapshot.state.is_terminal


def _store_one_code_point(
    root: Path,
    registry: ServiceRegistry,
    *,
    generation_id: str | None = None,
) -> str:
    """Write one real code point and return the collection now holding it.

    With *generation_id*, the point lands in the collection a rebuild
    generation of that id writes into - the collection an interrupted build
    leaves behind, which a reset of this source owns.
    """
    root.mkdir(parents=True, exist_ok=True)
    with registry.lease_store(root) as store:
        collection = (
            store.CODE_TABLE_NAME
            if generation_id is None
            else generation_code_collection(
                store.DERIVED_CODE_TABLE_NAME, generation_id
            )
        )
        store.upsert_code_chunks(
            [
                CodeChunk(
                    id="src/unaccounted.py#c0",
                    path="src/unaccounted.py",
                    language="python",
                    content="def unaccounted() -> None:\n    return None\n",
                    line_start=1,
                    line_end=2,
                    node_type="function_definition",
                    function_name="unaccounted",
                    class_name=None,
                    vector=[0.1] * store._embedding_dim,
                )
            ],
            write_policy=None,
            collection=collection,
        )
        return collection


def _collection_points(root: Path, registry: ServiceRegistry, collection: str) -> int:
    """Count one exact code collection, naming it rather than resolving it.

    Deliberately not the admission reading: a test proving what that reading
    has to cover cannot establish its own setup with it.
    """
    with registry.lease_store(root) as store:
        return store.count_code(collection)


def _assert_reported_as_a_first_build(snapshot: JobSnapshot) -> None:
    """Require the record to name both the request and what actually ran."""
    served = snapshot.to_dict()["spec"]
    assert isinstance(served, dict)
    assert served["requested_mode"] == "incremental"
    assert served["effective_mode"] == FIRST_BUILD_OPERATION
    assert served["authority"] == RunAuthority.REBUILD.value


async def test_a_new_vault_source_publishes_without_an_explicit_rebuild(
    tmp_path: Path,
    managed_facade_registry: ServiceRegistry,
    managed_job_manager: JobManager,
) -> None:
    """The first vault index of a new root succeeds as that source's build."""
    root = tmp_path / "new-vault"
    documents = write_vault_documents(root, 8)

    job_id = jobs.start_reindex_vault(
        root,
        clean=False,
        authority=RunAuthority.PUBLICATION,
        initiator_kind="cli",
    )
    snapshot = await _wait_for_managed_job(
        managed_job_manager,
        job_id,
        _succeeded,
        "the first vault index of a new root did not succeed",
    )

    _assert_reported_as_a_first_build(snapshot)
    assert set(published_content_identities(root, PublicSourceType.VAULT)) == {
        document.id for document in documents
    }
    assert managed_facade_registry.vault_doc_count(root) > 0


async def test_a_new_code_source_publishes_without_an_explicit_rebuild(
    tmp_path: Path,
    managed_facade_registry: ServiceRegistry,
    managed_job_manager: JobManager,
) -> None:
    """The first code index of a new root succeeds as that source's build."""
    root = tmp_path / "new-code"
    paths = _write_code_files(root, 8, "first-build")

    job_id = jobs.start_reindex_codebase(
        root,
        clean=False,
        authority=RunAuthority.PUBLICATION,
        initiator_kind="cli",
    )
    snapshot = await _wait_for_managed_job(
        managed_job_manager,
        job_id,
        _succeeded,
        "the first code index of a new root did not succeed",
    )

    _assert_reported_as_a_first_build(snapshot)
    assert set(published_content_identities(root, PublicSourceType.CODE)) == {
        path.relative_to(root).as_posix() for path in paths
    }
    assert managed_facade_registry.code_chunk_count(root) > 0


async def test_a_new_document_source_publishes_without_an_explicit_rebuild(
    tmp_path: Path,
    managed_facade_registry: ServiceRegistry,
    managed_job_manager: JobManager,
) -> None:
    """A new document source publishes its first build with no routed input.

    Documents are admitted only through an approved extraction route, so a
    root with none has an empty document corpus. The first build still has to
    complete and publish: an empty published corpus is what makes a later
    absence authoritative.
    """
    root = tmp_path / "new-document"
    root.mkdir()

    job_id = jobs.start_reindex_documents(
        root,
        clean=False,
        authority=RunAuthority.PUBLICATION,
        initiator_kind="cli",
    )
    snapshot = await _wait_for_managed_job(
        managed_job_manager,
        job_id,
        _succeeded,
        "the first document index of a new root did not succeed",
    )

    _assert_reported_as_a_first_build(snapshot)
    assert published_content_identities(root, PublicSourceType.DOCUMENT) == {}
    assert managed_facade_registry.document_chunk_count(root) == 0


async def test_a_watcher_origin_incremental_on_a_new_source_is_refused(
    tmp_path: Path,
    managed_facade_registry: ServiceRegistry,
    managed_job_manager: JobManager,
) -> None:
    """Automatic convergence never starts a full corpus build.

    Mutation proven by removing the origin test from ``index_job_spec``: the
    watcher-origin job then succeeds as a first build instead of reporting
    ``full_reindex_required``.
    """
    root = tmp_path / "watcher-origin"
    write_vault_documents(root, 4)

    job_id = jobs.start_reindex_vault(
        root,
        clean=False,
        authority=RunAuthority.PUBLICATION,
        initiator_kind="watcher",
    )
    snapshot = await _wait_for_managed_job(
        managed_job_manager,
        job_id,
        _terminal,
        "the watcher-origin index did not reach a terminal state",
    )

    assert snapshot.state is JobState.FAILED
    assert snapshot.error_kind == "full_reindex_required"
    assert snapshot.spec.requested_mode is None
    assert managed_facade_registry.vault_doc_count(root) == 0


async def test_points_without_a_publication_refuse_the_first_build(
    tmp_path: Path,
    managed_facade_registry: ServiceRegistry,
    managed_job_manager: JobManager,
) -> None:
    """Content no proof accounts for keeps the typed refusal, and survives it.

    Mutation proven by dropping the point reading from ``is_new_source``:
    the job then resets the collection and the stored point is gone.
    """
    root = tmp_path / "points-without-proof"
    _write_code_files(root, 4, "unaccounted")
    collection = _store_one_code_point(root, managed_facade_registry)
    assert _collection_points(root, managed_facade_registry, collection) == 1

    job_id = jobs.start_reindex_codebase(
        root,
        clean=False,
        authority=RunAuthority.PUBLICATION,
        initiator_kind="cli",
    )
    snapshot = await _wait_for_managed_job(
        managed_job_manager,
        job_id,
        _terminal,
        "the refused incremental index did not reach a terminal state",
    )

    assert snapshot.state is JobState.FAILED
    assert snapshot.error_kind == "full_reindex_required"
    assert snapshot.spec.requested_mode is None
    # The refusal names the absent publication. Reporting that storage no
    # longer backs published metadata here described a loss that cannot have
    # happened: nothing was ever published for this source.
    assert "publication proof does not exist" in str(snapshot.result)
    assert "storage no longer backs" not in str(snapshot.result)
    assert _collection_points(root, managed_facade_registry, collection) == 1


async def test_an_interrupted_builds_generation_points_refuse_the_first_build(
    tmp_path: Path,
    managed_facade_registry: ServiceRegistry,
    managed_job_manager: JobManager,
) -> None:
    """Points an interrupted build left in its own collection refuse too.

    No ledger, an empty served collection, and one generation-scoped
    collection holding a point. A reset of this source owns and removes that
    collection, so admitting a first build here would destroy content no
    proof accounts for - exactly what the refusal protects.

    Mutation proven by counting the canonical collection alone in
    ``reset_scope_point_count``: the job then succeeds as a first build and
    the generation's point is gone.
    """
    root = tmp_path / "generation-leftover"
    _write_code_files(root, 4, "leftover")
    collection = _store_one_code_point(
        root,
        managed_facade_registry,
        generation_id="c0ffee01",
    )
    assert _collection_points(root, managed_facade_registry, collection) == 1
    assert managed_facade_registry.code_chunk_count(root) == 0

    job_id = jobs.start_reindex_codebase(
        root,
        clean=False,
        authority=RunAuthority.PUBLICATION,
        initiator_kind="cli",
    )
    snapshot = await _wait_for_managed_job(
        managed_job_manager,
        job_id,
        _terminal,
        "the refused incremental index did not reach a terminal state",
    )

    assert snapshot.state is JobState.FAILED
    assert snapshot.error_kind == "full_reindex_required"
    assert snapshot.spec.requested_mode is None
    assert _collection_points(root, managed_facade_registry, collection) == 1


async def test_a_first_build_that_failed_without_points_is_a_first_build_again(
    tmp_path: Path,
    managed_facade_registry: ServiceRegistry,
    managed_job_manager: JobManager,
) -> None:
    """An interrupted first build that published nothing leaves a new source.

    The ledger carries a failed full generation and no proof, and the
    canonical collection is still empty, so the next explicit incremental
    request is that source's first build again rather than a refusal.
    """
    root = tmp_path / "failed-first-build"
    documents = write_vault_documents(root, 6)
    interrupted = VaultRunCheckpoint.open(
        root,
        backend_identity=configured_backend_identity(root),
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=NO_RUN_CONTROL,
    )
    interrupted.ledger.finish_generation(
        interrupted.generation_id,
        RunTerminalState.FAILED,
        detail="the first build ended before it published anything",
    )
    assert managed_facade_registry.vault_doc_count(root) == 0

    job_id = jobs.start_reindex_vault(
        root,
        clean=False,
        authority=RunAuthority.PUBLICATION,
        initiator_kind="cli",
    )
    snapshot = await _wait_for_managed_job(
        managed_job_manager,
        job_id,
        _succeeded,
        "the retried first vault build did not succeed",
    )

    _assert_reported_as_a_first_build(snapshot)
    assert set(published_content_identities(root, PublicSourceType.VAULT)) == {
        document.id for document in documents
    }


async def test_an_in_process_index_builds_every_new_source_of_a_root(
    tmp_path: Path,
    managed_run_config: ServiceRegistry,
) -> None:
    """The in-process route admits each selected source on its own history.

    No job and no service: this is the public facade the borrowed-GPU CLI run
    calls. Selecting every domain fans out to one request per domain, so each
    reads its own publication and storage and builds itself.
    """
    from ... import api

    root = tmp_path / "in-process-new"
    write_vault_documents(root, 4)
    _write_code_files(root, 4, "in-process")

    outcomes = api.index_all(
        root,
        api.AllIndexOptions(clean=False, reporter=NullProgressReporter()),
    )

    for name, outcome in (
        ("vault", outcomes.vault),
        ("code", outcomes.code),
        ("document", outcomes.document),
    ):
        assert outcome.error is None, f"{name} failed: {outcome.error}"
        assert outcome.result is not None
        assert outcome.result.first_build, f"{name} did not run as a first build"
    assert set(published_content_identities(root, PublicSourceType.VAULT))
    assert set(published_content_identities(root, PublicSourceType.CODE))
    assert published_content_identities(root, PublicSourceType.DOCUMENT) == {}
    assert managed_run_config.vault_doc_count(root) > 0
    assert managed_run_config.code_chunk_count(root) > 0


async def test_an_in_process_index_of_a_published_source_stays_incremental(
    tmp_path: Path,
    managed_run_config: ServiceRegistry,
) -> None:
    """A second in-process index of the same source updates rather than builds."""
    from ... import api

    root = tmp_path / "in-process-twice"
    write_vault_documents(root, 3)
    first = api.index(root, reporter=NullProgressReporter())
    assert first.first_build

    second = api.index(root, reporter=NullProgressReporter())

    assert not second.first_build
    assert managed_run_config.vault_doc_count(root) > 0


async def test_an_in_process_index_refuses_over_points_without_a_publication(
    tmp_path: Path,
    managed_run_config: ServiceRegistry,
) -> None:
    """The in-process route keeps the refusal, and the points with it.

    In process there is no job record to carry a typed kind, so the refusal
    is the failure the indexer raises; what makes it the same refusal is that
    its text classifies as ``full_reindex_required`` through the one
    classifier every adapter reads. Asserting the exception class instead
    would pin which layer happens to raise it.

    Mutation proven by dropping the never-built test from
    ``api.index_codebase``: the call then runs a first build over this
    content instead of refusing, so nothing is raised at all.
    """
    from ... import api
    from ..._job_errors import JobErrorKind, classify_error_text

    root = tmp_path / "in-process-unaccounted"
    _write_code_files(root, 3, "unaccounted")
    collection = _store_one_code_point(root, managed_run_config)
    assert _collection_points(root, managed_run_config, collection) == 1

    # The exception class is deliberately not pinned: what makes this the
    # same refusal is the classification below.
    with pytest.raises(Exception) as refused:
        api.index_codebase(
            root,
            api.CodeIndexOptions(reporter=NullProgressReporter()),
        )

    assert classify_error_text(str(refused.value)) is (
        JobErrorKind.FULL_REINDEX_REQUIRED
    )
    assert _collection_points(root, managed_run_config, collection) == 1
