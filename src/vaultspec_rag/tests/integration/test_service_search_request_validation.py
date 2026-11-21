"""Integration tests for ``POST /search`` request validation.

Each test drives a real running service over HTTP and authenticates with the
token that service generated for itself at startup, read back from its own
``/health``. Nothing about the request path is substituted.

The refusals asserted here are ordered: an empty query is refused as a bad
request before the project root is resolved, and a root that does not exist is
refused next as gone. Each test pins the branch that fired by its status, its
error code and its message.
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


# The live-service fixture loads its own model stack on the same card.
@pytest.mark.subprocess_gpu
class TestEmptyQueryRejected:
    """The empty-query guard fires before the root is resolved."""

    def test_empty_query_is_rejected_as_empty(self, live_service: tuple[int, Path]):
        """An empty query is refused on emptiness, not on something later.

        The request also carries a nonexistent root, which the very next guard
        refuses as gone. Dropping the empty-query guard lets the request reach
        that guard, and the status assertion then reads 410, not 400.
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
        """A bare filter token is real query text and clears the guard.

        Clearing it reaches root resolution, which refuses the nonexistent root
        as gone. A guard that treated the token as empty would answer 400
        ``bad_request`` instead.
        """
        port, _status_dir = live_service
        resp = _post_search(port, "lang:python")
        assert resp.status_code == 410, resp.text
        assert resp.json()["error"] == "root_missing"
        assert "query is empty" not in resp.json()["message"]
