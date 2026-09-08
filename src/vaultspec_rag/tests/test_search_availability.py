"""CPU-only contract tests for canonical search-availability evidence."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING, Literal, cast

import pytest
from httpx import Headers
from qdrant_client.http.exceptions import UnexpectedResponse

from .._search_state import (
    MAX_SEARCH_EVIDENCE_ITEMS,
    AbsenceAuthority,
    FreshnessWaitPolicy,
    GenerationEvidence,
    SearchAvailability,
    SearchFreshness,
    SearchReadinessAggregate,
    SearchSourceFact,
    SearchWaitCause,
    WaitObservation,
)
from ..job_manager.manager import JobManager
from ..job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobSnapshot,
    JobSource,
    JobSpec,
    JobState,
)
from ..server._search_availability import (
    CanonicalSearchEvidence,
    SearchAvailabilityContext,
    SearchResponseClassification,
    classify_qdrant_collection_disappearance,
    classify_search_response,
)
from ..service_quiesce import ServiceQuiesceController

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

pytestmark = [pytest.mark.unit]

type SearchSource = Literal["vault", "code"]


def _current_source_fact() -> SearchSourceFact:
    return SearchSourceFact(
        source="vault",
        availability=SearchAvailability.USABLE,
        freshness=SearchFreshness.CURRENT,
        absence_authority=AbsenceAuthority.AUTHORITATIVE,
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda fact: replace(
                fact,
                availability=cast("SearchAvailability", "unknown"),
            ),
            "availability must be a SearchAvailability",
        ),
        (
            lambda fact: replace(
                fact,
                freshness=cast("SearchFreshness", "unknown"),
            ),
            "freshness must be a SearchFreshness",
        ),
        (
            lambda fact: replace(
                fact,
                absence_authority=cast("AbsenceAuthority", "unknown"),
            ),
            "absence_authority must be a AbsenceAuthority",
        ),
        (
            lambda fact: replace(
                fact,
                wait_policy=cast("FreshnessWaitPolicy", "unknown"),
            ),
            "wait_policy must be a FreshnessWaitPolicy",
        ),
    ],
)
def test_source_fact_rejects_unknown_closed_vocabulary(
    mutation: Callable[[SearchSourceFact], SearchSourceFact],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        mutation(_current_source_fact())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda fact: replace(
            fact,
            availability=SearchAvailability.UNAVAILABLE,
        ),
        lambda fact: replace(
            fact,
            freshness=SearchFreshness.UPDATING,
        ),
    ],
)
def test_source_fact_rejects_authoritative_contradictions(
    mutation: Callable[[SearchSourceFact], SearchSourceFact],
) -> None:
    # Proven red by temporarily inverting the production authority predicate to
    # NON_AUTHORITATIVE: both cases fail here with DID NOT RAISE before restoration.
    with pytest.raises(
        ValueError,
        match="authoritative absence requires a usable, current source",
    ):
        mutation(_current_source_fact())


def test_wait_observation_rejects_unknown_cause() -> None:
    with pytest.raises(ValueError, match="cause must be a SearchWaitCause"):
        WaitObservation(
            cause=cast("SearchWaitCause", "unknown"),
            waited_seconds=0,
            configured_bound_seconds=1,
            remaining_bound_seconds=1,
        )


def _wait_with_invalid_duration(field: str, value: object) -> WaitObservation:
    if field == "waited_seconds":
        return WaitObservation(
            cause=SearchWaitCause.INDEX_TRANSITION,
            waited_seconds=cast("float", value),
            configured_bound_seconds=1,
            remaining_bound_seconds=0,
        )
    if field == "configured_bound_seconds":
        return WaitObservation(
            cause=SearchWaitCause.INDEX_TRANSITION,
            waited_seconds=0,
            configured_bound_seconds=cast("float", value),
            remaining_bound_seconds=0,
        )
    return WaitObservation(
        cause=SearchWaitCause.INDEX_TRANSITION,
        waited_seconds=0,
        configured_bound_seconds=1,
        remaining_bound_seconds=cast("float", value),
    )


@pytest.mark.parametrize(
    ("field", "duration"),
    [
        (field, duration)
        for field in (
            "waited_seconds",
            "configured_bound_seconds",
            "remaining_bound_seconds",
        )
        for duration in (-1, float("inf"), float("nan"), True, "1")
    ],
)
def test_wait_observation_rejects_invalid_durations(
    field: str,
    duration: object,
) -> None:
    with pytest.raises(
        ValueError,
        match=f"{field} must be a finite non-negative number",
    ):
        _wait_with_invalid_duration(field, duration)


def test_wait_observation_rejects_remaining_above_bound() -> None:
    with pytest.raises(
        ValueError,
        match="remaining_bound_seconds cannot exceed the configured bound",
    ):
        WaitObservation(
            cause=SearchWaitCause.INDEX_TRANSITION,
            waited_seconds=0,
            configured_bound_seconds=1,
            remaining_bound_seconds=2,
        )


def test_wait_observation_rejects_total_above_bound() -> None:
    with pytest.raises(
        ValueError,
        match="waited and remaining time cannot exceed the configured bound",
    ):
        WaitObservation(
            cause=SearchWaitCause.INDEX_TRANSITION,
            waited_seconds=0.6,
            configured_bound_seconds=1,
            remaining_bound_seconds=0.5,
        )


def test_source_fact_rejects_unbounded_evidence() -> None:
    observation = WaitObservation(
        cause=SearchWaitCause.SEARCH_ADMISSION,
        waited_seconds=0,
        configured_bound_seconds=1,
        remaining_bound_seconds=1,
    )
    with pytest.raises(ValueError, match="wait observations exceed"):
        replace(
            _current_source_fact(),
            absence_authority=AbsenceAuthority.NON_AUTHORITATIVE,
            waits=(observation,) * (MAX_SEARCH_EVIDENCE_ITEMS + 1),
        )
    with pytest.raises(ValueError, match="source evidence exceeds"):
        replace(
            _current_source_fact(),
            evidence=("job",) * (MAX_SEARCH_EVIDENCE_ITEMS + 1),
        )


def test_source_fact_rejects_malformed_generation_evidence() -> None:
    with pytest.raises(ValueError, match="generation must be GenerationEvidence"):
        replace(
            _current_source_fact(),
            generation=cast("GenerationEvidence", object()),
        )


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (
            lambda: GenerationEvidence(served_generation=""),
            "served_generation must contain 1 to 256 characters",
        ),
        (
            lambda: GenerationEvidence(observed_generation="x" * 257),
            "observed_generation must contain 1 to 256 characters",
        ),
        (
            lambda: GenerationEvidence(desired_generation=cast("str", 7)),
            "desired_generation must contain 1 to 256 characters",
        ),
        (
            lambda: GenerationEvidence(served_revision=-1),
            "served_revision must be a non-negative integer",
        ),
        (
            lambda: GenerationEvidence(observed_revision=cast("int", True)),
            "observed_revision must be a non-negative integer",
        ),
        (
            lambda: GenerationEvidence(desired_revision=cast("int", 1.5)),
            "desired_revision must be a non-negative integer",
        ),
    ],
)
def test_generation_evidence_rejects_malformed_identity(
    build: Callable[[], GenerationEvidence],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build()


def test_source_fact_rejects_non_boolean_retryability() -> None:
    with pytest.raises(ValueError, match="retryable must be a boolean"):
        replace(_current_source_fact(), retryable=cast("bool", 1))


@pytest.mark.parametrize(
    "aggregate",
    [
        SearchReadinessAggregate(
            availability=SearchAvailability.USABLE,
            freshness=SearchFreshness.CURRENT,
            absence_authority=AbsenceAuthority.NON_AUTHORITATIVE,
            source_count=2,
            usable_source_count=1,
            degraded_sources=("code",),
        ),
    ],
)
def test_valid_non_authoritative_aggregate_is_accepted(
    aggregate: SearchReadinessAggregate,
) -> None:
    assert aggregate.usable_source_count == 1


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (
            lambda: SearchReadinessAggregate(
                availability=SearchAvailability.UNAVAILABLE,
                freshness=SearchFreshness.CURRENT,
                absence_authority=AbsenceAuthority.AUTHORITATIVE,
                source_count=1,
                usable_source_count=0,
                degraded_sources=("vault",),
            ),
            "authoritative aggregate requires every source to be usable and current",
        ),
        (
            lambda: SearchReadinessAggregate(
                availability=SearchAvailability.USABLE,
                freshness=SearchFreshness.UPDATING,
                absence_authority=AbsenceAuthority.AUTHORITATIVE,
                source_count=1,
                usable_source_count=1,
                degraded_sources=("vault",),
            ),
            "authoritative aggregate requires every source to be usable and current",
        ),
        (
            lambda: SearchReadinessAggregate(
                availability=SearchAvailability.USABLE,
                freshness=SearchFreshness.CURRENT,
                absence_authority=AbsenceAuthority.NON_AUTHORITATIVE,
                source_count=2,
                usable_source_count=1,
                degraded_sources=(),
            ),
            "degraded_sources contradict the aggregate source counts",
        ),
        (
            lambda: SearchReadinessAggregate(
                availability=SearchAvailability.USABLE,
                freshness=SearchFreshness.CURRENT,
                absence_authority=AbsenceAuthority.NON_AUTHORITATIVE,
                source_count=1,
                usable_source_count=0,
                degraded_sources=("vault",),
            ),
            "usable aggregate requires at least one usable source",
        ),
        (
            lambda: SearchReadinessAggregate(
                availability=SearchAvailability.UNAVAILABLE,
                freshness=SearchFreshness.CURRENT,
                absence_authority=AbsenceAuthority.NON_AUTHORITATIVE,
                source_count=2,
                usable_source_count=1,
                degraded_sources=("vault",),
            ),
            "non-usable aggregate cannot report usable sources",
        ),
        (
            lambda: SearchReadinessAggregate(
                availability=SearchAvailability.USABLE,
                freshness=SearchFreshness.CURRENT,
                absence_authority=AbsenceAuthority.NON_AUTHORITATIVE,
                source_count=2,
                usable_source_count=2,
                degraded_sources=("vault",),
            ),
            "current aggregate cannot contain freshness degradation",
        ),
        (
            lambda: SearchReadinessAggregate(
                availability=SearchAvailability.USABLE,
                freshness=SearchFreshness.UPDATING,
                absence_authority=AbsenceAuthority.NON_AUTHORITATIVE,
                source_count=1,
                usable_source_count=1,
                degraded_sources=(),
            ),
            "non-current aggregate requires a degraded source",
        ),
    ],
)
def test_aggregate_rejects_contradictory_authority_freshness_and_counts(
    build: Callable[[], SearchReadinessAggregate],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build()


def _canonical_snapshot(
    root: Path,
    *,
    job_id: str,
    source: JobSource = JobSource.VAULT,
    mode: JobMode = JobMode.INCREMENTAL,
    state: JobState = JobState.RUNNING,
) -> JobSnapshot:
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=1,
        state_path=None,
    )
    outcome = manager.create(
        JobSpec(JobOperation.INDEX, source, str(root), mode),
        JobInitiator("test", "search availability", str(root)),
        job_id=job_id,
    )
    assert outcome.job is not None
    return replace(outcome.job, state=state)


def _readiness_classification(
    root: Path,
    *,
    evidence: CanonicalSearchEvidence | None = None,
    snapshots: Sequence[object] = (),
    results: list[object] | None = None,
) -> SearchResponseClassification:
    resolved_root = root.resolve()
    return classify_search_response(
        {"request_id": "readiness-request", "results": results or []},
        SearchAvailabilityContext(
            before_snapshot=(),
            after_snapshot=snapshots,
            requested_root=resolved_root,
            source="vault",
            request_id="readiness-request",
            index_state={
                "source": "vault",
                "indexed_count": 1,
                "indexed_target_root": str(resolved_root),
                "requested_target_root": str(resolved_root),
                "target_matches": True,
            },
            port=8766,
            canonical_evidence=evidence or CanonicalSearchEvidence(),
        ),
    )


def test_projection_requires_explicit_complete_proof_for_current_authority(
    tmp_path: Path,
) -> None:
    classification = _readiness_classification(
        tmp_path,
        evidence=CanonicalSearchEvidence(
            served_generation="generation-2",
            desired_generation="generation-2",
            publication_revision=4,
            desired_revision=4,
            collection_present=True,
            target_matches=True,
            integrity_verified=True,
        ),
    )

    assert classification.source_fact.availability is SearchAvailability.USABLE
    assert classification.source_fact.freshness is SearchFreshness.CURRENT
    assert (
        classification.source_fact.absence_authority is AbsenceAuthority.AUTHORITATIVE
    )
    assert classification.status_code == 200


@pytest.mark.parametrize(
    "evidence",
    [
        CanonicalSearchEvidence(
            served_generation="generation-2",
            desired_generation="generation-2",
            target_matches=True,
            integrity_verified=True,
        ),
        CanonicalSearchEvidence(
            served_generation="generation-2",
            desired_generation="generation-2",
            collection_present=True,
            integrity_verified=True,
        ),
        CanonicalSearchEvidence(
            served_generation="generation-2",
            desired_generation="generation-2",
            collection_present=True,
            target_matches=True,
        ),
        CanonicalSearchEvidence(
            served_generation="generation-2",
            collection_present=True,
            target_matches=True,
            integrity_verified=True,
        ),
        CanonicalSearchEvidence(
            desired_generation="generation-2",
            collection_present=True,
            target_matches=True,
            integrity_verified=True,
        ),
    ],
)
def test_projection_never_infers_current_from_partial_proof(
    tmp_path: Path,
    evidence: CanonicalSearchEvidence,
) -> None:
    classification = _readiness_classification(tmp_path, evidence=evidence)

    assert classification.source_fact.freshness is SearchFreshness.UNVERIFIABLE
    assert (
        classification.source_fact.absence_authority
        is AbsenceAuthority.NON_AUTHORITATIVE
    )


@pytest.mark.parametrize("publication_revision", [4, 5])
def test_projection_accepts_satisfied_revision_only_current_proof(
    tmp_path: Path,
    publication_revision: int,
) -> None:
    classification = _readiness_classification(
        tmp_path,
        evidence=CanonicalSearchEvidence(
            publication_revision=publication_revision,
            desired_revision=4,
            collection_present=True,
            target_matches=True,
            integrity_verified=True,
        ),
    )

    assert classification.source_fact.freshness is SearchFreshness.CURRENT
    assert (
        classification.source_fact.absence_authority is AbsenceAuthority.AUTHORITATIVE
    )


@pytest.mark.parametrize("publication_revision", [3, None])
def test_projection_rejects_unsatisfied_revision_only_current_proof(
    tmp_path: Path,
    publication_revision: int | None,
) -> None:
    classification = _readiness_classification(
        tmp_path,
        evidence=CanonicalSearchEvidence(
            publication_revision=publication_revision,
            desired_revision=4,
            collection_present=True,
            target_matches=True,
            integrity_verified=True,
        ),
    )

    assert classification.source_fact.freshness is SearchFreshness.UNVERIFIABLE
    assert (
        classification.source_fact.absence_authority
        is AbsenceAuthority.NON_AUTHORITATIVE
    )


def test_projection_rejects_mismatched_generation_current_proof(
    tmp_path: Path,
) -> None:
    classification = _readiness_classification(
        tmp_path,
        evidence=CanonicalSearchEvidence(
            served_generation="generation-1",
            desired_generation="generation-2",
            collection_present=True,
            target_matches=True,
            integrity_verified=True,
        ),
    )

    assert classification.source_fact.freshness is SearchFreshness.UNVERIFIABLE
    assert (
        classification.source_fact.absence_authority
        is AbsenceAuthority.NON_AUTHORITATIVE
    )


def test_projection_keeps_a_prior_complete_generation_usable_while_updating(
    tmp_path: Path,
) -> None:
    snapshot = _canonical_snapshot(tmp_path, job_id="updating")
    classification = _readiness_classification(
        tmp_path,
        evidence=CanonicalSearchEvidence(
            served_generation="generation-1",
            desired_generation="generation-2",
            collection_present=True,
        ),
        snapshots=(snapshot.to_dict(),),
        results=[{"id": "kept"}],
    )

    assert classification.source_fact.availability is SearchAvailability.USABLE
    assert classification.source_fact.freshness is SearchFreshness.UPDATING
    assert (
        classification.source_fact.absence_authority
        is AbsenceAuthority.NON_AUTHORITATIVE
    )
    assert classification.status_code == 200


def test_projection_marks_observed_collection_usable_without_a_served_generation(
    tmp_path: Path,
) -> None:
    snapshot = _canonical_snapshot(tmp_path, job_id="first-publication")
    classification = _readiness_classification(
        tmp_path,
        evidence=CanonicalSearchEvidence(collection_present=True),
        snapshots=(snapshot.to_dict(),),
    )

    assert classification.source_fact.availability is SearchAvailability.USABLE
    assert classification.source_fact.freshness is SearchFreshness.UPDATING
    assert classification.source_fact.reason_code == "index_updating"
    assert classification.status_code == 503


def test_projection_keeps_absent_optional_evidence_unknown(tmp_path: Path) -> None:
    classification = _readiness_classification(tmp_path)

    assert classification.source_fact.availability is SearchAvailability.UNAVAILABLE
    assert classification.source_fact.freshness is SearchFreshness.UNVERIFIABLE
    assert (
        classification.source_fact.absence_authority
        is AbsenceAuthority.NON_AUTHORITATIVE
    )
    assert classification.source_fact.generation.as_dict() == {}
    assert classification.source_fact.reason_code == "index_unverifiable"


def test_projection_uses_only_explicit_rebuild_required_evidence(
    tmp_path: Path,
) -> None:
    classification = _readiness_classification(
        tmp_path,
        evidence=CanonicalSearchEvidence(rebuild_required=True),
    )

    assert classification.source_fact.availability is SearchAvailability.UNAVAILABLE
    assert classification.source_fact.freshness is SearchFreshness.REBUILD_REQUIRED
    assert classification.source_fact.reason_code == "rebuild_required"
    assert classification.source_fact.retryable is False


def test_projection_never_infers_rebuild_required_from_job_mode(tmp_path: Path) -> None:
    snapshot = _canonical_snapshot(
        tmp_path,
        job_id="rebuild-job",
        mode=JobMode.REBUILD,
    )
    classification = _readiness_classification(
        tmp_path,
        snapshots=(snapshot.to_dict(),),
    )

    assert classification.rebuilding is True
    assert classification.source_fact.freshness is SearchFreshness.UPDATING
    assert classification.source_fact.reason_code == "index_updating"


def test_projection_uses_only_explicit_capacity_refusal(tmp_path: Path) -> None:
    refused = _readiness_classification(
        tmp_path,
        evidence=CanonicalSearchEvidence(capacity_refused=True),
    )
    unknown = _readiness_classification(tmp_path)

    assert refused.source_fact.availability is SearchAvailability.CAPACITY_LIMITED
    assert refused.source_fact.reason_code == "capacity_limited"
    assert refused.source_fact.retryable is True
    assert unknown.source_fact.availability is SearchAvailability.UNAVAILABLE


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        (
            lambda: CanonicalSearchEvidence(capacity_refused=cast("bool", 1)),
            "capacity_refused must be a boolean",
        ),
        (
            lambda: CanonicalSearchEvidence(rebuild_required=cast("bool", 1)),
            "rebuild_required must be a boolean",
        ),
    ],
)
def test_canonical_evidence_requires_strict_refusal_flags(
    evidence: Callable[[], CanonicalSearchEvidence],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        evidence()


def test_canonical_evidence_rejects_conflicting_refusals() -> None:
    with pytest.raises(
        ValueError,
        match="capacity_refused and rebuild_required are mutually exclusive",
    ):
        CanonicalSearchEvidence(capacity_refused=True, rebuild_required=True)


def test_empty_authority_follows_the_canonical_source_fact(tmp_path: Path) -> None:
    authoritative = _readiness_classification(
        tmp_path,
        evidence=CanonicalSearchEvidence(
            served_generation="generation-1",
            desired_generation="generation-1",
            collection_present=True,
            target_matches=True,
            integrity_verified=True,
        ),
    )
    snapshot = _canonical_snapshot(tmp_path, job_id="empty-updating")
    non_authoritative = _readiness_classification(
        tmp_path,
        evidence=CanonicalSearchEvidence(
            served_generation="generation-1",
            desired_generation="generation-2",
            collection_present=True,
        ),
        snapshots=(snapshot.to_dict(),),
    )

    assert authoritative.source_fact.absence_authority is AbsenceAuthority.AUTHORITATIVE
    assert authoritative.status_code == 200
    assert (
        non_authoritative.source_fact.absence_authority
        is AbsenceAuthority.NON_AUTHORITATIVE
    )
    assert non_authoritative.status_code == 503


def test_projection_and_legacy_job_evidence_share_one_bound(tmp_path: Path) -> None:
    # Proven red by slicing matching jobs at MAX_SEARCH_EVIDENCE_ITEMS - 1:
    # the exact shared-bound assertion below fails as 7 == 8 before restoration.
    snapshots = tuple(
        _canonical_snapshot(tmp_path, job_id=f"bounded-{index}").to_dict()
        for index in range(MAX_SEARCH_EVIDENCE_ITEMS + 1)
    )
    classification = _readiness_classification(tmp_path, snapshots=snapshots)

    assert len(classification.source_fact.evidence) == MAX_SEARCH_EVIDENCE_ITEMS
    assert len(classification.matching_jobs) == MAX_SEARCH_EVIDENCE_ITEMS
    assert classification.matching_jobs_truncated is True


def _availability_response(
    root: Path,
    *,
    before: Sequence[object] = (),
    after: Sequence[object] = (),
    source: SearchSource = "vault",
) -> dict[str, object] | None:
    resolved_root = root.resolve()
    result: dict[str, object] = {
        "request_id": "request-1",
        "results": [],
    }
    classification = classify_search_response(
        result,
        SearchAvailabilityContext(
            before_snapshot=before,
            after_snapshot=after,
            requested_root=resolved_root,
            source=source,
            request_id="request-1",
            index_state={
                "source": source,
                "indexed_count": 7,
                "indexed_target_root": str(resolved_root),
                "requested_target_root": str(resolved_root),
                "target_matches": True,
            },
            port=8766,
        ),
    )
    return classification.response if classification.status_code == 503 else None


@pytest.mark.parametrize(
    ("state", "matches"),
    [
        (JobState.QUEUED, True),
        (JobState.RUNNING, True),
        (JobState.PAUSING, True),
        (JobState.PAUSED, True),
        (JobState.CANCELLING, True),
        (JobState.CANCELLED, False),
        (JobState.SUCCEEDED, False),
        (JobState.FAILED, False),
        (JobState.INTERRUPTED, False),
    ],
)
def test_only_canonical_nonterminal_states_make_empty_results_unavailable(
    tmp_path: Path,
    state: JobState,
    *,
    matches: bool,
) -> None:
    root = (tmp_path / "project").resolve()
    snapshot = _canonical_snapshot(root, job_id=f"job-{state.value}", state=state)

    response = _availability_response(root, after=[snapshot.to_dict()])

    assert (response is not None) is matches


def test_legacy_and_invalid_canonical_identity_are_rejected(tmp_path: Path) -> None:
    # Proven red independently by accepting every non-null normalized root and
    # by removing exact source equality: the wrong-root and wrong-source records
    # each fail the exact `is None` rejection assertion before restoration.
    root = (tmp_path / "project").resolve()
    other_root = (tmp_path / "other-project").resolve()
    snapshot = _canonical_snapshot(root, job_id="canonical")
    legacy_record: dict[str, object] = {
        "id": "legacy",
        "source": "vault",
        "phase": "running",
        "initiator": {"project_root": str(root)},
    }
    wrong_operation = replace(
        snapshot,
        spec=replace(snapshot.spec, operation=JobOperation.MAINTENANCE),
    ).to_dict()
    wrong_source = replace(
        snapshot,
        spec=replace(snapshot.spec, source=JobSource.CODE),
    ).to_dict()
    wrong_root = replace(
        snapshot,
        spec=replace(snapshot.spec, project_root=str(other_root)),
    ).to_dict()
    invalid_mode = replace(
        snapshot,
        spec=replace(snapshot.spec, mode=None),
    ).to_dict()

    for record in (
        legacy_record,
        wrong_operation,
        wrong_source,
        wrong_root,
        invalid_mode,
    ):
        assert _availability_response(root, after=[record]) is None


def test_canonical_root_alias_matches_the_resolved_request_root(tmp_path: Path) -> None:
    root = (tmp_path / "project").resolve()
    alias = root / "uncreated" / ".."
    snapshot = _canonical_snapshot(alias, job_id="root-alias")

    response = _availability_response(root, after=[snapshot.to_dict()])

    assert response is not None
    index_state = cast("dict[str, object]", response["index_state"])
    assert index_state["matching_jobs"] == [
        {"id": "root-alias", "state": "running", "mode": "incremental"}
    ]


def test_second_observation_wins_when_job_ids_overlap(tmp_path: Path) -> None:
    root = (tmp_path / "project").resolve()
    before = _canonical_snapshot(
        root,
        job_id="same-job",
        mode=JobMode.REBUILD,
        state=JobState.RUNNING,
    )
    after = _canonical_snapshot(
        root,
        job_id="same-job",
        mode=JobMode.INCREMENTAL,
        state=JobState.PAUSING,
    )

    response = _availability_response(
        root,
        before=[before.to_dict()],
        after=[after.to_dict()],
    )

    assert response is not None
    index_state = cast("dict[str, object]", response["index_state"])
    assert index_state["matching_jobs"] == [
        {"id": "same-job", "state": "pausing", "mode": "incremental"}
    ]
    assert index_state["matching_jobs_truncated"] is False
    assert index_state["status"] == "updating"


def test_nonempty_result_remains_available_during_matching_rebuild(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "project").resolve()
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=1,
        state_path=None,
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            str(root),
            JobMode.REBUILD,
        ),
        JobInitiator("test", "search availability", str(root)),
        job_id="paused-rebuild",
        start_paused=True,
    )
    assert created.job is not None
    assert created.job.state is JobState.PAUSED
    before_snapshot = [job.to_dict() for job in manager.list_jobs()]
    after_snapshot = [job.to_dict() for job in manager.list_jobs()]
    index_state: dict[str, object] = {
        "source": "vault",
        "indexed_count": 7,
        "indexed_target_root": str(root),
        "requested_target_root": str(root),
        "target_matches": True,
        "status": "available",
    }
    result: dict[str, object] = {
        "request_id": "request-nonempty",
        "results": [{"opaque_result": {"rank": 1, "tokens": ["kept", 7]}}],
        "index_state": index_state,
        "opaque_envelope": {
            "nested": ["unchanged", {"sentinel": True}],
            "nullable": None,
        },
    }
    expected = deepcopy(result)

    classification = classify_search_response(
        result,
        SearchAvailabilityContext(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            requested_root=root,
            source="vault",
            request_id="request-nonempty",
            index_state=index_state,
            port=8766,
        ),
    )

    assert classification.response is result
    assert classification.response == expected
    assert classification.status_code == 200
    assert [(job.id, job.state, job.mode) for job in classification.matching_jobs] == [
        ("paused-rebuild", "paused", "rebuild")
    ]
    assert classification.matching_jobs_truncated is False
    assert classification.rebuilding is True


def test_matching_jobs_are_bounded_but_hidden_rebuild_still_sets_status(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "project").resolve()
    base = _canonical_snapshot(root, job_id="base", state=JobState.QUEUED)
    snapshots = [
        replace(
            base,
            id=f"job-{index}",
            spec=replace(
                base.spec,
                mode=JobMode.REBUILD if index == 8 else JobMode.INCREMENTAL,
            ),
        ).to_dict()
        for index in range(9)
    ]

    response = _availability_response(root, after=snapshots)

    assert response is not None
    index_state = cast("dict[str, object]", response["index_state"])
    matching_jobs = cast("list[dict[str, object]]", index_state["matching_jobs"])
    assert [job["id"] for job in matching_jobs] == [
        f"job-{index}" for index in range(8)
    ]
    assert index_state["matching_jobs_truncated"] is True
    assert index_state["status"] == "rebuilding"


def test_classification_evidence_is_after_first_bounded_and_shared_with_response(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "project").resolve()
    after = [
        _canonical_snapshot(root, job_id=f"after-{index}").to_dict()
        for index in range(2)
    ]
    before = [
        _canonical_snapshot(
            root,
            job_id=f"before-{index}",
            mode=JobMode.REBUILD if index == 7 else JobMode.INCREMENTAL,
        ).to_dict()
        for index in range(8)
    ]
    index_state: dict[str, object] = {
        "source": "vault",
        "indexed_count": 7,
        "indexed_target_root": str(root),
        "requested_target_root": str(root),
        "target_matches": True,
    }

    classification = classify_search_response(
        {"request_id": "request-merged", "results": []},
        SearchAvailabilityContext(
            before_snapshot=before,
            after_snapshot=after,
            requested_root=root,
            source="vault",
            request_id="request-merged",
            index_state=index_state,
            port=8766,
        ),
    )

    expected_ids = ["after-0", "after-1", *[f"before-{index}" for index in range(6)]]
    assert classification.status_code == 503
    assert [job.id for job in classification.matching_jobs] == expected_ids
    assert classification.matching_jobs_truncated is True
    assert classification.rebuilding is True
    response_index_state = cast(
        "dict[str, object]",
        classification.response["index_state"],
    )
    response_jobs = cast(
        "list[dict[str, object]]", response_index_state["matching_jobs"]
    )
    assert [job["id"] for job in response_jobs] == expected_ids
    assert response_index_state["matching_jobs_truncated"] is True
    assert response_index_state["status"] == "rebuilding"


def _qdrant_collection_response(status_code: int) -> UnexpectedResponse:
    return UnexpectedResponse(
        status_code,
        "Not Found" if status_code == 404 else "Internal Server Error",
        (
            b'{"status":{"error":"Not found: Collection '
            b"`r0123456789ab_vault_docs` doesn't exist!"
            b'"},"time":0.00001}'
        ),
        Headers(),
    )


def test_qdrant_collection_disappearance_uses_matching_canonical_job_evidence(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "project").resolve()
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=1,
        state_path=None,
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            str(root),
            JobMode.REBUILD,
        ),
        JobInitiator("test", "collection disappearance", str(root)),
        job_id="collection-rebuild",
        start_paused=True,
    )
    assert created.job is not None
    before_snapshot = [job.to_dict() for job in manager.list_jobs()]
    index_state: dict[str, object] = {
        "source": "vault",
        "indexed_count": 0,
        "indexed_target_root": str(root),
        "requested_target_root": str(root),
        "target_matches": True,
        "status": "missing",
    }

    classification = classify_qdrant_collection_disappearance(
        _qdrant_collection_response(404),
        SearchAvailabilityContext(
            before_snapshot=before_snapshot,
            after_snapshot=(),
            requested_root=root,
            source="vault",
            request_id="collection-request",
            index_state=index_state,
            port=8766,
        ),
    )

    assert classification is not None
    assert classification.status_code == 503
    assert classification.availability_cause == "collection_missing"
    assert classification.response["error"] == "index_unavailable"
    assert "results" not in classification.response
    assert [(job.id, job.state, job.mode) for job in classification.matching_jobs] == [
        ("collection-rebuild", "paused", "rebuild")
    ]


def test_qdrant_collection_disappearance_declines_unrelated_failures(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "project").resolve()
    matching = _canonical_snapshot(
        root,
        job_id="matching-rebuild",
        mode=JobMode.REBUILD,
    ).to_dict()
    index_state: dict[str, object] = {
        "source": "vault",
        "indexed_count": 0,
        "indexed_target_root": str(root),
        "requested_target_root": str(root),
        "target_matches": True,
        "status": "missing",
    }

    wrong_status = classify_qdrant_collection_disappearance(
        _qdrant_collection_response(500),
        SearchAvailabilityContext(
            before_snapshot=[matching],
            after_snapshot=(),
            requested_root=root,
            source="vault",
            request_id="wrong-status-request",
            index_state=index_state,
            port=8766,
        ),
    )
    no_matching_job = classify_qdrant_collection_disappearance(
        _qdrant_collection_response(404),
        SearchAvailabilityContext(
            before_snapshot=(),
            after_snapshot=(),
            requested_root=root,
            source="vault",
            request_id="no-matching-job-request",
            index_state=index_state,
            port=8766,
        ),
    )

    assert wrong_status is None
    assert no_matching_job is not None
    assert no_matching_job.status_code == 503
    assert no_matching_job.availability_cause == "collection_missing"
    assert no_matching_job.response["error"] == "index_unavailable"
    assert "results" not in no_matching_job.response
