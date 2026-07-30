"""MCP conformance: closed-domain adapters, annotations, and legible errors.

Introspects the real MCPServer instance (no mocks) to assert the surface decided
for the narrowed surface - exactly the search, index-refresh, and
read-only retrieval tools, carrying spec-correct 2026-07-28 annotations and
titles - and exercises the transport's legible-error contract against a real
local HTTP server returning an empty-body 404 (the opaque failure the grounding
research recorded).
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest
import uvicorn
from mcp import Client, UriTemplate
from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError

from ..mcp._mcp import mcp
from ..serviceclient._compat import local_package_version
from ..serviceclient._transport import _do_http_call
from ._http_stubs import QuietHandler
from ._ports import free_loopback_port

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


@pytest.fixture
def service_routes() -> Iterator[int]:
    """Serve the production route table over a live loopback Uvicorn server."""
    from ..server import ServerRouteRuntime, create_http_app
    from ..service import ServiceRegistry
    from ._cli_helpers import _CONTRACT_SERVICE_TOKEN

    port = free_loopback_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_http_app(
                ServerRouteRuntime(
                    token=_CONTRACT_SERVICE_TOKEN,
                    registry=ServiceRegistry(),
                    port=port,
                ),
                lifespan=None,
            ),
            host="127.0.0.1",
            port=port,
            log_config=None,
            access_log=False,
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()


def _workspace(path: Path) -> Path:
    """Create the smallest enrolled workspace accepted by the root resolver."""
    (path / ".vault").mkdir(parents=True)
    (path / ".vaultspec").mkdir()
    return path


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
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.idempotent_hint is True
                assert tool.annotations.open_world_hint is False

    def test_refresh_tools_are_non_destructive_and_idempotent(self) -> None:
        for tool in _tools():
            if tool.name in _REFRESH_TOOLS:
                assert tool.annotations is not None
                assert tool.annotations.read_only_hint is False
                assert tool.annotations.destructive_hint is False
                assert tool.annotations.idempotent_hint is True
                assert tool.annotations.open_world_hint is False

    def test_clean_tools_are_explicitly_destructive_and_idempotent(self) -> None:
        for tool in _tools():
            if tool.name in _CLEAN_TOOLS:
                assert tool.annotations is not None
                assert tool.annotations.read_only_hint is False
                assert tool.annotations.destructive_hint is True
                assert tool.annotations.idempotent_hint is True
                assert tool.annotations.open_world_hint is False

    def test_refresh_tools_expose_no_destructive_clean_input(self) -> None:
        for tool in _tools():
            if tool.name in _REFRESH_TOOLS:
                props = tool.input_schema.get("properties", {})
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
            props = tool.input_schema.get("properties", {})
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
                assert tool.output_schema is not None, tool.name
                props = set(tool.output_schema.get("properties", {}))
                assert {"results", "summary"} <= props, tool.name
                assert {"results", "summary"} <= model_props


class TestProjectRootWireContract:
    """Optional MCP roots are concrete on the daemon wire, never a 400 input."""

    def test_omitted_root_uses_env_and_explicit_root_wins(
        self,
        tmp_path: Path,
        service_routes: int,
    ) -> None:
        """Exercise MCP discovery, transport, and the production code-file route.

        The two workspaces contain different files at the same relative path.
        The omitted call can return the environment workspace's content only if
        the adapter resolves and serializes that root; the explicit call can
        return the other content only if it takes precedence over the env var.

        Mutation-proved in both halves against the adapter's root resolver.
        Returning the caller's value verbatim - the empty-string fallback this
        contract replaced - fails the omitted call with the route's own
        ``bad_request``, which is the 400 a blank root earns. Ranking the env
        var above the argument fails the explicit assertion below with the
        environment workspace's content. Neither substitution is a wire
        assertion, so do not reduce this to one call.
        """
        from ..config._types import EnvVar
        from ..mcp._tools import get_code_file
        from ._cli_helpers import _running_service_record

        env_root = _workspace(tmp_path / "environment-project").resolve()
        explicit_root = _workspace(tmp_path / "explicit-project").resolve()
        relative_path = "root-proof.py"
        (env_root / relative_path).write_text("environment root\n", encoding="utf-8")
        (explicit_root / relative_path).write_text("explicit root\n", encoding="utf-8")
        previous_root = os.environ.get(EnvVar.RAG_ROOT.value)
        os.environ[EnvVar.RAG_ROOT.value] = str(env_root)
        try:
            with _running_service_record(tmp_path / "status", service_routes):
                omitted = asyncio.run(get_code_file(relative_path))
                explicit = asyncio.run(
                    get_code_file(relative_path, project_root=str(explicit_root))
                )
        finally:
            if previous_root is None:
                os.environ.pop(EnvVar.RAG_ROOT.value, None)
            else:
                os.environ[EnvVar.RAG_ROOT.value] = previous_root

        assert omitted == "environment root\n"
        assert explicit == "explicit root\n"


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


class TestVaultResourceTemplate:
    """The document resource addresses real stems, and refuses to escape."""

    def _template(self) -> str:
        templates = asyncio.run(mcp.list_resource_templates())
        return next(
            t.uri_template for t in templates if t.uri_template.startswith("vault://")
        )

    def test_a_nested_document_stem_matches_the_template(self) -> None:
        """Every real stem carries its directory, so the template must keep it.

        Plain expansion stops at the path separator and captures nothing here,
        which silently unaddresses the whole resource; reserved expansion is
        what makes a directory-qualified stem reachable at all.
        """
        match = UriTemplate.parse(self._template()).match("vault://adr/overview")

        assert match == {"doc_id": "adr/overview"}

    def test_a_bare_stem_still_matches(self) -> None:
        match = UriTemplate.parse(self._template()).match("vault://overview")

        assert match == {"doc_id": "overview"}

    @pytest.mark.parametrize("uri", ["vault://../../etc/passwd", "vault://a%00b"])
    def test_an_escaping_stem_never_reaches_the_handler(self, uri: str) -> None:
        """Reserved expansion admits separators, so refusal is load-bearing.

        The handler forwards its stem to the daemon's document route, so a
        traversal or an embedded null that got this far would be forwarded
        too. Refusal must land before the handler, and the distinct exception
        types are what prove which side of it the read stopped on:
        ``ResourceNotFoundError`` is refusal at the template, while a stem
        that does reach the handler surfaces the handler's own
        ``ResourceError``.
        """
        with pytest.raises(ResourceNotFoundError):
            asyncio.run(mcp.read_resource(uri))

    def test_a_legitimate_nested_stem_does_reach_the_handler(self) -> None:
        """The counterpart that keeps the refusal test honest.

        Without this, a template that matched nothing at all would satisfy the
        refusal assertions above while leaving the resource unreachable.
        """
        with pytest.raises(ResourceError) as excinfo:
            asyncio.run(mcp.read_resource("vault://adr/overview"))

        assert not isinstance(excinfo.value, ResourceNotFoundError)


class TestServerIdentity:
    """Every result identifies the build that answered it."""

    def test_the_advertised_version_is_this_install(self) -> None:
        async def _server_info() -> object:
            async with Client(mcp) as client:
                result = await client.list_tools()
                assert result.meta is not None, "the result carried no _meta at all"
                return result.meta.get("io.modelcontextprotocol/serverInfo")

        assert asyncio.run(_server_info()) == {
            "name": "VaultSpec Search",
            "version": local_package_version(),
        }


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
