"""Service capability projections must describe the configured vector engine."""

from __future__ import annotations

import pytest

from ..capabilities import BackendCapabilities, backend_capabilities_dict
from ..server._models import SearchResponse

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("url", "expected"),
    [("", "qdrant-local"), ("http://127.0.0.1:8765", "qdrant-server")],
)
def test_service_capabilities_follow_backend(
    monkeypatch: pytest.MonkeyPatch, url: str, expected: str
) -> None:
    """Health/status and response defaults agree for both supported engines.

    Mutation proof: forcing the configured backend to local fails the managed
    server assertion; restoring the configured choice passes.
    """
    monkeypatch.setenv("VAULTSPEC_RAG_QDRANT_URL", url)
    assert backend_capabilities_dict()["backend"] == expected
    response = SearchResponse(results=[], summary="No results")
    assert response.backend_capabilities.backend == expected
    # Both concrete values also survive the public response schema.
    assert BackendCapabilities.model_validate({"backend": expected}).backend == expected
