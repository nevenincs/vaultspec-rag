"""MCP conformance: the narrowed search surface, its annotations, legible errors.

Introspects the real FastMCP instance (no mocks) to assert the surface decided
by the ``mcp-search-scope`` ADR - exactly the search, index-refresh, and
read-only retrieval tools, carrying spec-correct 2025-11-25 annotations and
titles - and exercises the transport's legible-error contract against a real
local HTTP server returning an empty-body 404 (the opaque failure the grounding
research recorded).
"""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest

from ..mcp._mcp import mcp
from ..serviceclient._transport import _do_http_call

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mcp.types import Tool

pytestmark = [pytest.mark.unit]

_EXPECTED_TOOLS = {
    "search_vault",
    "search_codebase",
    "get_code_file",
    "reindex_vault",
    "reindex_codebase",
}
_REMOVED_TOOLS = {
    "get_index_status",
    "list_projects",
    "evict_project",
    "get_watcher_state",
    "start_watcher",
    "stop_watcher",
    "get_service_state",
    "survey_storage",
    "get_logs",
    "get_jobs",
    "reconfigure_watcher",
}
_READ_ONLY_TOOLS = {"search_vault", "search_codebase", "get_code_file"}
_REFRESH_TOOLS = {"reindex_vault", "reindex_codebase"}


def _tools() -> list[Tool]:
    return asyncio.run(mcp.list_tools())


class TestNarrowedSurface:
    """The MCP surface is exactly search + index-refresh + read-only retrieval."""

    def test_surface_is_exactly_the_search_and_refresh_tools(self) -> None:
        assert {t.name for t in _tools()} == _EXPECTED_TOOLS

    def test_no_admin_or_lifecycle_tool_survives(self) -> None:
        assert {t.name for t in _tools()}.isdisjoint(_REMOVED_TOOLS)

    def test_read_only_tools_carry_the_read_only_hint(self) -> None:
        for tool in _tools():
            if tool.name in _READ_ONLY_TOOLS:
                assert tool.annotations is not None
                assert tool.annotations.readOnlyHint is True
                assert tool.annotations.idempotentHint is True
                assert tool.annotations.openWorldHint is False

    def test_refresh_tools_are_not_read_only(self) -> None:
        for tool in _tools():
            if tool.name in _REFRESH_TOOLS:
                assert tool.annotations is not None
                assert tool.annotations.readOnlyHint is False

    def test_every_tool_has_a_display_title(self) -> None:
        for tool in _tools():
            assert tool.title, f"tool {tool.name} has no title"

    def test_search_default_top_k_matches_cli_default(self) -> None:
        search_vault = next(t for t in _tools() if t.name == "search_vault")
        props = search_vault.inputSchema.get("properties", {})
        assert props["top_k"].get("default") == 10

    def test_search_tools_declare_a_result_output_schema(self) -> None:
        for tool in _tools():
            if tool.name in {"search_vault", "search_codebase"}:
                assert tool.outputSchema is not None, tool.name
                props = tool.outputSchema.get("properties", {})
                assert "results" in props


class _EmptyBody404Handler(BaseHTTPRequestHandler):
    """A server that answers every request with a bodyless 404."""

    def _respond_404(self) -> None:
        self.send_response(404)
        self.end_headers()

    def do_GET(self) -> None:  # stdlib handler contract
        self._respond_404()

    def do_POST(self) -> None:  # stdlib handler contract
        self._respond_404()

    def log_message(self, format: str, *args: object) -> None:  # noqa: ARG002
        return


@pytest.fixture
def empty_404_port() -> Iterator[int]:
    """Run a real local server that returns an empty-body 404 on any path."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EmptyBody404Handler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()


class TestLegibleTransportError:
    """An empty-body HTTP error is reported legibly, not as a bare ``404:``."""

    def test_empty_body_404_carries_a_legible_message(
        self, empty_404_port: int
    ) -> None:
        result = _do_http_call(empty_404_port, "/service-state", None)
        assert result is not None
        assert result.get("ok") is False
        assert result.get("http_code") == 404
        message = str(result.get("message", ""))
        assert "404" in message
        assert "empty response body" in message
        assert "server status" in message  # actionable remediation
