"""Strict search-response tests for the shared HTTP and MCP consumers."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from starlette.testclient import TestClient

from .._source_types import INDEX_SOURCES, PublicSourceType
from .._store_locks import VaultStoreLockedError
from ..config._settings import get_config, reset_config
from ..mcp._tools import _search_envelope_or_raise
from ..registry import get_registry, reset_registry
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
    _search_response_status,
)
from ..service import RegistryFullError, ServiceRegistry
from ..serviceclient._transport import _search_response_envelope, _try_http_search

if TYPE_CHECKING:
    from .._source_types import IndexSource

pytestmark = [pytest.mark.unit]


def _http_search(port: int) -> dict[str, object] | None:
    return _try_http_search("response contract", "vault", 3, port, "")


def test_valid_search_envelope_is_unchanged() -> None:
    expected: dict[str, object] = {
        "results": [{"id": "doc-1", "score": 0.75}],
        "summary": "one result",
    }
    result = _search_response_envelope(expected, 8766)

    assert result is expected
    assert _search_envelope_or_raise(result) is result


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


@pytest.mark.parametrize(
    "result",
    [[], {}, "legacy", None, {"summary": "missing"}, {"results": "legacy"}],
)
def test_mcp_rejects_malformed_search_envelopes(result: object) -> None:
    with pytest.raises(RuntimeError, match=r"^invalid_service_response:"):
        _search_envelope_or_raise(result)


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
    """An empty runtime-owned vault still answers when the global registry closed.

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

        assert response.status_code == 200, response.text
        assert response.json()["results"] == []
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
    envelope: dict[str, object] = {
        "ok": False,
        "error": "index_unavailable",
        "message": "The vault index is changing.",
        "remediation": ["Inspect the matching job.", "Retry after convergence."],
    }

    with pytest.raises(RuntimeError) as raised:
        _search_envelope_or_raise(envelope)

    assert str(raised.value) == (
        "index_unavailable: The vault index is changing. Remediation: "
        "Inspect the matching job. | Retry after convergence."
    )


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
