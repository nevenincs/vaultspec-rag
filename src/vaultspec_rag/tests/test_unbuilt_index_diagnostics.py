"""First-publication diagnostics from canonical proof, count, and job evidence."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from .._index_integrity import (
    IndexIntegrity,
    IndexIntegritySnapshot,
    IntegrityReason,
    IntegrityVerdict,
    acquire_index_integrity_snapshot_if_proven,
)
from .._search_state import SearchAvailability, SearchFreshness, SearchReasonCode
from .._source_types import INDEX_SOURCES, IndexSource, PublicSourceType
from ..indexer._run_ledger_models import RunAuthority
from ..job_models import JobMode, JobState
from ..mcp._tools import _validated_search_result
from ..server._search_availability import (
    SearchAvailabilityContext,
    SearchResponseClassification,
    classify_search_response,
)
from ..server._search_route_availability import (
    SearchAvailabilityRequestFacts,
    SearchIndexStateInput,
    _empty_search_diagnostics,
    search_index_state_for_route,
)
from .test_cli_search import _invoke_readiness_search, _search_envelope_service
from .test_publication_integrity import _published_empty_vault
from .test_search_availability import _canonical_snapshot

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _unbuilt_context(root: Path, source: IndexSource) -> SearchAvailabilityContext:
    integrity = acquire_index_integrity_snapshot_if_proven(
        root, PublicSourceType(source)
    )
    assert isinstance(integrity, IndexIntegrity)
    assert integrity.reason == "proof_missing"
    index_state = search_index_state_for_route(
        SearchIndexStateInput(
            indexed_count=0,
            requested_root=root,
            search_type=source,
            integrity=integrity.finish(0),
        )
    )
    return SearchAvailabilityRequestFacts(
        job_snapshot_before=[],
        root=root,
        source=source,
        request_id="first-publication",
        port=8766,
    ).to_context(after_snapshot=[], index_state=index_state)


def _classify(context: SearchAvailabilityContext) -> SearchResponseClassification:
    return classify_search_response({"results": []}, context)


@pytest.mark.parametrize("source", INDEX_SOURCES)
def test_unbuilt_source_reports_initial_indexing(
    tmp_path: Path, source: IndexSource
) -> None:
    classification = _classify(_unbuilt_context(tmp_path, source))
    fact = classification.source_fact
    response = classification.response

    assert classification.status_code == 503
    assert fact.reason_code == "index_not_built"
    assert fact.availability is SearchAvailability.UNAVAILABLE
    assert fact.freshness is SearchFreshness.UNVERIFIABLE
    assert response["error"] == "index_unavailable"
    assert response["retryable"] is False
    # Mutation-proven RED/GREEN: adding results=[] to the failure fails here.
    assert "results" not in response
    assert "has not been built yet" in str(response["message"])
    assert "does not by itself indicate a degraded service" in str(response["message"])
    remediation = str(response["remediation"])
    assert "server status --port 8766 --verbose" in remediation
    assert f"server jobs --state active --index {source} --port 8766" in remediation
    assert f"--target {tmp_path}" in remediation
    assert f"index --rebuild --type {source} --port 8766" in remediation
    assert "verify this root's index status and retry" in remediation


@pytest.mark.parametrize("state", [JobState.QUEUED, JobState.RUNNING, JobState.PAUSED])
def test_first_publication_job_is_monitored_before_another_build(
    tmp_path: Path,
    state: JobState,
) -> None:
    context = _unbuilt_context(tmp_path, "vault")
    job = _canonical_snapshot(
        tmp_path,
        job_id="initial-build",
        mode=JobMode.REBUILD,
        authority=RunAuthority.REBUILD,
        state=state,
    ).to_dict()
    classification = _classify(replace(context, after_snapshot=[job]))

    assert classification.status_code == 503
    assert classification.source_fact.availability is SearchAvailability.UNAVAILABLE
    assert classification.source_fact.freshness is SearchFreshness.UPDATING
    assert classification.source_fact.reason_code == "index_updating"
    assert classification.source_fact.evidence == ("initial-build",)
    assert "Inspect the matching job before submitting another" in str(
        classification.response["message"]
    )
    assert (
        classification.response["remediation"]
        == "vaultspec-rag server jobs --state active --index vault --port 8766"
    )


@pytest.mark.parametrize("mismatch", ["root", "source", "terminal"])
def test_unrelated_or_finished_jobs_do_not_hide_an_unbuilt_index(
    tmp_path: Path,
    mismatch: str,
) -> None:
    context = _unbuilt_context(tmp_path, "code")
    job = _canonical_snapshot(
        tmp_path if mismatch != "root" else tmp_path / "other",
        job_id="other-job",
        mode=JobMode.REBUILD,
        authority=RunAuthority.REBUILD,
        state=JobState.SUCCEEDED if mismatch == "terminal" else JobState.RUNNING,
    ).to_dict()
    spec = cast("dict[str, object]", job["spec"])
    spec["source"] = "vault" if mismatch == "source" else "code"
    classification = _classify(replace(context, after_snapshot=[job]))

    assert classification.source_fact.reason_code == "index_not_built"
    assert classification.source_fact.evidence == ()


@pytest.mark.parametrize("count", [0, 12])
def test_unreadable_proof_is_distinct_from_a_first_index(
    tmp_path: Path, count: int
) -> None:
    context = _unbuilt_context(tmp_path, "code")
    integrity = cast("dict[str, object]", context.index_state["index_integrity"])
    state = dict(context.index_state)
    state.update(
        indexed_count=count,
        index_integrity=integrity | {"reason": "proof_unreadable", "live_count": count},
    )
    classification = _classify(replace(context, index_state=state))

    assert classification.source_fact.reason_code == "index_unverifiable"
    assert (
        classification.source_fact.remediation
        == "vaultspec-rag server status --port 8766 --verbose"
    )


def test_existing_records_without_proof_are_not_reported_as_unbuilt(
    tmp_path: Path,
) -> None:
    context = _unbuilt_context(tmp_path, "code")
    state = dict(context.index_state)
    state["indexed_count"] = 12
    classification = _classify(replace(context, index_state=state))
    # Mutation-proven RED/GREEN: always classifying as unbuilt fails here.
    assert classification.source_fact.reason_code == "index_unverifiable"


def test_verified_empty_publication_is_authoritative(tmp_path: Path) -> None:
    _published_empty_vault(tmp_path)
    snapshot = acquire_index_integrity_snapshot_if_proven(
        tmp_path, PublicSourceType.VAULT
    )
    assert isinstance(snapshot, IndexIntegritySnapshot)
    proof = snapshot.publication.proof
    state = search_index_state_for_route(
        SearchIndexStateInput(
            indexed_count=0,
            requested_root=tmp_path,
            search_type=PublicSourceType.VAULT,
            integrity=snapshot.finish(0),
        )
    )
    context = SearchAvailabilityRequestFacts(
        job_snapshot_before=[],
        root=tmp_path,
        source="vault",
        request_id="empty-publication",
        port=8766,
    ).to_context(after_snapshot=[], index_state=state)
    context = replace(
        context,
        canonical_evidence=replace(
            context.canonical_evidence,
            served_generation=proof.generation_id,
            desired_generation=proof.generation_id,
            publication_revision=proof.revision,
            desired_revision=proof.revision,
        ),
    )
    classification = _classify(context)

    assert classification.status_code == 200
    assert classification.source_fact.freshness is SearchFreshness.CURRENT
    assert classification.response["results"] == []
    assert state["status"] == "available"
    # Mutation-proven RED/GREEN: retaining rebuild guidance fails this block.
    assert _empty_search_diagnostics(state, port=8766) == {
        "reason": "published_empty",
        "message": "The published vault index is empty.",
        "remediation": [],
    }


def test_mcp_and_cli_preserve_first_index_diagnostics(tmp_path: Path) -> None:
    response = _classify(_unbuilt_context(tmp_path, "code")).response
    assert _validated_search_result(response).model_dump(mode="json") == response
    with _search_envelope_service(response, status=503) as (port, _requests):
        result = _invoke_readiness_search(tmp_path, port, "--json")
        human = _invoke_readiness_search(tmp_path, port)

    assert result.exit_code == human.exit_code == 1
    assert json.loads(result.output) == response | {"command": "search"}
    compact = " ".join(human.output.split())
    assert "has not been built yet" in compact
    assert "does not by itself indicate a degraded service" in compact
    assert "reason=index_not_built" in compact
    assert "index --rebuild --type code --port 8766" in compact


def test_source_fact_rejects_a_bare_reason_string(tmp_path: Path) -> None:
    fact = _classify(_unbuilt_context(tmp_path, "code")).source_fact
    # Mutation-proven RED/GREEN: removing reason enum validation fails here.
    with pytest.raises(ValueError, match="reason_code must be a SearchReasonCode"):
        replace(fact, reason_code=cast("SearchReasonCode", "index_not_built"))


@pytest.mark.parametrize("field", ["verdict", "source", "reason"])
def test_integrity_rejects_bare_state_strings(field: str) -> None:
    integrity = IndexIntegrity(
        verdict=IntegrityVerdict.UNVERIFIABLE,
        source=PublicSourceType.CODE,
        claimed_count=None,
        live_count=0,
        generation_id=None,
        reason=IntegrityReason.PROOF_MISSING,
    )
    # Mutation-proven RED/GREEN: removing integrity enum validation fails here.
    with pytest.raises(ValueError, match=f"{field} must be a"):
        if field == "verdict":
            replace(integrity, verdict=cast("IntegrityVerdict", "unverifiable"))
        elif field == "source":
            replace(integrity, source=cast("PublicSourceType", "code"))
        else:
            replace(integrity, reason=cast("IntegrityReason", "proof_missing"))


def test_mcp_rejects_an_unknown_reason_code(tmp_path: Path) -> None:
    from pydantic import ValidationError

    payload = _classify(_unbuilt_context(tmp_path, "code")).response
    readiness = cast("dict[str, object]", payload["readiness"])
    sources = cast("list[dict[str, object]]", readiness["sources"])
    sources[0]["reason_code"] = "index_not_bulit"
    # Mutation-proven RED/GREEN: widening the MCP reason field to str fails here.
    with pytest.raises(ValidationError, match="reason_code"):
        _validated_search_result(payload)


@pytest.mark.parametrize("source", INDEX_SOURCES)
@pytest.mark.parametrize("json_mode", [True, False])
def test_in_process_cli_reports_initial_indexing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    source: IndexSource,
    json_mode: bool,
) -> None:
    import typer

    from ..cli._search import _InProcessRenderRequest, _render_in_process_results

    context = _unbuilt_context(tmp_path, source)
    request = _InProcessRenderRequest(
        results=[],
        query="readiness",
        search_type=PublicSourceType(source),
        json_mode=json_mode,
        show_scores=False,
        target=tmp_path,
        envelope={"index_state": dict(context.index_state)},
    )
    with pytest.raises(typer.Exit) as raised:
        _render_in_process_results(request)
    assert raised.value.exit_code == 1
    output = capsys.readouterr().out
    if json_mode:
        payload = json.loads(output)
        assert payload["error"] == "index_unavailable"
        assert payload["readiness"]["sources"][0]["reason_code"] == "index_not_built"
        assert "results" not in payload
    else:
        assert "has not been built yet" in " ".join(output.split())


def test_in_process_combined_cli_preserves_all_unbuilt_sources(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import typer

    from ..cli._search import _InProcessRenderRequest, _render_in_process_results
    from ..search._outcomes import CombinedSearchOutcome, SearchDomainOutcome

    contexts = {source: _unbuilt_context(tmp_path, source) for source in INDEX_SOURCES}
    domains = {
        source: SearchDomainOutcome.success(
            PublicSourceType(source), [], source_fact=_classify(context).source_fact
        )
        for source, context in contexts.items()
    }
    outcome = CombinedSearchOutcome(
        vault=domains["vault"],
        code=domains["code"],
        document=domains["document"],
        top_k=10,
    )
    request = _InProcessRenderRequest(
        results=outcome,
        query="readiness",
        search_type=PublicSourceType.COMBINED,
        json_mode=True,
        show_scores=False,
        target=tmp_path,
        envelope={"index_state": dict(contexts["code"].index_state)},
    )
    with pytest.raises(typer.Exit) as raised:
        _render_in_process_results(request)
    assert raised.value.exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "index_unavailable"
    assert {fact["source"] for fact in payload["readiness"]["sources"]} == {
        "vault",
        "code",
        "document",
    }
    assert all(
        fact["reason_code"] == "index_not_built"
        for fact in payload["readiness"]["sources"]
    )
