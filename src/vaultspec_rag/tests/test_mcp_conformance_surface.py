"""MCP conformance: closed-domain adapters, annotations, and legible errors.

Introspects the real FastMCP instance (no mocks) to assert the surface decided
for the narrowed surface - exactly the search, index-refresh, and
read-only retrieval tools, carrying spec-correct 2025-11-25 annotations and
titles - and exercises the transport's legible-error contract against a real
local HTTP server returning an empty-body 404 (the opaque failure the grounding
research recorded). The dispatch contract is covered the same way: a recording
stand-in daemon proves what an omitting caller actually puts on the wire.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING, Any, cast

import pytest

from ..mcp._mcp import mcp
from ..serviceclient._transport import _do_http_call
from ._http_stubs import QuietHandler

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from mcp.types import Tool

pytestmark = [pytest.mark.unit]

_EXPECTED_TOOLS = {
    "search_vault",
    "search_codebase",
    "search_documents",
    "search_combined",
    "get_code_file",
    "reindex_vault",
    "reindex_codebase",
    "reindex_documents",
    "reindex_all",
    "clean_documents",
    "clean_all",
    "get_index_status",
}
_REMOVED_TOOLS = {
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
_READ_ONLY_TOOLS = {
    "search_vault",
    "search_codebase",
    "search_documents",
    "search_combined",
    "get_code_file",
    "get_index_status",
}
_REFRESH_TOOLS = {
    "reindex_vault",
    "reindex_codebase",
    "reindex_documents",
    "reindex_all",
}
_CLEAN_TOOLS = {"clean_documents", "clean_all"}


def _tools() -> list[Tool]:
    return asyncio.run(mcp.list_tools())


class TestNarrowedSurface:
    """The MCP surface exhaustively covers the public source domains."""

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

    def test_refresh_tools_are_non_destructive_and_idempotent(self) -> None:
        for tool in _tools():
            if tool.name in _REFRESH_TOOLS:
                assert tool.annotations is not None
                assert tool.annotations.readOnlyHint is False
                assert tool.annotations.destructiveHint is False
                assert tool.annotations.idempotentHint is True
                assert tool.annotations.openWorldHint is False

    def test_clean_tools_are_explicitly_destructive_and_idempotent(self) -> None:
        for tool in _tools():
            if tool.name in _CLEAN_TOOLS:
                assert tool.annotations is not None
                assert tool.annotations.readOnlyHint is False
                assert tool.annotations.destructiveHint is True
                assert tool.annotations.idempotentHint is True
                assert tool.annotations.openWorldHint is False

    def test_refresh_tools_expose_no_destructive_clean_input(self) -> None:
        for tool in _tools():
            if tool.name in _REFRESH_TOOLS:
                props = tool.inputSchema.get("properties", {})
                assert "clean" not in props, (
                    f"{tool.name} exposes the destructive clean rebuild; it must be "
                    "CLI-only"
                )

    def test_every_tool_has_a_display_title(self) -> None:
        for tool in _tools():
            assert tool.title, f"tool {tool.name} has no title"

    def test_search_default_top_k_matches_cli_default(self) -> None:
        from ..mcp._tools import _DEFAULT_TOP_K

        # The MCP default tracks the CLI --max-results default (10). Assert the
        # source constant and both published schemas agree, so a drift in either
        # the constant or the introspected schema fails here rather than a magic
        # literal that cannot catch the divergence it claims to guard.
        assert _DEFAULT_TOP_K == 10
        for name in (
            "search_vault",
            "search_codebase",
            "search_documents",
            "search_combined",
        ):
            tool = next(t for t in _tools() if t.name == name)
            props = tool.inputSchema.get("properties", {})
            assert props["top_k"].get("default") == _DEFAULT_TOP_K

    def test_search_tools_declare_a_result_output_schema(self) -> None:
        # The declared outputSchema must reflect the SearchResults model the
        # tools return (results + summary), not merely be present.
        from ..mcp._tools import SearchResults

        model_props = set(SearchResults.model_json_schema().get("properties", {}))
        for tool in _tools():
            if tool.name in {
                "search_vault",
                "search_codebase",
                "search_documents",
                "search_combined",
            }:
                assert tool.outputSchema is not None, tool.name
                props = set(tool.outputSchema.get("properties", {}))
                assert {"results", "summary"} <= props, tool.name
                assert {"results", "summary"} <= model_props


class _EmptyBody404Handler(QuietHandler):
    """A server that answers every request with a bodyless 404."""

    def _respond_404(self) -> None:
        self.send_response(404)
        self.end_headers()

    def do_GET(self) -> None:  # stdlib handler contract
        self._respond_404()

    def do_POST(self) -> None:  # stdlib handler contract
        self._respond_404()


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


@pytest.fixture
def recorded_requests(isolated_singleton_dirs: Path) -> Iterator[list[dict[str, Any]]]:
    """Publish a real recording daemon and yield the bodies it receives.

    A stand-in server on a loopback port answers every POST with a valid search
    envelope and appends the decoded request body, so a test can assert on the
    exact payload the MCP put on the wire rather than on an intercepted call.
    Writing the discovery file into the relocated status dir is what makes the
    tools resolve this port instead of the operator's real service.
    """
    received: list[dict[str, Any]] = []

    class _Recorder(QuietHandler):
        def do_POST(self) -> None:  # stdlib handler contract
            length = int(self.headers.get("Content-Length") or 0)
            decoded = cast("dict[str, Any]", json.loads(self.rfile.read(length)))
            decoded["_path"] = self.path
            received.append(decoded)
            body = json.dumps({"results": [], "summary": "recorded"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    (isolated_singleton_dirs / "service.json").write_text(
        json.dumps({"pid": os.getpid(), "port": port, "service_token": ""}),
        encoding="utf-8",
    )
    try:
        yield received
    finally:
        server.shutdown()
        server.server_close()


class TestOptionalProjectRootReachesTheRouteConcrete:
    """An omitted project root travels as a real root, never as the empty string.

    The daemon is multi-root and requires ``project_root`` on every request, so
    the tool schema may only advertise the argument as optional if an omitting
    caller still sends a concrete root. Forwarding the empty string instead is
    the rejected request this guards; the working directory is the honest
    default because the host launches one stdio server per project.
    """

    def test_omitted_project_root_is_sent_as_the_process_cwd(
        self,
        recorded_requests: list[dict[str, Any]],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ..mcp._tools import search_codebase

        monkeypatch.chdir(tmp_path)

        asyncio.run(search_codebase("anything"))

        assert [r["_path"] for r in recorded_requests] == ["/search"]
        assert recorded_requests[0]["project_root"] == str(tmp_path.resolve())

    def test_omitted_project_root_reaches_the_reindex_route_too(
        self,
        recorded_requests: list[dict[str, Any]],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The fill covers the index family, not just search."""
        from ..mcp._tools import reindex_vault

        monkeypatch.chdir(tmp_path)

        asyncio.run(reindex_vault())

        assert [r["_path"] for r in recorded_requests] == ["/reindex"]
        assert recorded_requests[0]["project_root"] == str(tmp_path.resolve())

    def test_explicit_project_root_is_not_replaced_by_the_cwd(
        self,
        recorded_requests: list[dict[str, Any]],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A caller who names a root gets that root, not the one it ran from."""
        from ..mcp._tools import search_codebase

        monkeypatch.chdir(tmp_path)
        explicit = str(tmp_path / "elsewhere")

        asyncio.run(search_codebase("anything", project_root=explicit))

        assert recorded_requests[0]["project_root"] == explicit
        assert recorded_requests[0]["project_root"] != str(tmp_path.resolve())


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
