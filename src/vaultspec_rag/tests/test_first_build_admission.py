"""Admission turns the first index of a never-built source into a full build.

The readings are taken against a real run ledger and a real local store, so
the predicate is exercised over the same two facts production reads.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, cast

import pytest

from .._job_admission import (
    SourceAdmissionReading,
    SourcePublication,
    admit_index_job,
    admits_first_build,
    index_job_spec,
    is_new_source,
    read_source_admission,
)
from .._source_types import PublicSourceType
from .._store_models import CodeChunk, generation_code_collection
from .._store_writes import workspace_volume_path
from ..indexer._run_ledger_models import RunAuthority, index_run_ledger_path
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
    """A real committed proof is read as a completed publication.

    No point count is taken: a published source is not new whatever storage
    holds, so opening and locking a backend to compute a number that cannot
    change the answer is work every incremental index would pay for.
    """
    del isolated_registry
    root = tmp_path / "published-root"
    publish_empty_vault_proof(root)

    assert read_source_admission(root, PublicSourceType.VAULT) == (
        SourceAdmissionReading(
            publication=SourcePublication.PUBLISHED,
            stored_points=None,
        )
    )


def test_a_ledger_that_is_not_a_database_refuses_without_a_warning(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A corrupt run ledger is one of the publications known to be unreadable.

    Admission answers the HTTP routes behind the CLI and MCP adapters one
    domain at a time, so a ledger nobody can read has to refuse that source
    rather than fail the whole request. The ledger converts corruption into
    its own typed failure, which is in the set this reads through - and a
    publication already accounted for as unreadable is not a surprise: an old
    or contended ledger reaches the same branch on ordinary read paths, where
    a warning per read would be noise.

    Mutation proven by narrowing the set in ``_read_source_publication`` to
    ``ProofUnverifiableError``: the ledger's corruption then falls through to
    the catch-all, which reports it as unaccounted-for.
    """
    del isolated_registry
    root = tmp_path / "corrupt-ledger"
    root.mkdir()
    ledger_path = index_run_ledger_path(workspace_volume_path(root.resolve()))
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_bytes(b"this is not a database, it is 32 bytes of text.\n")

    with caplog.at_level("WARNING", logger="vaultspec_rag.jobs"):
        for source in (
            PublicSourceType.VAULT,
            PublicSourceType.CODE,
            PublicSourceType.DOCUMENT,
        ):
            assert read_source_admission(root, source) == SourceAdmissionReading(
                publication=SourcePublication.UNREADABLE,
                stored_points=None,
            ), f"{source.value} did not report an unreadable publication"
        spec = _admit(root, source=JobSource.CODE)

    assert spec.mode is JobMode.INCREMENTAL
    assert not spec.is_first_build
    assert [
        record.message
        for record in caplog.records
        if "publication state" in record.message
    ] == []


def test_an_unexpected_publication_failure_refuses_instead_of_raising(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Nothing a publication read can raise reaches the caller of admission.

    The run ledger converts every corruption it meets into its own typed
    failure, so no real file reaches the branch below - which is exactly why
    it exists, and why the read is intercepted to get there. One collaborator
    is replaced; the classification under test runs unchanged.

    Mutation proven by deleting the catch-all in
    ``_read_source_publication``: the error then leaves admission, and the
    one HTTP request behind it fails for every domain rather than refusing
    this one.
    """
    del isolated_registry
    import sqlite3

    from .. import _publication_state

    root = tmp_path / "unexpected-failure"
    root.mkdir()

    def raise_database_error(*_args: object, **_kwargs: object) -> object:
        raise sqlite3.DatabaseError("database disk image is malformed")

    # Admission resolves this name at call time, so replacing it here is
    # what the production read reaches.
    monkeypatch.setattr(
        _publication_state,
        "acquire_publication_snapshot",
        raise_database_error,
    )

    with caplog.at_level("WARNING", logger="vaultspec_rag.jobs"):
        reading = read_source_admission(root, PublicSourceType.CODE)
        escalated = _admit(root, source=JobSource.CODE).is_first_build

    assert reading == SourceAdmissionReading(
        publication=SourcePublication.UNREADABLE,
        stored_points=None,
    )
    assert not escalated
    # Unaccounted-for, so it is reported. The known unreadable publications
    # reach their own branch and log nothing.
    assert [
        record.message
        for record in caplog.records
        if "publication state" in record.message
    ]


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


def test_two_concurrent_first_build_admissions_collapse_to_one_job(
    tmp_path: Path,
    isolated_status_dir: Path,
    isolated_registry: ServiceRegistry,
) -> None:
    """One source cannot have two first builds admitted for it at once.

    Both callers read a never-built source and both ask for its first build,
    so without the manager's equivalence two jobs would each run the
    reset-first lifecycle over the same collections. The readings are taken
    on both threads before either creates, which is the ordering that makes
    the second admission's answer depend on equivalence rather than on
    having observed the first job's writes.

    Mutation proven by making ``_find_equivalent_active_locked`` return
    ``None``: two jobs are then created for the one source.
    """
    del isolated_registry, isolated_status_dir
    from .. import jobs

    root = tmp_path / "concurrent-first-build"
    root.mkdir()
    jobs.reset()
    ready = threading.Barrier(2)
    outcomes: list[tuple[str, bool]] = []
    failures: list[BaseException] = []
    lock = threading.Lock()

    def admit() -> None:
        try:
            spec = _admit(root, source=JobSource.CODE)
            assert spec.is_first_build
            ready.wait(timeout=10)
            _manager, job_id, created = admit_index_job(
                root,
                source=JobSource.CODE,
                clean=False,
                authority=RunAuthority.PUBLICATION,
                initiator_kind="cli",
            )
        except BaseException as exc:  # reported, never swallowed
            with lock:
                failures.append(exc)
            return
        with lock:
            outcomes.append((job_id, created))

    threads = [
        threading.Thread(target=admit, name=f"first-build-admission-{ordinal}")
        for ordinal in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    try:
        assert not [thread for thread in threads if thread.is_alive()]
        assert failures == []
        assert len({job_id for job_id, _created in outcomes}) == 1
        assert [created for _job_id, created in outcomes].count(True) == 1
        manager = jobs.get_job_manager()
        active = manager.active()
        assert len(active) == 1
        assert active[0].spec.is_first_build
    finally:
        jobs.reset()


def test_the_in_process_route_asks_the_same_admission(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
) -> None:
    """The public facade decides through the one owner, per source.

    The in-process route has no job to carry a mode, so what it asks is the
    decision itself. A root whose vault has published and whose code index
    has never been built answers differently for each, which is what makes
    selecting every domain safe.
    """
    root = tmp_path / "in-process-mixed"
    publish_empty_vault_proof(root)

    assert not admits_first_build(root, PublicSourceType.VAULT, initiator_kind="api")
    assert admits_first_build(root, PublicSourceType.CODE, initiator_kind="api")
    assert admits_first_build(root, PublicSourceType.DOCUMENT, initiator_kind="api")
    collection = _store_one_code_point(root, isolated_registry)
    assert _collection_points(root, isolated_registry, collection) == 1
    assert not admits_first_build(root, PublicSourceType.CODE, initiator_kind="api")


@pytest.mark.parametrize("initiator_kind", ["watcher", "integrity"])
def test_no_origin_outside_the_operator_ones_asks_for_a_build(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
    initiator_kind: str,
) -> None:
    """Automatic origins are refused the decision itself, not just the spec.

    Mutation proven by removing the origin test from ``admits_first_build``:
    both origins then report a first build to every caller of admission,
    including the in-process route.
    """
    del isolated_registry
    root = tmp_path / f"origin-{initiator_kind}"
    root.mkdir()

    assert not admits_first_build(
        root,
        PublicSourceType.CODE,
        initiator_kind=initiator_kind,
    )


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
