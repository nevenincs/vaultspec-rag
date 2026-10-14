"""Admission turns the first index of a never-built source into a full build.

The readings are taken against a real run ledger and a real local store, so
the predicate is exercised over the same two facts production reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from .._job_admission import (
    SourceAdmissionReading,
    SourcePublication,
    index_job_spec,
    is_new_source,
    read_source_admission,
)
from .._source_types import PublicSourceType
from .._store_models import CodeChunk, generation_code_collection
from ..indexer._run_ledger_models import RunAuthority
from ..job_models import (
    FIRST_BUILD_OPERATION,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
)
from ..registry import get_registry
from ._publication_assertions import publish_empty_vault_proof
from ._state_fixtures import reset_registry

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..service import ServiceRegistry

pytestmark = pytest.mark.unit


@pytest.fixture
def isolated_registry() -> Generator[ServiceRegistry]:
    """Build and discard the process-wide registry around one admission."""
    reset_registry()
    registry = get_registry()
    try:
        yield registry
    finally:
        reset_registry()


def _admit(
    root: Path,
    *,
    source: JobSource = JobSource.CODE,
    clean: bool = False,
    initiator_kind: str = "cli",
) -> JobSpec:
    """Admit one index request the way every adapter admits it."""
    return index_job_spec(
        root,
        source=source,
        clean=clean,
        authority=RunAuthority.REBUILD if clean else RunAuthority.PUBLICATION,
        initiator_kind=initiator_kind,
    )


def _store_one_code_point(
    root: Path,
    registry: ServiceRegistry,
    *,
    generation_id: str | None = None,
) -> str:
    """Write one real code point and return the collection now holding it.

    With *generation_id*, it lands in the collection a rebuild generation of
    that id writes into, which is what an interrupted build leaves behind.
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
                    id="src/stored.py#c0",
                    path="src/stored.py",
                    language="python",
                    content="def stored() -> None:\n    return None\n",
                    line_start=1,
                    line_end=2,
                    node_type="function_definition",
                    function_name="stored",
                    class_name=None,
                    vector=[0.1] * store._embedding_dim,
                )
            ],
            write_policy=None,
            collection=collection,
        )
        return collection


def _collection_points(
    root: Path,
    registry: ServiceRegistry,
    collection: str,
) -> int:
    """Count one exact code collection, naming it rather than resolving it.

    Deliberately not the admission reading: a test proving what that reading
    has to cover cannot establish its own setup with it.
    """
    with registry.lease_store(root) as store:
        return store.count_code(collection)


def test_no_publication_and_no_points_is_the_only_new_reading() -> None:
    """Both readings have to agree before a source counts as never built."""
    assert is_new_source(
        SourceAdmissionReading(
            publication=SourcePublication.ABSENT,
            stored_points=0,
        )
    )


@pytest.mark.parametrize(
    ("publication", "stored_points"),
    [
        # Mutation proven by widening ``is_new_source`` to ignore the point
        # count: points with no publication are what the typed rebuild
        # refusal exists for, and a first build must never delete them.
        pytest.param(SourcePublication.ABSENT, 1, id="points-without-publication"),
        # Mutation proven by accepting any non-published reading: an
        # unreadable ledger, a foreign backend's proof, or an open receipt
        # is not evidence that nothing was ever built here.
        pytest.param(SourcePublication.UNREADABLE, 0, id="unreadable-publication"),
        # Mutation proven by treating an unreadable count as zero: a count
        # nobody could take is an absence of reading, not a reading of zero.
        pytest.param(SourcePublication.ABSENT, None, id="uncountable-storage"),
        pytest.param(SourcePublication.PUBLISHED, 0, id="published-and-empty"),
        pytest.param(SourcePublication.PUBLISHED, 12, id="published-with-points"),
    ],
)
def test_anything_short_of_never_built_is_not_new(
    publication: SourcePublication,
    stored_points: int | None,
) -> None:
    """Every other combination keeps the typed rebuild refusal."""
    assert not is_new_source(
        SourceAdmissionReading(
            publication=publication,
            stored_points=stored_points,
        )
    )


def test_a_never_indexed_root_reads_as_absent_and_empty(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
) -> None:
    """Both production readings agree on a root nothing has ever indexed."""
    del isolated_registry
    root = tmp_path / "never-indexed"
    root.mkdir()

    for source in (
        PublicSourceType.VAULT,
        PublicSourceType.CODE,
        PublicSourceType.DOCUMENT,
    ):
        reading = read_source_admission(root, source)
        assert reading == SourceAdmissionReading(
            publication=SourcePublication.ABSENT,
            stored_points=0,
        ), f"{source.value} did not read as never built"


def test_a_completed_publication_reads_as_published(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
) -> None:
    """A real committed proof is read as a completed publication."""
    del isolated_registry
    root = tmp_path / "published-root"
    publish_empty_vault_proof(root)

    assert read_source_admission(root, PublicSourceType.VAULT) == (
        SourceAdmissionReading(
            publication=SourcePublication.PUBLISHED,
            stored_points=0,
        )
    )


def test_an_incremental_request_for_a_new_source_is_admitted_as_a_first_build(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
) -> None:
    """Each source's first index runs the reset-first lifecycle a rebuild runs."""
    del isolated_registry
    root = tmp_path / "first-build"
    root.mkdir()

    for source in (JobSource.VAULT, JobSource.CODE, JobSource.DOCUMENT):
        spec = _admit(root, source=source)
        assert spec.mode is JobMode.REBUILD, source.value
        assert spec.authority is RunAuthority.REBUILD, source.value
        assert spec.requested_mode is JobMode.INCREMENTAL, source.value
        assert spec.is_first_build, source.value
        assert spec.requested_operation == JobMode.INCREMENTAL.value
        assert spec.effective_operation == FIRST_BUILD_OPERATION


def test_stored_points_without_a_publication_keep_the_incremental_request(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
) -> None:
    """Admission refuses to escalate over content no proof accounts for.

    Mutation proven by dropping the point reading from ``is_new_source``:
    this request then escalates and the reset deletes the stored point.
    """
    root = tmp_path / "points-without-proof"
    collection = _store_one_code_point(root, isolated_registry)
    assert _collection_points(root, isolated_registry, collection) == 1

    spec = _admit(root, source=JobSource.CODE)

    assert spec.mode is JobMode.INCREMENTAL
    assert spec.authority is RunAuthority.PUBLICATION
    assert spec.requested_mode is None
    assert not spec.is_first_build
    assert _collection_points(root, isolated_registry, collection) == 1, (
        "admission touched stored points"
    )


def test_an_interrupted_builds_generation_points_keep_the_request(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
) -> None:
    """A generation-scoped leftover is content the first build would destroy.

    An interrupted code build writes into its own collection, which a reset
    of this source owns and removes. Reading only the served collection would
    call this root empty.

    Mutation proven by counting the canonical collection alone in
    ``reset_scope_point_count``: this request then escalates, and the reset
    deletes the interrupted build's points.
    """
    root = tmp_path / "generation-leftover"
    collection = _store_one_code_point(
        root,
        isolated_registry,
        generation_id="deadbeef",
    )
    assert _collection_points(root, isolated_registry, collection) == 1
    with isolated_registry.lease_store(root) as store:
        assert store.count_code() == 0, "the served collection should be empty"

    spec = _admit(root, source=JobSource.CODE)

    assert spec.mode is JobMode.INCREMENTAL
    assert not spec.is_first_build
    assert _collection_points(root, isolated_registry, collection) == 1


def test_a_published_source_keeps_the_incremental_request(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
) -> None:
    """A source with a completed publication is never a first build again."""
    del isolated_registry
    root = tmp_path / "already-published"
    publish_empty_vault_proof(root)

    spec = _admit(root, source=JobSource.VAULT)

    assert spec.mode is JobMode.INCREMENTAL
    assert spec.effective_operation == JobMode.INCREMENTAL.value


def test_each_source_of_one_root_is_admitted_independently(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
) -> None:
    """One root can have a built source and a never-built one at once.

    Selecting every source fans out to one admission per source, so a vault
    that has published does not make the code index of the same root anything
    other than its first build.
    """
    del isolated_registry
    root = tmp_path / "mixed-root"
    publish_empty_vault_proof(root)

    assert not _admit(root, source=JobSource.VAULT).is_first_build
    assert _admit(root, source=JobSource.CODE).is_first_build
    assert _admit(root, source=JobSource.DOCUMENT).is_first_build


@pytest.mark.parametrize("initiator_kind", ["watcher", "integrity"])
def test_automatic_origins_never_start_a_first_build(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
    initiator_kind: str,
) -> None:
    """Watcher and integrity work keeps its bounded automatic scope.

    Mutation proven by removing the origin test from ``index_job_spec``:
    both origins then admit a full corpus build nobody requested.
    """
    del isolated_registry
    root = tmp_path / f"automatic-{initiator_kind}"
    root.mkdir()

    spec = _admit(root, source=JobSource.CODE, initiator_kind=initiator_kind)

    assert spec.mode is JobMode.INCREMENTAL
    assert spec.authority is RunAuthority.PUBLICATION
    assert not spec.is_first_build


def test_an_explicit_rebuild_is_not_relabelled_as_a_first_build(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
) -> None:
    """An operator who asked for a rebuild is told they got a rebuild."""
    del isolated_registry
    root = tmp_path / "explicit-rebuild"
    root.mkdir()

    spec = _admit(root, source=JobSource.CODE, clean=True)

    assert spec.mode is JobMode.REBUILD
    assert spec.requested_mode is None
    assert spec.requested_operation == JobMode.REBUILD.value
    assert spec.effective_operation == JobMode.REBUILD.value


def test_a_requested_mode_records_only_an_admitted_first_build() -> None:
    """The specification refuses to express any other escalation.

    Mutation proven by deleting the ``requested_mode`` check in
    ``JobSpec.__post_init__``: a rebuild request then persists as though it
    had been admitted as something else entirely.
    """
    with pytest.raises(ValueError, match="admitted as a first build"):
        JobSpec(
            operation=JobOperation.INDEX,
            source=JobSource.CODE,
            project_root="/tmp/root",
            mode=JobMode.INCREMENTAL,
            authority=RunAuthority.PUBLICATION,
            requested_mode=JobMode.INCREMENTAL,
        )


def test_a_first_build_specification_round_trips_through_persistence() -> None:
    """A restored first build keeps both operations it was admitted with."""
    from ..job_models import (
        DesiredJobState,
        JobAttempt,
        JobCapabilities,
        JobResourceSnapshot,
        JobRuntimeSnapshot,
        JobSnapshot,
        JobState,
        JobTimestamps,
    )
    from ..job_persistence import _job_spec_from_dict

    spec = JobSpec(
        operation=JobOperation.INDEX,
        source=JobSource.CODE,
        project_root="/tmp/root",
        mode=JobMode.REBUILD,
        authority=RunAuthority.REBUILD,
        requested_mode=JobMode.INCREMENTAL,
    )
    record = JobSnapshot(
        id="job",
        revision=1,
        spec=spec,
        state=JobState.QUEUED,
        desired_state=DesiredJobState.RUNNING,
        capabilities=JobCapabilities(
            pausable=False,
            resumable=False,
            cancellable=True,
            retryable=False,
            deletable=False,
        ),
        attempt=JobAttempt(number=1),
        timestamps=JobTimestamps(created_at=1.0, state_changed_at=1.0),
        progress=None,
        result=None,
        error_kind=None,
        initiator=JobInitiator(
            kind="cli",
            command="reindex_codebase",
            project_root="/tmp/root",
        ),
        runtime=JobRuntimeSnapshot(
            pid=1,
            parent_pid=1,
            user="tester",
            executable="python",
            prefix="prefix",
            base_prefix="prefix",
            virtual_env=None,
        ),
        resources=JobResourceSnapshot(started=None, finished=None),
    ).to_dict()
    served = cast("dict[str, object]", record["spec"])

    assert served["requested_mode"] == JobMode.INCREMENTAL.value
    assert served["effective_mode"] == FIRST_BUILD_OPERATION
    assert _job_spec_from_dict(served) == spec


def test_a_record_without_a_requested_mode_restores_as_one_operation() -> None:
    """A job written before the field existed carries no escalation."""
    from ..job_persistence import _job_spec_from_dict

    restored = _job_spec_from_dict(
        {
            "operation": JobOperation.INDEX.value,
            "source": JobSource.CODE.value,
            "project_root": "/tmp/root",
            "mode": JobMode.INCREMENTAL.value,
            "authority": RunAuthority.PUBLICATION.value,
        }
    )

    assert restored.requested_mode is None
    assert not restored.is_first_build
