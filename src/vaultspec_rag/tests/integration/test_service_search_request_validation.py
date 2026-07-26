"""Integration tests for ``POST /search`` request validation.

Each test drives a real running service over HTTP and authenticates with the
token that service generated for itself at startup, read back from its own
``/health``. Nothing about the request path is substituted.

The refusals asserted here are ordered: an empty query is refused before the
project root is resolved, and both refusals carry the same status and the same
error code. Only the message distinguishes them, so that is what each test
pins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from ._helpers import _poll_health

if TYPE_CHECKING:
    from pathlib import Path

_NONEXISTENT_ROOT = "/nonexistent-root-for-request-validation"


def _post_search(port: int, query: str) -> httpx.Response:
    """Send one search request carrying *query* and an unresolvable root."""
    token = _poll_health(port)["service_token"]
    return httpx.post(
        f"http://127.0.0.1:{port}/search",
        json={
            "type": "code",
            "query": query,
            "top_k": 5,
            "project_root": _NONEXISTENT_ROOT,
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )


@pytest.mark.integration
class TestEmptyQueryRejected:
    """The empty-query guard fires before the root is resolved."""

    def test_empty_query_is_rejected_as_empty(self, live_service: tuple[int, Path]):
        """An empty query is refused on emptiness, not on something later.

        The request also carries a nonexistent root, which the very next guard
        refuses with the same status and the same ``bad_request`` code.
        Asserting only those two passes whichever guard fired, so the branch is
        pinned by its own message.

        Proven able to fail against this real service: dropping the
        empty-query guard lets the request reach root resolution, which
        answers ``not a vaultspec project (no .vault/ directory)`` - the
        message assertion fails while status and error code still read
        400 / bad_request. Restored, it passes.
        """
        port, _status_dir = live_service
        resp = _post_search(port, "")
        assert resp.status_code == 400
        assert resp.json()["error"] == "bad_request"
        assert "query is empty" in resp.json()["message"]

    def test_whitespace_query_is_rejected_as_empty(
        self, live_service: tuple[int, Path]
    ):
        """Whitespace is empty too, and is refused by the same branch.

        Proven able to fail: the same mutation as the sibling test - the
        message assertion is what distinguishes this refusal from the root one
        that would otherwise absorb it. Restored, it passes.
        """
        port, _status_dir = live_service
        resp = _post_search(port, "   \t  ")
        assert resp.status_code == 400
        assert "query is empty" in resp.json()["message"]

    def test_filter_only_query_is_not_empty(self, live_service: tuple[int, Path]):
        """A bare filter token is real query text and clears the guard."""
        port, _status_dir = live_service
        resp = _post_search(port, "lang:python")
        assert resp.status_code == 400
        # It got past the empty-query guard to root resolution.
        assert "query is empty" not in resp.json()["message"]
