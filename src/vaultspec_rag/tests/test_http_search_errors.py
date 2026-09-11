"""Strict search-response tests for the shared HTTP and MCP consumers."""

from __future__ import annotations

import socket
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from httpx import Headers
from pydantic import ValidationError
from qdrant_client.http.exceptions import UnexpectedResponse
from starlette.testclient import TestClient

from .._search_state import MAX_SEARCH_EVIDENCE_ITEMS
from .._source_types import INDEX_SOURCES, PublicSourceType
from .._store_locks import VaultStoreLockedError
from ..config._settings import get_config, reset_config
from ..mcp._tools import _validated_search_result
from ..registry import get_registry, reset_registry
from ..search._models import SearchResult
from ..server import (
    ServerRouteRuntime,
    _local_store_locked_error_dict,
    _registry,
    _registry_full_error_dict,
    create_http_app,
)
from ..server._routes_search import (
    SearchAvailabilityRequestFacts,
    SearchRequest,
    _classify_completed_search,
    _classify_search_result,
    _search_response_status,
)
from ..server._search_availability import (
    CanonicalSearchEvidence,
    SearchAvailabilityContext,
    classify_qdrant_collection_disappearance,
    classify_search_response,
)
from ..server._search_readiness import ReadinessRevisionSnapshot, ReadinessSourceKey
from ..service import RegistryFullError, ServiceRegistry
from ..serviceclient._search_transport import (
    _search_response_envelope,
    try_http_search,
)
from ._search_readiness_scenarios import (
    SEARCH_READINESS_SCENARIOS,
    canonical_service_envelope,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from .._source_types import IndexSource

pytestmark = [pytest.mark.unit]


def _http_search(port: int) -> dict[str, object] | None:
    return try_http_search("response contract", "vault", 3, port, "")


def test_valid_search_envelope_is_unchanged() -> None:
    expected = canonical_service_envelope(SEARCH_READINESS_SCENARIOS["current"])
    result = _search_response_envelope(expected, 8766)

    assert result is expected
    assert _validated_search_result(result).model_dump(mode="json") == expected


def test_structured_search_error_is_unchanged() -> None:
    expected: dict[str, object] = {
        "ok": False,
        "error": "index_unavailable",
        "message": "The vault index is changing.",
        "remediation": [
            "vaultspec-rag server jobs --state active --index vault --port 8766",
            "Retry after the matching job reaches a terminal state.",
        ],
    }
    result = _search_response_envelope(expected, 8766)

    assert result is expected


@pytest.mark.parametrize(
    "response",
    [
        {},
        [],
        "legacy",
        None,
        {"summary": "missing results"},
        {"results": "legacy"},
    ],
    ids=[
        "empty-object",
        "legacy-list",
        "json-string",
        "json-null",
        "missing-results",
        "wrong-results-type",
    ],
)
def test_malformed_search_shapes_return_stable_failure(response: object) -> None:
    port = 8766
    result = _search_response_envelope(response, port)

    assert result == {
        "ok": False,
        "error": "invalid_service_response",
        "message": (
            f"HTTP search on port {port} returned an invalid service response; "
            "expected a non-empty JSON object envelope containing results or "
            "a structured error."
        ),
    }


def test_refused_search_connection_remains_unreachable() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
        result = _http_search(port)

    assert result is None


@pytest.mark.parametrize("result", [[], "legacy", None])
def test_mcp_rejects_non_object_search_envelopes(result: object) -> None:
    with pytest.raises(RuntimeError, match=r"^invalid_service_response:"):
        _validated_search_result(result)


@pytest.mark.parametrize("result", [{}, {"summary": "missing"}, {"results": "legacy"}])
def test_mcp_rejects_malformed_object_search_envelopes(
    result: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _validated_search_result(result)


def _status_contract_request(root: Path) -> SearchRequest:
    return SearchRequest(
        root=root,
        query="response status contract",
        top_k=3,
        payload={},
        search_type=PublicSourceType.VAULT,
        request_id="response-status-contract",
    )


def _status_contract_facts(root: Path) -> SearchAvailabilityRequestFacts:
    return SearchAvailabilityRequestFacts(
        job_snapshot_before=[],
        root=root,
        source="vault",
        request_id="response-status-contract",
        port=None,
    )


def test_search_route_keeps_the_runtime_registry_after_global_shutdown(
    tmp_path: Path,
) -> None:
    """An unverifiable empty runtime vault fails after global registry shutdown.

    The real, model-free count reaches the runtime registry. Reverting the
    route to a public facade that resolves ``get_registry()`` makes this a 500
    because the deliberately closed singleton rejects the count lease.
    """
    root = tmp_path / "vault"
    (root / ".vault").mkdir(parents=True)
    get_config({"watch_enabled": False})
    reset_registry()
    global_registry = get_registry()
    global_registry.close_all()
    runtime_registry = ServiceRegistry()
    app = create_http_app(
        ServerRouteRuntime(
            token="runtime-registry-search-token",
            registry=runtime_registry,
            port=8765,
        ),
        lifespan=None,
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/search",
                headers={"Authorization": "Bearer runtime-registry-search-token"},
                json={
                    "query": "runtime registry remains authoritative",
                    "project_root": str(root),
                },
            )

        assert response.status_code == 503, response.text
        payload = response.json()
        assert payload["error"] == "index_unverifiable"
        assert payload["retryable"] is False
        assert "results" not in payload
        # Adding an unconditional Retry-After at the JSONResponse seam made
        # this exact absence assertion fail with `'1' is None` (exit 1);
        # restoring the header-free response passed (exit 0).
        assert response.headers.get("retry-after") is None
    finally:
        runtime_registry.close_all()
        reset_registry()
        reset_config()


@pytest.mark.parametrize("search_type", ["code", "combined"])
def test_a_never_indexed_root_answers_rather_than_failing(
    tmp_path: Path,
    search_type: str,
) -> None:
    """The first search on a new project answers with a typed outcome, not a fault.

    A root nobody has indexed has no publication proof, and every read that
    reaches for one has to treat that as an absence rather than a refusal. An
    empty page from that root cannot prove absence, so the answer is the typed
    non-authoritative failure - never a server fault, and never results.
    The code domain is the one that publishes a breadth claim, so it is the
    domain where a strict proof read leaks: `code` reaches it directly and
    `combined` reaches it through the code leg. Both are asserted because a
    tolerant read on one and a strict read on the other still 500s the
    operator, just less often.

    The verdict is asserted, not only the status. A typed answer that reports
    nothing about breadth would hide a strict read behind a swallowed
    exception; `unverifiable` is the typed outcome that says the proof could
    not be read and no claim was invented in its place.

    Proven able to fail: restoring the strict `acquire_code_breadth_snapshot`
    in `search_codebase_timed` fails the `code` parameter on the status
    assertion with a 500. The `combined` parameter stays green under that same
    mutation, because its code leg does not reach that call - which is the
    reason both are pinned rather than only the one that fails today. A later
    change that routes the combined leg through the same read would otherwise
    reintroduce the failure with nothing watching.
    """
    root = tmp_path / "fresh-project"
    (root / ".vault").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "example.py").write_text(
        "def f():\n    return 1\n", encoding="utf-8"
    )
    get_config({"watch_enabled": False})
    reset_registry()
    runtime_registry = ServiceRegistry()
    token = "never-indexed-search-token"
    app = create_http_app(
        ServerRouteRuntime(token=token, registry=runtime_registry, port=8765),
        lifespan=None,
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/search",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "query": "anything at all",
                    "type": search_type,
                    "project_root": str(root),
                },
            )

        assert response.status_code == 503, response.text
        payload = cast("dict[str, object]", response.json())
        assert payload["error"] == "index_unverifiable", payload
        assert payload["retryable"] is False, payload
        assert "results" not in payload
        index_state = cast("dict[str, object]", payload["index_state"])
        integrity = cast("dict[str, object]", index_state["index_integrity"])
        assert integrity["verdict"] == "unverifiable", integrity
        assert integrity["reason"] == "proof_unreadable", integrity
    finally:
        runtime_registry.close_all()
        reset_registry()
        reset_config()


def test_mutating_routes_reject_a_closed_runtime_before_global_or_gpu_work(
    tmp_path: Path,
) -> None:
    """The app runtime remains the sole authority for mutating route facades."""
    root = tmp_path / "vault"
    (root / ".vault").mkdir(parents=True)
    get_config({"watch_enabled": True})
    reset_registry()
    global_registry = get_registry()
    runtime_registry = ServiceRegistry()
    runtime_registry.close_all()
    token = "runtime-registry-mutation-token"
    app = create_http_app(
        ServerRouteRuntime(
            token=token,
            registry=runtime_registry,
            port=8765,
        ),
        lifespan=None,
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            headers = {"Authorization": f"Bearer {token}"}
            watcher = client.post(
                "/watcher/start",
                headers=headers,
                json={"root": str(root)},
            )
            clean = client.post(
                "/clean",
                headers=headers,
                json={"project_root": str(root), "type": "vault"},
            )
            benchmark = client.post(
                "/benchmark",
                headers=headers,
                json={"project_root": str(root), "n_queries": 1},
            )
            quality = client.post("/quality", headers=headers)

        assert global_registry is not runtime_registry
        assert watcher.status_code == 200, watcher.text
        assert watcher.json()["status"] == "unavailable"
        assert clean.status_code == 409, clean.text
        clean_domains = clean.json()["domains"]
        assert clean_domains["vault"]["error_kind"] == "RuntimeError"
        assert clean_domains["vault"]["detail"] == "ServiceRegistry is shutting down"
        assert benchmark.status_code == 500, benchmark.text
        assert quality.status_code == 500, quality.text
    finally:
        runtime_registry.close_all()
        reset_registry()
        reset_config()


class TestSearchResponseStatus:
    """Retryable admission failures must not reach the wire as success."""

    def test_registry_full_envelope_reports_service_unavailable(self) -> None:
        envelope: dict[str, object] = _registry_full_error_dict(
            RegistryFullError(_registry.max_projects),
            _registry,
        )

        assert envelope["ok"] is False
        assert _search_response_status(envelope) == 503

    def test_local_store_locked_envelope_reports_service_unavailable(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = tmp_path / ".vault" / "data" / "search-data" / "qdrant"
        envelope: dict[str, object] = _local_store_locked_error_dict(
            VaultStoreLockedError(str(db_path))
        )

        assert envelope["ok"] is False
        assert _search_response_status(envelope) == 503

    def test_retrieval_envelope_keeps_the_success_status(self) -> None:
        envelope: dict[str, object] = {"results": [], "summary": "no results"}

        assert _search_response_status(envelope) == 200

    def test_failure_status_does_not_depend_on_a_missing_results_key(self) -> None:
        """Status follows the failure declaration, not the payload's shape."""
        envelope: dict[str, object] = {
            "ok": False,
            "error": "registry_full",
            "message": "every slot is busy",
            "results": [],
        }

        assert _search_response_status(envelope) == 503

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            ("index_unavailable", 503),
            ("index_unverifiable", 503),
            ("capacity_limited", 503),
            ("backend_unavailable", 503),
            ("freshness_wait_timeout", 503),
            ("rebuild_required", 409),
            ("rebuild_refused", 409),
        ],
    )
    def test_canonical_failure_codes_map_to_exact_status(
        self,
        error: str,
        expected: int,
    ) -> None:
        # Returning the legacy blanket 503 made rebuild_required equal 503 and
        # failed its exact 409 assertion; restoration passed every case.
        envelope: dict[str, object] = {
            "ok": False,
            "error": error,
            "retryable": error not in {"rebuild_required", "rebuild_refused"},
        }

        actual = _search_response_status(envelope)

        assert actual == expected
        assert actual != 429


def _canonical_classification_facts(
    root: Path,
    *,
    current: bool,
    updating: bool = False,
) -> SearchAvailabilityRequestFacts:
    key = ReadinessSourceKey.from_root(root, "vault")
    return SearchAvailabilityRequestFacts(
        job_snapshot_before=(
            [
                {
                    "id": "updating-vault",
                    "state": "running",
                    "spec": {
                        "operation": "index",
                        "project_root": str(root.resolve()),
                        "source": "vault",
                        "mode": "incremental",
                    },
                }
            ]
            if updating
            else []
        ),
        root=root,
        source="vault",
        request_id="canonical-envelope-request",
        port=8766,
        readiness_snapshot=ReadinessRevisionSnapshot(
            key=key,
            published_generation="served",
            publication_revision=1,
            desired_generation="served" if current else "desired",
            controller_revision=1 if current else 2,
        ),
    )


def _canonical_searched(results: list[dict[str, object]]) -> dict[str, object]:
    return {
        "results": results,
        "summary": "search summary",
        "index_state": {
            "source": "vault",
            "indexed_count": 1,
            "indexed_target_root": "project",
            "requested_target_root": "project",
            "target_matches": True,
            "status": "available",
            "index_integrity": {"verdict": "consistent"},
        },
    }


def _matching_index_job(root: Path, *, mode: str = "incremental") -> dict[str, object]:
    return {
        "id": f"{mode}-vault-job",
        "state": "running",
        "spec": {
            "operation": "index",
            "project_root": str(root.resolve()),
            "source": "vault",
            "mode": mode,
        },
    }


def _availability_context(
    root: Path,
    *,
    evidence: CanonicalSearchEvidence,
    jobs: list[dict[str, object]] | None = None,
    request_id: str = "canonical-builder-request",
) -> SearchAvailabilityContext:
    return SearchAvailabilityContext(
        before_snapshot=[] if jobs is None else jobs,
        after_snapshot=[],
        requested_root=root,
        source="vault",
        request_id=request_id,
        index_state=cast("dict[str, object]", _canonical_searched([])["index_state"]),
        port=8766,
        canonical_evidence=evidence,
    )


def _assert_stable_failure_envelope(
    envelope: dict[str, object],
    *,
    error: str,
    retryable: bool,
    request_id: str,
    status: int,
) -> None:
    assert envelope["error"] == error
    assert envelope["retryable"] is retryable
    assert envelope["request_id"] == request_id
    assert isinstance(envelope["remediation"], str)
    assert envelope["remediation"]
    assert "results" not in envelope
    assert _search_response_status(envelope) == status
    assert _search_response_status(envelope) != 429
    readiness = cast("dict[str, object]", envelope["readiness"])
    sources = cast("list[dict[str, object]]", readiness["sources"])
    aggregate = cast("dict[str, object]", readiness["aggregate"])
    assert len(sources) == 1
    assert sources[0]["waits"] == []
    assert isinstance(sources[0]["evidence"], list)
    assert (
        len(cast("list[object]", sources[0]["evidence"])) <= MAX_SEARCH_EVIDENCE_ITEMS
    )
    assert aggregate["source_count"] == 1
    assert aggregate["absence_authority"] == "non_authoritative"


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (
            CanonicalSearchEvidence(rebuild_required=True),
            ("rebuild", "rebuild_required", False, 409),
        ),
        (
            CanonicalSearchEvidence(capacity_refused=True),
            ("incremental", "capacity_limited", True, 503),
        ),
    ],
    ids=["rebuild-required", "capacity-limited"],
)
def test_canonical_classifier_builds_stable_admission_failure_envelope(
    tmp_path: Path,
    evidence: CanonicalSearchEvidence,
    expected: tuple[str, str, bool, int],
) -> None:
    mode, error, retryable, status = expected
    root = (tmp_path / "project").resolve()
    request_id = f"{error}-request"

    classification = classify_search_response(
        {"results": []},
        _availability_context(
            root,
            evidence=evidence,
            jobs=[_matching_index_job(root, mode=mode)],
            request_id=request_id,
        ),
    )

    _assert_stable_failure_envelope(
        classification.response,
        error=error,
        retryable=retryable,
        request_id=request_id,
        status=status,
    )


def test_collection_disappearance_builds_stable_unavailable_envelope(
    tmp_path: Path,
) -> None:
    request_id = "collection-disappearance-request"
    missing = UnexpectedResponse(
        404,
        "Not Found",
        b'{"status":{"error":"Not found: Collection `vault_docs` doesn\'t exist!"}}',
        Headers(),
    )

    classification = classify_qdrant_collection_disappearance(
        missing,
        _availability_context(
            tmp_path,
            evidence=CanonicalSearchEvidence(),
            request_id=request_id,
        ),
    )

    assert classification is not None
    assert classification.availability_cause == "collection_missing"
    _assert_stable_failure_envelope(
        classification.response,
        error="index_unavailable",
        retryable=True,
        request_id=request_id,
        status=503,
    )


def test_usable_updating_nonempty_success_preserves_results_and_readiness(
    tmp_path: Path,
) -> None:
    # Removing success readiness attachment raised KeyError at the exact
    # readiness lookup below; restoration passed without changing useful hits.
    result: dict[str, object] = {
        "id": "useful-prior-generation",
        "score": 0.8,
    }
    classification = _classify_search_result(
        _canonical_searched([result]),
        _canonical_classification_facts(tmp_path, current=False, updating=True),
    )

    assert classification.status_code == 200
    assert classification.response["results"] == [result]
    readiness = cast("dict[str, object]", classification.response["readiness"])
    source = cast("list[dict[str, object]]", readiness["sources"])[0]
    assert source["availability"] == "usable"
    assert source["freshness"] == "updating"
    assert source["absence_authority"] == "non_authoritative"


def test_authoritative_empty_success_carries_current_readiness(tmp_path: Path) -> None:
    classification = _classify_search_result(
        _canonical_searched([]),
        _canonical_classification_facts(tmp_path, current=True),
    )

    assert classification.status_code == 200
    assert classification.response["results"] == []
    readiness = cast("dict[str, object]", classification.response["readiness"])
    aggregate = cast("dict[str, object]", readiness["aggregate"])
    assert aggregate["absence_authority"] == "authoritative"


def test_non_authoritative_empty_is_typed_failure_without_results(
    tmp_path: Path,
) -> None:
    # Disabling the non-authoritative-empty rewrite made the exact status
    # assertion fail with `assert 200 == 503` (exit 1); restoring it passed
    # (exit 0) and keeps the empty results suppressed.
    classification = _classify_search_result(
        _canonical_searched([]),
        _canonical_classification_facts(tmp_path, current=False),
    )

    assert classification.status_code == 503
    _assert_stable_failure_envelope(
        classification.response,
        error="index_unverifiable",
        retryable=False,
        request_id="canonical-envelope-request",
        status=503,
    )


class TestCompletedSearchClassificationSkip:
    """Availability classification refines retrieval, never a failed envelope."""

    def test_failed_envelope_carrying_results_is_not_classified(
        self,
        tmp_path: Path,
    ) -> None:
        """A failure that carries hits is still a failure, not a 200 to refine."""
        envelope: dict[str, object] = {
            "ok": False,
            "error": "local_store_locked",
            "message": "the local index is already open",
            "results": [{"id": "doc-1", "score": 0.75}],
        }

        classification = _classify_completed_search(
            envelope,
            _status_contract_request(tmp_path),
            _status_contract_facts(tmp_path),
            None,
            0.0,
        )

        assert classification is None
        assert "request_id" not in envelope


def test_mcp_preserves_structured_error_remediation() -> None:
    envelope = canonical_service_envelope(SEARCH_READINESS_SCENARIOS["unavailable"])

    result = _validated_search_result(envelope)

    assert result.model_dump(mode="json") == envelope
    assert result.error == "index_unavailable"
    assert result.remediation == envelope["remediation"]


class TestCombinedSearchBuildsNoAvailabilityFacts:
    """The fan-out has no single index, so it must never reach the classifier.

    ``SearchAvailabilityRequestFacts.source`` is typed to the three concrete
    corpora. Before this pin the route built the facts unconditionally and
    asserted that type with a cast, so a ``combined`` request put a value in
    the field that the field's own type excluded. It caused no visible failure
    only because every consumer re-tested for the fan-out separately, which
    makes the honest type the thing that has to be pinned.
    """

    def test_the_facts_refuse_every_source_no_index_job_can_carry(self) -> None:
        """Only a concrete corpus builds facts; the fan-out is refused.

        Proven able to fail: replacing the ``__post_init__`` membership test
        with ``pass`` lets ``COMBINED`` construct, and the ``pytest.raises``
        below fails with ``DID NOT RAISE``. Restored, it raises and the
        message names the offending source.
        """
        for source in INDEX_SOURCES:
            facts = SearchAvailabilityRequestFacts(
                job_snapshot_before=[],
                root=Path("C:/combined-carve-out"),
                # INDEX_SOURCES is the runtime twin of the field's Literal, so
                # the checker cannot narrow the loop variable to it.
                source=cast("IndexSource", source),
                request_id="concrete-source",
                port=None,
            )
            assert facts.source == source

        with pytest.raises(ValueError, match="combined fan-out has no single index"):
            SearchAvailabilityRequestFacts(
                job_snapshot_before=[],
                root=Path("C:/combined-carve-out"),
                source=cast("IndexSource", PublicSourceType.COMBINED.value),
                request_id="fan-out-source",
                port=None,
            )

    def test_a_combined_search_route_request_never_constructs_them(
        self,
        tmp_path: Path,
    ) -> None:
        """``POST /search {"type": "combined"}`` reaches retrieval, not the facts.

        Closed compute admission makes retrieval refuse on its first statement,
        so this drives the real route through the construction site without a
        model, a GPU, or an index. The facts are built before that refusal can
        happen, so building them for the fan-out raises out of the route and
        the single quiesce envelope below becomes a 500.

        Proven able to fail: restoring the unconditional construction the cast
        used to serve - building the facts before the fan-out is excluded -
        fails the status assertion below with ``assert 500 == 503``, the 500
        being the facts' own refusal escaping the route. Restored, the fan-out
        builds nothing and the quiesce envelope arrives intact.
        """
        from ..service import ServiceRegistry

        root = tmp_path / "vault"
        (root / ".vault").mkdir(parents=True)
        registry = ServiceRegistry()
        assert registry.quiesce_resources(timeout_seconds=0).achieved
        app = create_http_app(
            ServerRouteRuntime(
                token="combined-carve-out-token",
                registry=registry,
                port=8765,
            ),
            lifespan=None,
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/search",
                headers={"Authorization": "Bearer combined-carve-out-token"},
                json={
                    "query": "combined fan-out builds no availability facts",
                    "type": PublicSourceType.COMBINED.value,
                    "project_root": str(root),
                },
            )
        # Asserted before the body is parsed: a 500 carries Starlette's plain
        # "Internal Server Error" text, so parsing first would fail on a JSON
        # decode error instead of on the status this test is about.
        assert response.status_code == 503, response.text
        payload: dict[str, object] = response.json()
        assert payload["error"] == "quiesce_admission_closed"


class _CombinedRouteSearcher:
    def __init__(self, vault_results: list[SearchResult]) -> None:
        self._vault_results = vault_results

    def search_vault(self, *_args: object, **_kwargs: object) -> list[SearchResult]:
        return self._vault_results


class _CombinedRouteRegistry(ServiceRegistry):
    """Real route registry with deterministic, model-free domain seams."""

    def __init__(
        self,
        *,
        vault_count: int | Exception,
        code_count: int | Exception,
        document_count: int | Exception,
        vault_results: list[SearchResult] | None = None,
    ) -> None:
        super().__init__()
        self._counts = {
            "vault": vault_count,
            "code": code_count,
            "document": document_count,
        }
        self._searcher = _CombinedRouteSearcher(vault_results or [])

    def _count(self, source: str) -> int:
        value = self._counts[source]
        if isinstance(value, Exception):
            raise value
        return value

    def vault_doc_count(self, root: Path) -> int:
        del root
        return self._count("vault")

    def code_chunk_count(self, root: Path) -> int:
        del root
        return self._count("code")

    def document_chunk_count(self, root: Path) -> int:
        del root
        return self._count("document")

    @contextmanager
    def search_lease(self, root: Path) -> Generator[SimpleNamespace]:  # type: ignore[override]
        del root
        yield SimpleNamespace(searcher=self._searcher)


def _combined_http_response(
    tmp_path: Path, registry: ServiceRegistry
) -> tuple[int, dict[str, object], dict[str, str]]:
    root = tmp_path / "combined-vault"
    (root / ".vault").mkdir(parents=True)
    app = create_http_app(
        ServerRouteRuntime(token="combined-token", registry=registry, port=8765),
        lifespan=None,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/search",
            headers={"Authorization": "Bearer combined-token"},
            json={
                "query": "combined readiness contract",
                "type": PublicSourceType.COMBINED.value,
                "project_root": str(root),
            },
        )
    return response.status_code, response.json(), dict(response.headers)


def test_combined_http_retains_useful_results_and_failed_constituent(
    tmp_path: Path,
) -> None:
    """The real route serializes classification instead of bypassing it.

    Mutation evidence: temporarily returning ``None`` instead of ``combined``
    from combined dispatch made the exact ``partial`` lookup fail with
    ``KeyError`` (exit 1); restoration passed (exit 0). Filtering ``domains``
    to successful legs then failed the exact three-source tuple assertion
    because ``code`` disappeared (exit 1); restoration passed (exit 0).
    """
    registry = _CombinedRouteRegistry(
        vault_count=1,
        code_count=RuntimeError("code collection unavailable"),
        document_count=0,
        vault_results=[SearchResult("v", "v.md", "Vault", 0.9, "body", "vault")],
    )

    status, payload, _headers = _combined_http_response(tmp_path, registry)

    assert status == 200
    assert [
        item["id"] for item in cast("list[dict[str, object]]", payload["results"])
    ] == ["v"]
    assert payload["partial"] is True
    domains = cast("dict[str, dict[str, object]]", payload["domains"])
    assert tuple(domains) == ("vault", "code", "document")
    assert domains["vault"]["ok"] is True
    assert domains["code"]["ok"] is False
    assert domains["code"]["error_kind"] == "RuntimeError"
    readiness = cast("dict[str, object]", payload["readiness"])
    sources = cast("list[dict[str, object]]", readiness["sources"])
    assert [source["source"] for source in sources] == ["vault", "code", "document"]
    assert cast("dict[str, object]", readiness["aggregate"])["source_count"] == 3


def test_combined_http_empty_partial_is_typed_failure_without_results(
    tmp_path: Path,
) -> None:
    """A failed constituent cannot be hidden behind an empty success.

    Mutation evidence: temporarily removing ``combined.partial`` from the
    empty-authority guard made the exact status assertion report 200 instead
    of 503 (exit 1); restoration passed (exit 0). Removing result suppression
    failed the exact ``results`` absence assertion (exit 1), and adding a
    speculative final ``Retry-After: 1`` failed its exact header absence
    assertion (exit 1); each restoration passed (exit 0).
    """
    registry = _CombinedRouteRegistry(
        vault_count=0,
        code_count=RuntimeError("code collection unavailable"),
        document_count=0,
    )

    status, payload, headers = _combined_http_response(tmp_path, registry)

    assert status == 503
    assert payload["ok"] is False
    assert payload["error"] == "index_unverifiable"
    assert "results" not in payload
    assert payload["remediation"] is not None
    assert "retry-after" not in headers
    assert (
        cast("dict[str, dict[str, object]]", payload["domains"])["code"]["ok"] is False
    )
    assert cast("dict[str, object]", payload["readiness"])["aggregate"]


def test_combined_http_complete_failure_has_canonical_retry_and_remediation(
    tmp_path: Path,
) -> None:
    """Complete failure retains all constituents and suppresses all results.

    Mutation evidence: removing the complete-failure result suppression
    failed the exact ``results`` absence assertion (exit 1); restoration
    passed (exit 0). Removing the document constituent from route serialization
    failed the exact ordered domain-key assertion (exit 1); restoration passed
    (exit 0).
    """
    registry = _CombinedRouteRegistry(
        vault_count=RuntimeError("vault unavailable"),
        code_count=RuntimeError("code unavailable"),
        document_count=RuntimeError("document unavailable"),
    )

    status, payload, headers = _combined_http_response(tmp_path, registry)

    assert status == 503
    assert payload["ok"] is False
    assert payload["error"] == "combined_search_failed"
    assert payload["retryable"] is False
    assert payload["remediation"] is not None
    assert "results" not in payload
    assert "retry-after" not in headers
    domains = cast("dict[str, dict[str, object]]", payload["domains"])
    assert tuple(domains) == ("vault", "code", "document")
    assert all(domain["ok"] is False for domain in domains.values())
    readiness = cast("dict[str, object]", payload["readiness"])
    assert cast("dict[str, object]", readiness["aggregate"])["source_count"] == 3
