"""A search never returns content read across a reset of its source.

Every case runs against a real local store and a real run ledger under the
test's temporary root. A reset in progress is the exact durable state a
rebuild leaves between recording its intent and recording completion; a reset
that crosses a read is the production reset itself, run from inside the read.
Nothing here loads a model: the empty-collection path answers without one, so
a search that should have been refused and was not comes back as an empty
success the assertions reject.

MUTATION PROOF, each run in one uninterrupted sequence:

- Deleting the validation after the read in ``read_current_epoch`` failed
  ``test_a_read_that_spans_a_reset_returns_nothing`` on its ``pytest.raises``
  for every source; restoring it passed.
- Deleting the ``serving`` refusal in ``capture_source_read_fence`` failed
  ``test_a_source_mid_reset_refuses_before_reading`` on its ``pytest.raises``
  and ``test_each_public_search_refuses_a_source_mid_reset`` on its
  ``pytest.raises``; restoring it passed.
- Returning the outcome unchanged from ``_fenced_combined_outcome`` failed
  ``test_a_reset_crossing_a_combined_search_fences_that_domain`` on its
  ``error_kind`` assertion; restoring it passed.
- Dropping the unfinished-reset branch of ``storage_refusal_fact`` failed
  ``test_combined_search_refuses_only_the_domain_an_abandoned_reset_left``
  on its ``error_kind`` assertion; restoring it passed.
- Treating every unfinished reset as owned (``_reset_owner`` returning its
  first record regardless of generation) failed
  ``test_an_unfinished_reset_is_classified_by_the_job_that_owns_it`` on its
  ``abandoned`` assertion; dropping the ``PAUSED`` branch failed it on its
  ``paused`` assertion. Restoring each passed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import typer

from .._operator_commands import (
    IndexCommandOptions,
    index_command,
    server_job_resume_command,
    server_jobs_command,
)
from .._public_search import (
    CombinedSearchRequest,
    DocumentSearchRequest,
    search_combined_timed,
    search_documents_timed,
)
from .._publication_state import (
    IndexTransitionError,
    UnfinishedResetError,
    capture_source_read_fence,
    read_current_epoch,
)
from .._search_state import (
    AbsenceAuthority,
    SearchAvailability,
    SearchFreshness,
    SearchReasonCode,
    SearchSourceFact,
)
from .._source_types import CONCRETE_SOURCES, PublicSourceType
from .._store_writes import workspace_volume_path
from ..api import (
    CodebaseSearchRequest,
    VaultSearchRequest,
    search_codebase_timed,
    search_vault_timed,
)
from ..cli._search_in_process import InProcessSearchRequest, try_in_process_search
from ..indexer._rebuild_lifecycle import reset_selected_sources
from ..indexer._run_ledger_models import SourceResetPhase, index_run_ledger_path
from ..indexer._run_ledger_runtime import RunLedger
from ..job_models import JobMode, JobOperation, JobState
from ..registry import get_registry
from ..server._search_availability import storage_refusal_fact
from ..service import ServiceRegistry
from ..store_runtime import configured_backend_identity
from ._config_fixtures import reset_config
from .test_rebuild_lifecycle import _collection, _open, _points, _seed

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture(name="local_root")
def _local_root(tmp_path: Path) -> Generator[Path]:
    """A root on local storage with two-wide dense vectors and no sparse ones."""
    from ..config._settings import get_config

    get_config(
        {
            "local_only": True,
            "qdrant_url": None,
            "embedding_dimension": 2,
            "sparse_enabled": False,
        }
    )
    (tmp_path / ".vault").mkdir()
    try:
        yield tmp_path.resolve()
    finally:
        reset_config()


def record_reset_intent(root: Path, source: PublicSourceType) -> None:
    """Leave the durable state of a reset that recorded intent and no more."""
    ledger = RunLedger(index_run_ledger_path(workspace_volume_path(root)))
    state = ledger.begin_source_reset(
        source, str(root), configured_backend_identity(root), "rebuild-in-flight"
    )
    assert state.phase is SourceResetPhase.INTENT


def search_source(
    root: Path, source: PublicSourceType, registry: ServiceRegistry
) -> list[object]:
    """Run the production search facade of one concrete source."""
    if source is PublicSourceType.VAULT:
        vault, _ = search_vault_timed(
            VaultSearchRequest(root_dir=root, query="needle"), registry=registry
        )
        return list(vault)
    if source is PublicSourceType.CODE:
        code, _ = search_codebase_timed(
            CodebaseSearchRequest(root_dir=root, query="needle"), registry=registry
        )
        return list(code)
    document, _ = search_documents_timed(
        DocumentSearchRequest(root_dir=root, query="needle"), registry=registry
    )
    return list(document)


@pytest.mark.parametrize("source", CONCRETE_SOURCES)
def test_a_read_that_spans_a_reset_returns_nothing(
    local_root: Path, source: PublicSourceType
) -> None:
    """A read whose storage a reset discards mid-read is refused, not returned."""
    with _open(local_root) as store:
        store.ensure_table()
        store.ensure_code_table()
        store.ensure_document_table()
        collection = _collection(store, source)
        _seed(store, collection)

        def read_then_reset() -> int:
            observed = _points(store, collection)
            reset_selected_sources(store, source, generation_id="rebuild-1")
            return observed

        with pytest.raises(IndexTransitionError) as refused:
            read_current_epoch(local_root, source, read_then_reset)

        assert refused.value.source is source
        assert _points(store, collection) == 0


@pytest.mark.parametrize("source", CONCRETE_SOURCES)
def test_a_source_mid_reset_refuses_before_reading(
    local_root: Path, source: PublicSourceType
) -> None:
    """Storage being discarded is never read at all."""
    record_reset_intent(local_root, source)
    reads: list[PublicSourceType] = []

    with pytest.raises(IndexTransitionError):
        read_current_epoch(local_root, source, lambda: reads.append(source))

    assert reads == []


@pytest.mark.parametrize("source", CONCRETE_SOURCES)
def test_a_completed_reset_serves_what_its_rebuild_wrote_so_far(
    local_root: Path, source: PublicSourceType
) -> None:
    """Partial replacement content of the current epoch is answered.

    A rebuild that has written one batch has not published, and its content
    is still the only content of the epoch it writes under.
    """
    with _open(local_root) as store:
        store.ensure_table()
        store.ensure_code_table()
        store.ensure_document_table()
        collection = _collection(store, source)
        _seed(store, collection, point_id=1)
        reset_selected_sources(store, source, generation_id="rebuild-1")
        _seed(store, collection, point_id=2)

        served = read_current_epoch(
            local_root, source, lambda: _points(store, collection)
        )

    assert served == 1


@pytest.mark.parametrize("source", CONCRETE_SOURCES)
def test_each_public_search_refuses_a_source_mid_reset(
    local_root: Path, source: PublicSourceType
) -> None:
    """Every single-source facade refuses; its siblings keep answering."""
    record_reset_intent(local_root, source)
    registry = ServiceRegistry()

    with pytest.raises(IndexTransitionError) as refused:
        search_source(local_root, source, registry)

    assert refused.value.source is source
    for sibling in CONCRETE_SOURCES:
        if sibling is not source:
            assert search_source(local_root, sibling, registry) == []


def local_search_request(
    root: Path, source: PublicSourceType
) -> InProcessSearchRequest:
    """One JSON-mode local search of *source* with no filters."""
    return InProcessSearchRequest(
        target=root,
        query="needle",
        search_type=source,
        max_results=5,
        language=None,
        path=None,
        node_type=None,
        function_name=None,
        class_name=None,
        include_paths=None,
        exclude_paths=None,
        dedup_locales=None,
        prefer=None,
        doc_type=None,
        feature=None,
        date=None,
        tag=None,
        source_path=None,
        extractor_id=None,
        extractor_version=None,
        locator_kind=None,
        json_mode=True,
        envelope={},
    )


@pytest.mark.parametrize("source", CONCRETE_SOURCES)
def test_the_local_cli_search_reports_an_abandoned_reset_as_rebuild_required(
    local_root: Path, source: PublicSourceType, capsys: pytest.CaptureFixture[str]
) -> None:
    """A local search answers an ownerless reset the way the service does.

    No job anywhere owns the reset this root recorded, so nothing will finish
    it: the refusal is ``rebuild_required``, not retryable, names the rebuild
    command, and exits 1. It must not be reported as a GPU or runtime fault.

    Mutation: removing the ``IndexTransitionError`` branch of
    ``try_in_process_search`` sent the refusal to the GPU error handler, which
    writes prose rather than an envelope, and failed the ``stdout`` assertion
    for every source; restoring it passed.
    """
    record_reset_intent(local_root, source)

    try:
        with pytest.raises(typer.Exit) as exited:
            try_in_process_search(local_search_request(local_root, source))
    finally:
        get_registry().close_project(local_root)

    assert exited.value.exit_code == 1
    stdout = capsys.readouterr().out
    assert stdout.startswith("{"), f"expected one JSON envelope, got {stdout!r}"
    envelope = json.loads(stdout)
    assert envelope["ok"] is False
    assert envelope["command"] == "search"
    assert envelope["error"] == SearchReasonCode.REBUILD_REQUIRED.value
    assert envelope["retryable"] is False
    assert "rebuild generation rebuild-in-flight" in envelope["message"]
    assert envelope["index_state"]["source"] == source.value
    rebuild = index_command(
        source, IndexCommandOptions(rebuild=True, target=str(local_root))
    )
    assert f"`{rebuild}`" in envelope["remediation"]


def test_combined_search_refuses_only_the_domain_an_abandoned_reset_left(
    local_root: Path,
) -> None:
    """A combined search keeps every other domain and types the refused one."""
    record_reset_intent(local_root, PublicSourceType.CODE)

    outcome, _timings = search_combined_timed(
        CombinedSearchRequest(root_dir=local_root, query="needle"),
        registry=ServiceRegistry(),
    )

    assert outcome.code.error_kind == SearchReasonCode.REBUILD_REQUIRED.value
    assert outcome.code.results == ()
    fact = outcome.code.source_fact
    assert fact.reason_code is SearchReasonCode.REBUILD_REQUIRED
    assert fact.availability is SearchAvailability.UNAVAILABLE
    assert fact.absence_authority is AbsenceAuthority.NON_AUTHORITATIVE
    assert fact.retryable is False
    assert outcome.vault.ok
    assert outcome.document is not None
    assert outcome.document.ok


def _unfinished_reset(root: Path, source: PublicSourceType) -> UnfinishedResetError:
    """Record an unfinished reset and return the refusal a read of it raises."""
    record_reset_intent(root, source)
    with pytest.raises(UnfinishedResetError) as refused:
        capture_source_read_fence(root, source)
    return refused.value


def _index_job(
    root: Path,
    *,
    state: JobState,
    generation: str | None,
    job_id: str = "job-1",
) -> dict[str, object]:
    """One canonical job record as the job manager's snapshot renders it."""
    return {
        "id": job_id,
        "state": state.value,
        "spec": {
            "operation": JobOperation.INDEX.value,
            "source": PublicSourceType.CODE.value,
            "project_root": str(root),
            "mode": JobMode.REBUILD.value,
        },
        "rebuild_generation_id": generation,
    }


def test_an_unfinished_reset_is_classified_by_the_job_that_owns_it(
    local_root: Path,
) -> None:
    """Retryability and remediation follow the owning job's actual state.

    A running owner will finish the reset, so a retry succeeds. A paused owner
    will not until it is resumed. No live owner, including a job that ended,
    means nothing will finish it, so only a new rebuild helps.
    """
    refusal = _unfinished_reset(local_root, PublicSourceType.CODE)
    base = SearchSourceFact(
        source="code",
        availability=SearchAvailability.USABLE,
        freshness=SearchFreshness.UPDATING,
        absence_authority=AbsenceAuthority.NON_AUTHORITATIVE,
    )

    def classify(*jobs: dict[str, object]) -> SearchSourceFact:
        return storage_refusal_fact(refusal, base, root=local_root, job_snapshot=jobs)

    running = classify(
        _index_job(local_root, state=JobState.RUNNING, generation="rebuild-in-flight")
    )
    assert running.reason_code is SearchReasonCode.INDEX_TRANSITION
    assert running.retryable is True
    assert running.remediation == server_jobs_command(index="code")

    paused = classify(
        _index_job(local_root, state=JobState.PAUSED, generation="rebuild-in-flight")
    )
    assert paused.reason_code is SearchReasonCode.INDEX_TRANSITION
    assert paused.retryable is False, "paused"
    assert f"`{server_job_resume_command('job-1')}`" in str(paused.remediation)

    for ended in (
        (),
        (
            _index_job(
                local_root, state=JobState.FAILED, generation="rebuild-in-flight"
            ),
        ),
        (
            _index_job(
                local_root, state=JobState.CANCELLED, generation="rebuild-in-flight"
            ),
        ),
        (
            _index_job(local_root, state=JobState.RUNNING, generation="other-rebuild")
            | {
                "spec": {
                    "operation": "index",
                    "source": "vault",
                    "project_root": str(local_root),
                    "mode": "rebuild",
                }
            },
        ),
    ):
        abandoned = classify(*ended)
        assert abandoned.reason_code is SearchReasonCode.REBUILD_REQUIRED, "abandoned"
        assert abandoned.freshness is SearchFreshness.REBUILD_REQUIRED
        assert abandoned.retryable is False
        assert "rebuild-in-flight" in str(abandoned.remediation)
        assert "--rebuild --type code" in str(abandoned.remediation)

    replacing = classify(
        _index_job(local_root, state=JobState.QUEUED, generation=None, job_id="job-2")
    )
    assert replacing.reason_code is SearchReasonCode.INDEX_TRANSITION
    assert replacing.retryable is True


def test_the_service_answers_an_abandoned_reset_with_409_and_a_live_one_with_503(
    local_root: Path,
) -> None:
    """The route's status follows the classified retryability."""
    from ..server._search_route_availability import (
        SearchAvailabilityRequestFacts,
        typed_storage_refusal,
    )

    refusal = _unfinished_reset(local_root, PublicSourceType.CODE)
    facts = SearchAvailabilityRequestFacts(
        job_snapshot_before=[],
        root=local_root,
        source="code",
        request_id="request-1",
        port=None,
    )

    abandoned, abandoned_class = typed_storage_refusal(refusal, facts, [])
    live, live_class = typed_storage_refusal(
        refusal,
        facts,
        [
            _index_job(
                local_root, state=JobState.RUNNING, generation="rebuild-in-flight"
            )
        ],
    )

    assert abandoned_class.status_code == 409
    assert abandoned["error"] == SearchReasonCode.REBUILD_REQUIRED.value
    assert abandoned_class.response["index_state"] == {
        "source": "code",
        "requested_target_root": str(local_root),
        "status": "unavailable",
    }
    assert live_class.status_code == 503
    assert live["error"] == SearchReasonCode.INDEX_TRANSITION.value
    assert live["retryable"] is True
    assert live_class.response["index_state"] == {
        "source": "code",
        "requested_target_root": str(local_root),
        "status": "rebuilding",
    }


def test_a_reset_crossing_a_combined_search_fences_that_domain(
    local_root: Path,
) -> None:
    """A reset recorded after a combined count is caught before the answer.

    The count of every domain is taken under the epoch captured before it;
    a reset recorded afterwards leaves the count and any search behind it
    unreturnable for that domain.
    """
    from .. import _public_search

    registry = ServiceRegistry()
    counts, failures, facts, _timings, fences = _public_search._count_combined_domains(
        local_root, registry, include_documents=True
    )
    assert not failures
    record_reset_intent(local_root, PublicSourceType.VAULT)

    empty = _public_search._empty_or_failed_combined_outcome(failures, facts, 5)
    fenced = _public_search._fenced_combined_outcome(empty, fences, local_root)

    assert counts[PublicSourceType.VAULT] == 0
    assert fenced.vault.error_kind == SearchReasonCode.INDEX_TRANSITION.value
    assert fenced.code.ok


def _document_fact(root: Path, registry: ServiceRegistry) -> SearchSourceFact:
    outcome, _timings = search_combined_timed(
        CombinedSearchRequest(root_dir=root, query="needle"), registry=registry
    )
    assert outcome.document is not None
    assert outcome.document.ok
    assert outcome.document.results == ()
    return outcome.document.source_fact


def _published_document_generation(root: Path) -> str:
    from .._publication_state import acquire_publication_snapshot

    return acquire_publication_snapshot(
        root, PublicSourceType.DOCUMENT
    ).proof.generation_id


async def test_an_empty_corpus_is_authoritative_only_once_its_rebuild_finalizes(
    local_root: Path,
) -> None:
    """Absence is proven by a finished build, never by one still running.

    The corpus is genuinely empty throughout, so the reset leaves exactly what
    the completed rebuild will certify. Only the certification differs.

    Mutation: dropping the ``integrity_verified`` requirement from
    ``_target_is_current`` let the readiness registry's cached claim on the
    discarded publication certify the rebuilding source, and failed the
    middle assertion with ``authoritative``; restoring it passed.
    """
    import asyncio

    from ._hook_publication import publish_empty_document_proof

    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    readiness = registry.readiness_registry
    publish_empty_document_proof(local_root)
    readiness.publish_next(
        local_root,
        "document",
        generation=_published_document_generation(local_root),
    )

    assert (
        _document_fact(local_root, registry).absence_authority
        is AbsenceAuthority.AUTHORITATIVE
    )

    with _open(local_root) as store:
        reset_selected_sources(
            store, PublicSourceType.DOCUMENT, generation_id="rebuild-2"
        )

    rebuilding = _document_fact(local_root, registry)
    assert rebuilding.absence_authority is AbsenceAuthority.NON_AUTHORITATIVE
    assert rebuilding.availability is SearchAvailability.USABLE

    publish_empty_document_proof(local_root)
    readiness.publish_next(
        local_root,
        "document",
        generation=_published_document_generation(local_root),
    )

    assert (
        _document_fact(local_root, registry).absence_authority
        is AbsenceAuthority.AUTHORITATIVE
    )


async def test_a_reset_retires_the_readiness_claim_on_the_discarded_generation(
    local_root: Path,
) -> None:
    """Readiness never names a generation a reset discarded as served.

    The claim is retired at the reset and replaced only by the rebuild's own
    publication; the revision stays so bounded waits keep their ordering.

    Mutation: making ``_current_locked`` return the cached snapshot unchanged
    kept the discarded generation served and failed the ``retired`` assertion;
    restoring the epoch comparison passed.
    """
    import asyncio

    from ._hook_publication import publish_empty_document_proof

    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    readiness = registry.readiness_registry
    publish_empty_document_proof(local_root)
    discarded = _published_document_generation(local_root)
    readiness.publish_next(local_root, "document", generation=discarded)
    assert readiness.snapshot(local_root, "document").published_generation == (
        discarded
    )

    with _open(local_root) as store:
        reset_selected_sources(
            store, PublicSourceType.DOCUMENT, generation_id="rebuild-2"
        )

    retired = readiness.snapshot(local_root, "document")
    assert retired.published_generation is None, "retired"
    assert retired.publication_revision == 1
    assert _document_fact(local_root, registry).generation.served_generation is None

    publish_empty_document_proof(local_root)
    rebuilt = _published_document_generation(local_root)
    readiness.publish_next(local_root, "document", generation=rebuilt)
    assert readiness.snapshot(local_root, "document").published_generation == rebuilt
    assert _document_fact(local_root, registry).generation.served_generation == rebuilt


async def test_a_publication_proven_before_a_reset_is_never_served_after_it(
    local_root: Path,
) -> None:
    """A proof read before a reset cannot be stamped with the reset's epoch.

    The service captures the epoch before it reads the proof it publishes; a
    reset landing between the two leaves the claim on the earlier epoch, so
    the next read retires it.

    Mutation: ignoring ``reset_epoch`` in ``publish_next`` and reading the
    epoch afresh stamped the discarded generation with the new epoch and
    failed the ``published_generation is None`` assertion; restoring the
    parameter passed.
    """
    import asyncio

    from ..server._search_readiness import current_reset_fence
    from ._hook_publication import publish_empty_document_proof

    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    readiness = registry.readiness_registry
    publish_empty_document_proof(local_root)
    fence = current_reset_fence(local_root, "document")
    assert fence is not None
    before = fence.epoch
    proven = _published_document_generation(local_root)
    with _open(local_root) as store:
        reset_selected_sources(
            store, PublicSourceType.DOCUMENT, generation_id="rebuild-2"
        )

    readiness.publish_next(
        local_root, "document", generation=proven, reset_epoch=before
    )

    assert before == 0
    assert readiness.snapshot(local_root, "document").published_generation is None


async def test_the_generation_a_rebuild_serves_is_reported_apart_from_publication(
    local_root: Path,
) -> None:
    """Search names the generation storage holds while a rebuild ingests.

    After the reset nothing is published, so ``served_generation`` is absent;
    ``observed_generation`` names the rebuild whose replacement search
    addresses. Mid-reset storage holds no generation, so neither is named.
    Once the rebuild publishes, the two agree.

    Mutation: returning ``current`` unchanged from ``_observed`` left
    ``observed_generation`` absent and failed the ``serving rebuild``
    assertion. Dropping the ``serving`` condition named the generation of a
    reset still discarding and failed the mid-reset assertion. Restoring each
    passed.
    """
    import asyncio

    from ._hook_publication import publish_empty_document_proof

    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    readiness = registry.readiness_registry
    publish_empty_document_proof(local_root)
    discarded = _published_document_generation(local_root)
    readiness.publish_next(local_root, "document", generation=discarded)
    before = _document_fact(local_root, registry).generation
    assert before.observed_generation == discarded
    assert before.served_generation == discarded

    with _open(local_root) as store:
        reset_selected_sources(
            store, PublicSourceType.DOCUMENT, generation_id="rebuild-2"
        )

    during = _document_fact(local_root, registry).generation
    assert during.served_generation is None
    assert during.observed_generation == "rebuild-2", "serving rebuild"
    assert during.as_dict().get("observed_generation") == "rebuild-2"

    record_reset_intent(local_root, PublicSourceType.DOCUMENT)
    mid_reset = readiness.snapshot(local_root, "document")
    assert mid_reset.published_generation is None
    assert mid_reset.observed_generation is None

    with _open(local_root) as store:
        reset_selected_sources(
            store, PublicSourceType.DOCUMENT, generation_id="rebuild-in-flight"
        )
    publish_empty_document_proof(local_root)
    rebuilt = _published_document_generation(local_root)
    readiness.publish_next(local_root, "document", generation=rebuilt)
    after = _document_fact(local_root, registry).generation
    assert after.served_generation == rebuilt
    assert after.observed_generation == rebuilt
