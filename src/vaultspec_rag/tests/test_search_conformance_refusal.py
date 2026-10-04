"""CPU search outcomes backed by real local Qdrant compatibility checks."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Literal, cast

import pytest
from qdrant_client import models

from .. import _public_search, store_schema
from .._operator_commands import IndexCommandOptions, index_command
from .._search_state import (
    AbsenceAuthority,
    FreshnessWaitPolicy,
    GenerationEvidence,
    SearchAvailability,
    SearchFreshness,
    SearchReasonCode,
    SearchSourceFact,
)
from .._source_types import INDEX_SOURCES, IndexSource, PublicSourceType
from .._store_search import HybridSearchRequest
from ..search import DocumentSearchResult, SearchResult
from ..search._outcomes import COMBINED_SEARCH_FAILED, CombinedSearchOutcome
from ..server._routes_search import _search_response_status
from ..server._search_availability import storage_conformance_refusal_fact
from ..server._search_readiness import ReadinessRevisionSnapshot, ReadinessSourceKey
from ..server._search_route_availability import (
    SearchAvailabilityRequestFacts,
    apply_combined_search_outcome,
    run_search_with_availability,
)
from ..service import ServiceRegistry
from ..storage_identity import sidecar_path
from ..store_runtime import StorageGeometryError, StorageModelError, VaultStore

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..search._outcomes import AnySearchResult, SearchDomainOutcome

pytestmark = pytest.mark.unit

type Mismatch = Literal["sparse_model", "dense_dim", "distance", "dense_vector_name"]


def _collections(store: VaultStore) -> dict[IndexSource, str]:
    return {
        "vault": store.TABLE_NAME,
        "code": store.CODE_TABLE_NAME,
        "document": store.DOCUMENT_TABLE_NAME,
    }


@contextmanager
def _populated_store(root: Path) -> Generator[VaultStore]:
    store = VaultStore(root, embedding_dim=4)
    try:
        store.ensure_table()
        store.ensure_code_table()
        store.ensure_document_table()
        for source, collection in _collections(store).items():
            store.client.upsert(
                collection,
                [
                    models.PointStruct(
                        id=1,
                        vector={"dense": [0.1, 0.2, 0.3, 0.4]},
                        payload={
                            "doc_id": source,
                            "chunk_id": source,
                            "document_id": source,
                            "path": f"{source}.txt",
                        },
                    )
                ],
            )
        yield store
    finally:
        store.close()


def _change_identity(store: VaultStore, source: IndexSource, field: str) -> bytes:
    path = sidecar_path(store.db_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    identity = raw["collections"][_collections(store)[source]]
    identity[field] = 8 if field == "dense_dim" else "superseded/identity"
    path.write_text(json.dumps(raw), encoding="utf-8")
    # A fresh verification is required on the next normal read.
    store._ensured.clear()
    return path.read_bytes()


def _search(store: VaultStore, source: IndexSource) -> list[dict[str, object]]:
    operations = {
        "vault": store.hybrid_search,
        "code": store.hybrid_search_codebase,
        "document": store.hybrid_search_document,
    }
    return operations[source](
        HybridSearchRequest(query_text="query", query_vector=[0.1, 0.2, 0.3, 0.4])
    )


def _current_fact(source: IndexSource) -> SearchSourceFact:
    return SearchSourceFact(
        source=source,
        availability=SearchAvailability.USABLE,
        freshness=SearchFreshness.CURRENT,
        absence_authority=AbsenceAuthority.AUTHORITATIVE,
        generation=GenerationEvidence(
            served_generation="captured",
            desired_generation="captured",
            served_revision=7,
            desired_revision=7,
        ),
        evidence=("captured-job",),
    )


def _request_facts(root: Path, source: IndexSource) -> SearchAvailabilityRequestFacts:
    return SearchAvailabilityRequestFacts(
        job_snapshot_before=[],
        root=root,
        source=source,
        request_id="conformance-search",
        port=8767,
        readiness_snapshot=ReadinessRevisionSnapshot(
            ReadinessSourceKey.from_root(root, source),
            published_generation="captured",
            desired_generation="captured",
            publication_revision=7,
            controller_revision=7,
        ),
        wait_policy=FreshnessWaitPolicy.BOUNDED,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", INDEX_SOURCES)
@pytest.mark.parametrize(
    "mismatch", ["sparse_model", "dense_dim", "distance", "dense_vector_name"]
)
async def test_concrete_storage_refusal_has_actionable_rebuild_outcome(
    tmp_path: Path,
    source: IndexSource,
    mismatch: Mismatch,
) -> None:
    # Guard: removing the typed interception leaks the real storage exception.
    with _populated_store(tmp_path) as store:
        identity_before = _change_identity(store, source, mismatch)
        response, classification = await run_search_with_availability(
            lambda: {"results": _search(store, source)},
            _request_facts(tmp_path, source),
        )
        assert classification is not None
        assert classification.status_code == _search_response_status(response) == 409
        assert response["error"] == "rebuild_required"
        assert response["ok"] is False
        assert response["retryable"] is False
        assert "results" not in response
        state = cast("dict[str, object]", response["index_state"])
        # A refused query cannot assert a measured zero or collection absence.
        assert "indexed_count" not in state
        assert state["status"] == "unavailable"
        assert state["source"] == source
        assert state["requested_target_root"] == str(tmp_path)
        assert response["remediation"] == index_command(
            source, IndexCommandOptions(rebuild=True, port=8767, target=str(tmp_path))
        )
        assert _collections(store)[source] in str(response["message"])
        fact = classification.source_fact
        assert fact.availability is SearchAvailability.UNAVAILABLE
        assert fact.freshness is SearchFreshness.REBUILD_REQUIRED
        assert fact.absence_authority is AbsenceAuthority.NON_AUTHORITATIVE
        assert fact.wait_policy is FreshnessWaitPolicy.BOUNDED
        assert fact.generation == _current_fact(source).generation
        assert store.client.count(_collections(store)[source], exact=True).count == 1
        assert sidecar_path(store.db_path).read_bytes() == identity_before


@pytest.mark.asyncio
@pytest.mark.parametrize("source", INDEX_SOURCES)
async def test_dense_model_mismatch_keeps_matching_geometry_searchable(
    tmp_path: Path,
    source: IndexSource,
) -> None:
    # Guard: treating dense provenance as a fatal sparse mismatch refuses hits.
    with _populated_store(tmp_path) as store:
        identity_before = _change_identity(store, source, "dense_model")
        response, classification = await run_search_with_availability(
            lambda: {"results": _search(store, source)},
            _request_facts(tmp_path, source),
        )
        assert classification is None
        assert len(cast("list[object]", response["results"])) == 1
        verdict = store.conformance_verdicts()[_collections(store)[source]]
        assert verdict.verdict == store_schema.NONCONFORMING
        assert not verdict.geometry_fatal and not verdict.sparse_model_fatal
        assert sidecar_path(store.db_path).read_bytes() == identity_before


@pytest.mark.asyncio
async def test_concrete_query_does_not_ensure_an_unrelated_collection(
    tmp_path: Path,
) -> None:
    with _populated_store(tmp_path) as store:
        _change_identity(store, "document", "sparse_model")
        response, classification = await run_search_with_availability(
            lambda: {"results": _search(store, "code")},
            _request_facts(tmp_path, "code"),
        )
        assert classification is None
        assert len(cast("list[object]", response["results"])) == 1
        with pytest.raises(StorageModelError):
            _search(store, "document")


@pytest.mark.asyncio
async def test_concrete_unknown_failure_is_not_classified_by_its_text(
    tmp_path: Path,
) -> None:
    def fail() -> dict[str, object]:
        raise RuntimeError("full_reindex_required: unrelated application failure")

    # Guard: a broad interception or text taxonomy hides an unknown defect.
    with pytest.raises(RuntimeError, match="unrelated application failure"):
        await run_search_with_availability(fail, _request_facts(tmp_path, "code"))


def _domain(store: VaultStore, source: IndexSource) -> SearchDomainOutcome:
    def retrieve() -> list[AnySearchResult]:
        rows = _search(store, source)
        if source == "document":
            return [
                DocumentSearchResult(
                    str(row["id"]), "document.txt", "Document", 0.8, "text"
                )
                for row in rows
            ]
        return [
            SearchResult(
                str(row["id"]),
                f"{source}.txt",
                source,
                0.7,
                "text",
                "vault" if source == "vault" else "codebase",
            )
            for row in rows
        ]

    return _public_search._search_domain(
        _public_search._DomainSearch(
            PublicSourceType(source), store.root_dir, retrieve
        ),
        _current_fact(source),
    )


def _combined_response(outcome: CombinedSearchOutcome) -> dict[str, object]:
    response: dict[str, object] = {"results": [result.id for result in outcome.results]}
    apply_combined_search_outcome(
        response,
        outcome,
        request_id="combined-conformance",
        index_state={"source": "combined"},
        has_results=bool(outcome.results),
    )
    return response


@pytest.mark.parametrize("source", INDEX_SOURCES)
@pytest.mark.parametrize("mismatch", ["sparse_model", "dense_dim"])
def test_combined_refusal_retains_compatible_hits_and_actual_source_failure(
    tmp_path: Path,
    source: IndexSource,
    mismatch: Mismatch,
) -> None:
    # Guard: reusing the preflight current fact loses the failed constituent.
    with _populated_store(tmp_path) as store:
        _change_identity(store, source, mismatch)
        domains = {name: _domain(store, name) for name in INDEX_SOURCES}
        combined = CombinedSearchOutcome(
            domains["vault"], domains["code"], domains["document"], top_k=5
        )
        response = _combined_response(combined)
        failed = domains[source]
        assert failed.error_kind == "rebuild_required"
        assert failed.source_fact.source == source
        assert failed.source_fact.availability is SearchAvailability.UNAVAILABLE
        assert failed.source_fact.freshness is SearchFreshness.REBUILD_REQUIRED
        assert (
            failed.source_fact.absence_authority is AbsenceAuthority.NON_AUTHORITATIVE
        )
        assert failed.source_fact.retryable is False
        assert failed.source_fact.generation == _current_fact(source).generation
        assert failed.source_fact.evidence == ("captured-job",)
        assert failed.source_fact.remediation == index_command(
            source, IndexCommandOptions(rebuild=True, target=str(tmp_path))
        )
        assert set(cast("list[str]", response["results"])) == set(INDEX_SOURCES) - {
            source
        }
        assert response["ok"] is True and response["partial"] is True
        assert _search_response_status(response) == 200
        payload = combined.domain_status_payload()
        assert payload[source]["readiness"] == failed.source_fact.as_dict()
        assert combined.readiness.usable_source_count == 2


def test_all_combined_refusals_preserve_existing_total_failure_protocol(
    tmp_path: Path,
) -> None:
    with _populated_store(tmp_path) as store:
        for source in INDEX_SOURCES:
            _change_identity(store, source, "sparse_model")
        combined = CombinedSearchOutcome(
            _domain(store, "vault"),
            _domain(store, "code"),
            _domain(store, "document"),
            top_k=5,
        )
        response = _combined_response(combined)
        assert response["error"] == COMBINED_SEARCH_FAILED
        assert _search_response_status(response) == 503
        assert response["retryable"] is False
        assert "results" not in response
        assert combined.readiness.usable_source_count == 0
        assert all(
            fact.reason_code is SearchReasonCode.REBUILD_REQUIRED
            for fact in combined.source_facts
        )
        assert response["remediation"] == combined.vault.source_fact.remediation


def test_empty_compatible_combined_domains_cannot_claim_authoritative_absence(
    tmp_path: Path,
) -> None:
    with _populated_store(tmp_path) as store:
        _change_identity(store, "code", "sparse_model")
        for source in ("vault", "document"):
            store.client.delete(
                _collections(store)[source], models.PointIdsList(points=[1])
            )
        combined = CombinedSearchOutcome(
            _domain(store, "vault"),
            _domain(store, "code"),
            _domain(store, "document"),
            top_k=5,
        )
        response = _combined_response(combined)
        assert response["error"] == "rebuild_required"
        assert _search_response_status(response) == 409
        assert response["ok"] is False and response["partial"] is True
        assert "results" not in response
        assert (
            combined.readiness.absence_authority is AbsenceAuthority.NON_AUTHORITATIVE
        )


@pytest.mark.parametrize("source", INDEX_SOURCES)
def test_combined_count_refusal_uses_the_same_typed_source_fact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: IndexSource,
) -> None:
    # The count seam can fail before retrieval; use the actual storage refusal.
    with _populated_store(tmp_path) as store:
        _change_identity(store, source, "sparse_model")
        registry = ServiceRegistry()
        methods = {
            "vault": "vault_doc_count",
            "code": "code_chunk_count",
            "document": "document_chunk_count",
        }
        for name, method in methods.items():

            def count(_root: Path, name: str = name) -> int:
                return len(_search(store, cast("IndexSource", name)))

            monkeypatch.setattr(
                registry,
                method,
                count,
            )
        counts, failures, facts, timings = _public_search._count_combined_domains(
            tmp_path, registry
        )
        assert source not in counts
        assert f"{source}_indexed_count" not in timings
        assert failures[PublicSourceType(source)].error_kind == "rebuild_required"
        assert (
            facts[PublicSourceType(source)].freshness
            is SearchFreshness.REBUILD_REQUIRED
        )
        assert facts[PublicSourceType(source)].retryable is False
        assert (
            facts[PublicSourceType(source)].availability
            is SearchAvailability.UNAVAILABLE
        )


def test_unknown_combined_failure_preserves_exception_without_rebuild_authority(
    tmp_path: Path,
) -> None:
    def fail() -> list[AnySearchResult]:
        raise ValueError("full_reindex_required: unrelated application failure")

    domain = _public_search._search_domain(
        _public_search._DomainSearch(PublicSourceType.CODE, tmp_path, fail),
        _current_fact("code"),
    )
    assert domain.error_kind == "ValueError"
    assert domain.source_fact == _current_fact("code")
    assert "--rebuild" not in str(domain.source_fact.remediation)


@pytest.mark.parametrize("error_type", [StorageGeometryError, StorageModelError])
def test_failure_fact_preserves_bounded_evidence_but_replaces_readiness(
    tmp_path: Path,
    error_type: type[StorageGeometryError],
) -> None:
    original = replace(
        _current_fact("document"), wait_policy=FreshnessWaitPolicy.BOUNDED
    )
    fact = storage_conformance_refusal_fact(
        error_type("incompatible actual document vectors"), original, root=tmp_path
    )
    assert fact is not None
    assert fact.generation == original.generation
    assert fact.evidence == original.evidence
    assert fact.wait_policy == original.wait_policy
    assert fact.reason_code is SearchReasonCode.REBUILD_REQUIRED
    assert fact.retryable is False
