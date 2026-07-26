"""Unit tests for the search-quality backlog fixes.

Three independent fixes surfaced by the server-mode quality audit:
- vault result paths are project-root-relative (carry the docs prefix);
- merging two small chunks never cross-pairs a class tail's class_name
  with an adjacent module-level function's function_name;
- an empty/whitespace search query is rejected, while a filter-only
  query still proceeds.
"""

import os
from typing import ClassVar, cast

import httpx
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from .. import server as _m
from ..indexer._ast_chunker import ASTChunker
from ..search._searcher import _join_doc_path
from ..server._routes import ROUTES

Chunk = tuple[str, int, int, str | None, str | None, str | None]


class TestVaultDocPath:
    pytestmark: ClassVar = [pytest.mark.unit]

    def test_prepends_docs_prefix(self):
        assert _join_doc_path(".vault", "research/foo.md") == ".vault/research/foo.md"

    def test_idempotent_when_prefix_present(self):
        assert (
            _join_doc_path(".vault", ".vault/research/foo.md")
            == ".vault/research/foo.md"
        )

    def test_normalises_backslashes(self):
        assert _join_doc_path(".vault", "research\\foo.md") == ".vault/research/foo.md"

    def test_empty_prefix_passes_through(self):
        assert _join_doc_path("", "research/foo.md") == "research/foo.md"

    def test_result_still_ends_with_extension(self):
        assert _join_doc_path(".vault", "adr/x.md").endswith(".md")


class TestMergeKeepsIdentityCoherent:
    pytestmark: ClassVar = [pytest.mark.unit]

    def test_class_tail_does_not_adopt_sibling_function(self):
        # A class-tail chunk (class set, no function) merged with an
        # adjacent module-level function chunk must NOT emerge claiming
        # that function as a method of the class.
        chunker = ASTChunker(chunk_size=200)
        chunks: list[Chunk] = [
            ("class Foo: pass", 1, 1, "class_definition", None, "Foo"),
            ("def helper(): pass", 2, 2, "function_definition", "helper", None),
        ]
        merged = chunker._merge_small(chunks)
        assert len(merged) == 1
        _text, _ls, _le, _nt, fn, cls = merged[0]
        assert cls == "Foo"
        assert fn is None, "class tail must not adopt the sibling function as a method"

    def test_real_method_pair_survives(self):
        # A genuine method chunk (both names from one source) keeps both.
        chunker = ASTChunker(chunk_size=200)
        chunks: list[Chunk] = [
            ("def m(self): pass", 1, 1, "function_definition", "m", "Bar"),
            ("x = 1", 2, 2, None, None, None),
        ]
        merged = chunker._merge_small(chunks)
        assert len(merged) == 1
        _text, _ls, _le, _nt, fn, cls = merged[0]
        assert (fn, cls) == ("m", "Bar")

    def test_structureless_prev_takes_chunk_identity(self):
        chunker = ASTChunker(chunk_size=200)
        chunks: list[Chunk] = [
            ("# comment", 1, 1, None, None, None),
            ("def g(): pass", 2, 2, "function_definition", "g", None),
        ]
        merged = chunker._merge_small(chunks)
        assert len(merged) == 1
        _text, _ls, _le, _nt, fn, cls = merged[0]
        assert (fn, cls) == ("g", None)


@pytest.fixture
def _search_app(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[httpx.Client, str]:
    """Serve production's own route table over real ASGI, with a real token.

    ``ROUTES`` is the production route table and the transport is Starlette's
    own, so every assertion below is decided by production request handling.

    The token is a precondition, not a substitute for anything under test: the
    auth gate fails closed on an unset token, so a request could not reach the
    validation being asserted without one. Assigning it is what
    ``service_lifespan`` does at startup, and the value assigned here is
    production-legal. Driving the real lifespan instead would start a daemon,
    claim the machine singleton and load the models - none of which any
    assertion here depends on.
    """
    monkeypatch.setattr(_m, "_SERVICE_TOKEN", "test-token-q")
    client = cast("httpx.Client", TestClient(Starlette(routes=ROUTES)))
    return client, "test-token-q"


class TestEmptyQueryRejected:
    pytestmark: ClassVar = [pytest.mark.unit]

    def _post(self, client: httpx.Client, token: str, query: str) -> httpx.Response:
        return client.post(
            "/search",
            json={
                "type": "code",
                "query": query,
                "top_k": 5,
                "project_root": os.path.abspath(os.path.join(os.sep, "nonexistent")),
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_empty_query_is_rejected_as_empty(
        self, _search_app: tuple[httpx.Client, str]
    ):
        """An empty query is refused on emptiness, not on something later.

        The request also carries a nonexistent root, which the very next
        guard refuses with the same status and the same ``bad_request``
        code. Asserting only those two passes whichever guard fired, so
        the branch is pinned by its own message.

        Proven able to fail: dropping the empty-query guard lets the
        request reach root resolution, which refuses it identically apart
        from the message - failing the message assertion while status and
        error code still read 400 / bad_request. Restored, it passes.
        """
        client, token = _search_app
        resp = self._post(client, token, "")
        assert resp.status_code == 400
        assert resp.json()["error"] == "bad_request"
        assert "query is empty" in resp.json()["message"]

    def test_whitespace_query_is_rejected_as_empty(
        self, _search_app: tuple[httpx.Client, str]
    ):
        """Whitespace is empty too, and is refused by the same branch.

        Proven able to fail: the same mutation as the sibling test - the
        message assertion is what distinguishes this refusal from the root
        one that would otherwise absorb it. Restored, it passes.
        """
        client, token = _search_app
        resp = self._post(client, token, "   \t  ")
        assert resp.status_code == 400
        assert "query is empty" in resp.json()["message"]

    def test_filter_only_query_is_not_empty(
        self, _search_app: tuple[httpx.Client, str]
    ):
        # "lang:python" is non-empty raw text: it must pass the empty
        # guard (and then fail later on the bogus root, not on emptiness).
        client, token = _search_app
        resp = self._post(client, token, "lang:python")
        assert resp.status_code == 400
        # It got past the empty-query guard to root resolution.
        assert "query is empty" not in resp.json()["message"]
