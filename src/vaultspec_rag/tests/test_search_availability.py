"""CPU-only contract tests for canonical search-availability evidence."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING, Literal, cast

import pytest
from httpx import Headers
from qdrant_client.http.exceptions import UnexpectedResponse

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
    classify_qdrant_collection_disappearance,
    classify_search_response,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

pytestmark = [pytest.mark.unit]

type SearchSource = Literal["vault", "code"]


def _canonical_snapshot(
    root: Path,
    *,
    job_id: str,
    source: JobSource = JobSource.VAULT,
    mode: JobMode = JobMode.INCREMENTAL,
    state: JobState = JobState.RUNNING,
) -> JobSnapshot:
    manager = JobManager(max_nonterminal=1, state_path=None)
    outcome = manager.create(
        JobSpec(JobOperation.INDEX, source, str(root), mode),
        JobInitiator("test", "search availability", str(root)),
        job_id=job_id,
    )
    assert outcome.job is not None
    return replace(outcome.job, state=state)


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
    manager = JobManager(max_nonterminal=1, state_path=None)
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
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
        requested_root=root,
        source="vault",
        request_id="request-nonempty",
        index_state=index_state,
        port=8766,
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
        before_snapshot=before,
        after_snapshot=after,
        requested_root=root,
        source="vault",
        request_id="request-merged",
        index_state=index_state,
        port=8766,
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
    manager = JobManager(max_nonterminal=1, state_path=None)
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
        before_snapshot=before_snapshot,
        after_snapshot=(),
        requested_root=root,
        source="vault",
        request_id="collection-request",
        index_state=index_state,
        port=8766,
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
        before_snapshot=[matching],
        after_snapshot=(),
        requested_root=root,
        source="vault",
        request_id="wrong-status-request",
        index_state=index_state,
        port=8766,
    )
    no_matching_job = classify_qdrant_collection_disappearance(
        _qdrant_collection_response(404),
        before_snapshot=(),
        after_snapshot=(),
        requested_root=root,
        source="vault",
        request_id="no-matching-job-request",
        index_state=index_state,
        port=8766,
    )

    assert wrong_status is None
    assert no_matching_job is None
