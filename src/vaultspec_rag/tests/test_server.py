"""Unit tests for the MCP server module."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import typing
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    import logging
    from collections.abc import Coroutine, Iterator
    from pathlib import Path

    import httpx

from ..capabilities import BackendCapabilities
from ..config._settings import reset_config
from ..config._types import EnvVar
from ..mcp._mcp import mcp
from ..mcp._resources import analyze_feature
from ..server import (
    HealthResponse,
    IndexResponse,
    IndexStatus,
    SearchResponse,
    SearchResultItem,
    ServerRouteRuntime,
    create_http_app,
)
from ..server._lifecycle import _DiscoveryPublisher
from ..server._utils import (
    _clamp_top_k,
    _default_root,
    _is_sensitive_path,
    _resolve_root,
    _validate_vault_root,
)
from ..service import ServiceRegistry
from ..serviceclient._discovery import HEARTBEAT_STALENESS_SECONDS

pytestmark = [pytest.mark.unit]


def test_missing_mcp_extra_guidance_respects_all_install_modes() -> None:
    from ..server._main import _missing_mcp_extra_message

    message = _missing_mcp_extra_message(ImportError("mcp unavailable"))

    assert "uvx --from vaultspec-rag[mcp]" in message
    assert "does not modify the project" in message
    assert "[project].dependencies" in message
    assert "[dependency-groups].dev" in message
    assert "[tool.uv].dev-dependencies" in message
    assert "uv add vaultspec-rag[mcp]" not in message


class TestServerRouteRuntime:
    """The HTTP app owns one explicit, fail-closed route authority."""

    def test_empty_token_is_rejected_before_an_app_can_be_built(self) -> None:
        with pytest.raises(ValueError, match="non-empty service token"):
            ServerRouteRuntime(token="", registry=ServiceRegistry(), port=8765)

    @pytest.mark.parametrize("port", [0, 65536])
    def test_invalid_port_is_rejected_before_an_app_can_be_built(
        self,
        port: int,
    ) -> None:
        with pytest.raises(ValueError, match=r"port in 1\.\.65535"):
            ServerRouteRuntime(
                token="invalid-runtime-port-test-token",
                registry=ServiceRegistry(),
                port=port,
            )

    def test_factory_installs_the_exact_runtime_and_missing_state_fails_closed(
        self,
    ) -> None:
        from starlette.applications import Starlette

        from ..server._runtime import get_app_runtime

        runtime = ServerRouteRuntime(
            token="direct-runtime-test-token",
            registry=ServiceRegistry(),
            port=8765,
        )
        app = create_http_app(runtime, lifespan=None)

        assert get_app_runtime(app) is runtime
        assert get_app_runtime(app).port == 8765
        with pytest.raises(RuntimeError, match="no valid server route runtime"):
            get_app_runtime(Starlette())


def _run[T](coro: Coroutine[object, object, T]) -> T:
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


class TestPackageEntryPoint:
    """Guard the ``python -m vaultspec_rag.server`` daemon-spawn path.

    The service daemon is launched as ``python -m vaultspec_rag.server
    --port N``. When ``server`` became a package, the ``-m`` invocation
    required a ``__main__`` module; without it the daemon never starts and
    every subprocess service-lifecycle test fails. ``--help`` is free (no
    GPU/model load), so this is a fast, real subprocess check.
    """

    def test_python_dash_m_help_runs(self):
        result = subprocess.run(
            [sys.executable, "-m", "vaultspec_rag.server", "--help"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "--port" in result.stdout


@pytest.fixture
def discovery_publisher(tmp_path: Path) -> Iterator[_DiscoveryPublisher]:
    """Retain a real isolated discovery owner for lifecycle helper tests."""
    from .._machine_lock import (
        acquire_machine_lock_lease,
        release_machine_lock_lease,
    )

    status_key = EnvVar.STATUS_DIR.value
    storage_key = EnvVar.QDRANT_STORAGE_DIR.value
    previous_env = {
        status_key: os.environ.get(status_key),
        storage_key: os.environ.get(storage_key),
    }
    os.environ[status_key] = str(tmp_path / "status")
    os.environ[storage_key] = str(tmp_path / "qdrant" / "storage")
    reset_config()
    lease, holder = acquire_machine_lock_lease()
    assert lease is not None
    assert holder == os.getpid()
    publisher = _DiscoveryPublisher(
        ServerRouteRuntime(
            token="test-owner-token",
            registry=ServiceRegistry(),
            port=8766,
        ),
        lease,
    )
    try:
        yield publisher
    finally:
        publisher.quiesce()
        publisher.cleanup()
        release_machine_lock_lease(lease)
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


class TestReadOnlyLaunchSurface:
    """Under the read-only flag the mutating tools are gone, not refusing.

    A composing agent must not be handed the schema of a capability it may not
    call: a tool the model can see is a tool that eventually gets called, and
    two of the withdrawn ones drop a shared index every other consumer on the
    machine depends on. So the contract is absence from the listing, which is
    what these assert.

    Which tools are withdrawn is never spelled out here either. The production
    code derives it from the read-only annotation each tool is registered with,
    and so does this - restating the six names would be a second source of
    truth in the tests, free to disagree with the one in the code.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    @pytest.fixture
    def restored_tool_registry(self) -> typing.Iterator[None]:
        """Return the shared server's tool registry to its launch state.

        The restriction mutates the process-wide server that every other test
        in this file lists, so without this a read-only case would silently
        narrow the surface those cases assert against.
        """
        from ..mcp._mcp import mcp

        registry = mcp._tool_manager._tools
        snapshot = dict(registry)
        try:
            yield
        finally:
            registry.clear()
            registry.update(snapshot)

    @staticmethod
    def _declared_read_only() -> set[str]:
        """Names whose registration declares them read-only."""
        from ..mcp._mcp import mcp

        return {
            tool.name
            for tool in mcp._tool_manager.list_tools()
            if tool.annotations and tool.annotations.read_only_hint
        }

    def test_the_restricted_listing_serves_exactly_the_read_only_tools(
        self, restored_tool_registry: None
    ) -> None:
        """Mutation: had the restriction withdraw nothing (an empty tuple).

        Observed this fail on the set equality, the listing still carrying the
        six mutating tools that the flag exists to remove.
        """
        del restored_tool_registry
        from ..mcp._tools import restrict_to_read_only_tools

        expected = self._declared_read_only()
        assert expected, "no tool declares itself read-only; the premise is gone"

        restrict_to_read_only_tools()

        assert {tool.name for tool in _run(mcp.list_tools())} == expected

    def test_no_tool_that_can_mutate_survives_the_flag(
        self, restored_tool_registry: None
    ) -> None:
        """The assertion that catches a mutating tool added later.

        Equality with the read-only set above would already fail for a new
        mutating tool, but only because the set it compares against is derived.
        This says the invariant directly, so the reason a failure matters is
        legible from the test that fails.

        Mutation: as above. Observed this fail naming ``clean_all`` among the
        survivors.
        """
        del restored_tool_registry
        from ..mcp._tools import restrict_to_read_only_tools

        restrict_to_read_only_tools()

        survivors = [
            tool.name
            for tool in _run(mcp.list_tools())
            if not (tool.annotations and tool.annotations.read_only_hint)
        ]
        assert survivors == [], f"mutating tools survived the flag: {survivors}"

    def test_the_default_launch_still_serves_every_tool(self) -> None:
        """The flag must not narrow the surface an operator or CI gets.

        Deliberately a sibling of the two above rather than trusting them: a
        change that satisfied the restricted assertions by withdrawing tools
        eagerly would leave both of them green and break every operator use of
        reindex and clean.

        Mutation: called the restriction at import time in the tools module,
        so the surface is narrowed before anything asks for it. Observed this
        fail on the strict-subset assertion, the default listing already down
        to the six read-only tools.
        """
        served = {tool.name for tool in _run(mcp.list_tools())}

        assert self._declared_read_only() < served, (
            "the default surface must be strictly wider than the read-only one"
        )

    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            pytest.param(["vaultspec-search-mcp"], False, id="absent"),
            pytest.param(["vaultspec-search-mcp", "--read-only"], True, id="present"),
        ],
    )
    def test_the_restriction_is_opt_in_at_the_launch_boundary(
        self, argv: list[str], expected: bool
    ) -> None:
        """The surface assertions above cannot see which launches restrict.

        They list the shared server directly, so a runner that restricted on
        every launch rather than under the flag would leave all three green
        while silently withdrawing reindex and clean from every operator. The
        opt-in has to be asserted where it is actually decided, which is the
        argument parse.

        Mutation: gave ``--read-only`` ``default=True``. Observed the
        ``absent`` case fail on ``False is True``, the flag no longer opt-in.
        """
        import sys

        from ..server._main import _resolve_daemon_argv

        # Set and restore rather than substitute: the parser reads the real
        # argv, so this drives production's own entry point on a real command
        # line instead of standing anything in for it.
        original = sys.argv
        sys.argv = argv
        try:
            resolved = _resolve_daemon_argv()[2]
        finally:
            sys.argv = original

        assert resolved is expected


class TestToolsSendOnlyCanonicalSources:
    """No MCP tool may put a compatibility alias on the wire.

    The daemon's search route parses its source with ``allow_aliases=False`` -
    a deliberately closed contract - while the CLI and the service client parse
    with ``allow_aliases=True`` at their own boundaries. An adapter that
    forwards its public spelling instead of canonicalising it therefore fails
    against the route while working everywhere else, which is exactly how
    ``search_codebase`` came to be refused with ``unknown_source_type``:
    ``received: "codebase"``, ``aliases_allowed: false``.

    The alias table itself is already guarded in ``test_source_types``. What
    was unguarded is this: that the adapter actually consults it.
    """

    #: Every alias the adapter may be handed, and the canonical value the
    #: route will accept for it. Taken from the same table the parser reads,
    #: so a new alias cannot be added without this pairing being considered.
    ALIAS_EXPECTATIONS: typing.ClassVar = [
        ("codebase", "code"),
        ("docs", "vault"),
        ("all", "combined"),
    ]

    @pytest.mark.parametrize(("alias", "canonical"), ALIAS_EXPECTATIONS)
    def test_an_alias_is_resolved_before_it_reaches_the_wire(
        self, alias: str, canonical: str
    ) -> None:
        """Mutation: had ``_canonical_tool_source`` return ``str(value)``.

        Observed this fail on the equality for ``codebase`` first, the adapter
        handing the route the spelling it refuses.
        """
        from ..mcp._tools import _canonical_tool_source

        assert _canonical_tool_source(alias) == canonical

    def test_every_canonical_source_survives_unchanged(self) -> None:
        """Canonicalising must not disturb a value that is already canonical.

        Mutation: as above. Observed no failure here - a passthrough leaves
        canonical values correct, which is why the alias case above is the one
        carrying this contract.
        """
        from .._source_types import PublicSourceType
        from ..mcp._tools import _canonical_tool_source

        for source in PublicSourceType:
            assert _canonical_tool_source(source.value) == source.value

    def test_an_unknown_source_is_refused_rather_than_forwarded(self) -> None:
        """A value in neither the enum nor the table must not reach the route.

        Mutation: as above. Observed this fail on DID NOT RAISE, the adapter
        forwarding an unknown spelling for the daemon to reject instead of
        refusing it where the caller can be told why.
        """
        from ..mcp._tools import _canonical_tool_source

        with pytest.raises(ValueError, match="unknown_source_type"):
            _canonical_tool_source("not_a_source")


class TestToolRegistration:
    """Verify all expected tools are registered on the MCPServer instance."""

    def test_expected_tools_registered(self):
        tools = _run(mcp.list_tools())
        tool_names = {t.name for t in tools}
        expected = {
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
        assert expected == tool_names

    def test_tool_count(self):
        tools = _run(mcp.list_tools())
        assert len(tools) == 12

    def test_all_tools_have_descriptions(self):
        tools = _run(mcp.list_tools())
        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"

    def test_tools_accept_project_root(self):
        """All search/index tools should accept a project_root parameter."""
        tools = _run(mcp.list_tools())
        tools_with_project_root = {
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
        for tool in tools:
            if tool.name in tools_with_project_root:
                param_names = set(tool.input_schema.get("properties", {}).keys())
                assert "project_root" in param_names, (
                    f"Tool {tool.name} missing project_root parameter"
                )

    def test_search_vault_exposes_filter_params(self):
        """search_vault must expose doc_type/feature/date/tag explicit params."""
        tools = _run(mcp.list_tools())
        sv = next(t for t in tools if t.name == "search_vault")
        params = set(sv.input_schema.get("properties", {}).keys())
        assert {"doc_type", "feature", "date", "tag"}.issubset(params)

    def test_search_codebase_exposes_path_param(self):
        """search_codebase must expose path as an explicit filter param."""
        tools = _run(mcp.list_tools())
        sc = next(t for t in tools if t.name == "search_codebase")
        params = set(sc.input_schema.get("properties", {}).keys())
        assert "path" in params
        # And the original four code filters stay exposed.
        assert {"language", "node_type", "function_name", "class_name"}.issubset(params)

    def test_search_documents_exposes_provenance_filters(self):
        tools = _run(mcp.list_tools())
        search = next(t for t in tools if t.name == "search_documents")
        params = set(search.input_schema.get("properties", {}))
        assert {
            "source_path",
            "extractor_id",
            "extractor_version",
            "locator_kind",
        } <= params

    def test_search_codebase_exposes_glob_params(self):
        """search_codebase must expose include_paths/exclude_paths list[str]."""
        tools = _run(mcp.list_tools())
        sc = next(t for t in tools if t.name == "search_codebase")
        properties = sc.input_schema.get("properties", {})
        assert "include_paths" in properties
        assert "exclude_paths" in properties
        # The SDK renders list[str] | None as anyOf [array, null]; accept
        # either that or a direct array schema for forward compatibility.
        for key in ("include_paths", "exclude_paths"):
            schema = properties[key]
            if "anyOf" in schema:
                array_branch = next(
                    b for b in schema["anyOf"] if b.get("type") == "array"
                )
                assert array_branch["items"]["type"] == "string"
            else:
                assert schema.get("type") == "array"
                assert schema["items"]["type"] == "string"


class TestPromptRegistration:
    """Verify prompts are registered."""

    def test_analyze_feature_registered(self):
        prompts = _run(mcp.list_prompts())
        prompt_names = {p.name for p in prompts}
        assert "analyze_feature" in prompt_names

    def test_prompt_count(self):
        prompts = _run(mcp.list_prompts())
        assert len(prompts) == 1


class TestAnalyzeFeaturePrompt:
    """Test the analyze_feature prompt template."""

    def test_contains_feature_name(self):
        result = analyze_feature("rag")
        assert "rag" in result

    def test_references_search_tools(self):
        result = analyze_feature("indexing")
        assert "search_vault" in result
        assert "search_codebase" in result

    def test_structured_steps(self):
        result = analyze_feature("search")
        assert "1." in result
        assert "2." in result
        assert "3." in result


class TestPydanticModels:
    """Test Pydantic model validation and serialization."""

    def test_search_result_item_minimal(self):
        item = SearchResultItem(
            id="doc-1",
            path="docs/adr-001.md",
            title="ADR 001",
            score=0.95,
            snippet="Some text",
            source="vault",
        )
        assert item.id == "doc-1"
        assert item.score == 0.95
        assert item.line_start is None

    def test_search_result_item_full(self):
        item = SearchResultItem(
            id="code-1",
            path="src/main.py",
            title="main module",
            score=0.88,
            snippet="def main():",
            source="codebase",
            language="python",
            line_start=1,
            line_end=10,
            rerank_text="def main():\n    return 0",
        )
        assert item.language == "python"
        assert item.line_start == 1
        assert item.rerank_text == "def main():\n    return 0"
        assert "rerank_text" not in item.model_dump()

    def test_search_response(self):
        resp = SearchResponse(
            results=[
                SearchResultItem(
                    id="1",
                    path="a.md",
                    title="A",
                    score=0.9,
                    snippet="text",
                    source="vault",
                ),
            ],
            summary="Found 1 result",
        )
        assert len(resp.results) == 1
        assert "1 result" in resp.summary
        assert resp.backend_capabilities.backend == "qdrant-local"
        assert resp.backend_capabilities.concurrent_search_supported is True
        assert resp.backend_capabilities.same_project_search_strategy == "serialized"
        assert resp.backend_capabilities.cross_project_search_strategy == "parallel"
        assert resp.backend_capabilities.local_storage_process_model == "exclusive"

    def test_search_response_empty(self):
        resp = SearchResponse(results=[], summary="No results")
        assert len(resp.results) == 0
        assert resp.backend_capabilities.concurrent_search_supported is True

    def test_backend_capabilities_serializes_to_tool_schema(self):
        caps = BackendCapabilities()
        data = caps.model_dump()

        assert data == {
            "backend": "qdrant-local",
            "concurrent_search_supported": True,
            "same_project_search_strategy": "serialized",
            "cross_project_search_strategy": "parallel",
            "local_storage_process_model": "exclusive",
        }

    def test_index_status(self):
        status = IndexStatus(
            vault_count=100,
            code_count=500,
            storage_path="/tmp/qdrant",
            target_dir="/tmp/workspace",
        )
        assert status.vault_count == 100
        assert status.code_count == 500
        assert status.target_dir == "/tmp/workspace"
        assert status.backend_capabilities.concurrent_search_supported is True

    def test_index_response(self):
        resp = IndexResponse(
            total=50,
            added=10,
            updated=5,
            removed=2,
            duration_ms=1500,
        )
        assert resp.total == 50
        assert resp.files == 0  # default

    def test_index_response_with_files(self):
        resp = IndexResponse(
            total=200,
            added=200,
            updated=0,
            removed=0,
            duration_ms=3000,
            files=42,
        )
        assert resp.files == 42

    def test_search_result_item_from_attributes(self):
        """Verify model_config from_attributes works with dict input."""
        data = {
            "id": "test",
            "path": "test.md",
            "title": "Test",
            "score": 0.5,
            "snippet": "content",
            "source": "vault",
        }
        item = SearchResultItem.model_validate(data)
        assert item.id == "test"

    def test_health_response(self):
        resp = HealthResponse(
            status="ready",
            cuda=True,
            models_loaded=True,
            project_count=1,
            uptime_s=42.5,
        )
        assert resp.status == "ready"
        assert resp.cuda is True
        assert resp.models_loaded is True
        assert resp.project_count == 1
        assert resp.uptime_s == 42.5
        assert resp.backend_capabilities.concurrent_search_supported is True

    def test_health_response_defaults(self):
        resp = HealthResponse(
            status="loading",
            cuda=False,
            models_loaded=False,
        )
        assert resp.project_count == 0
        # service_token is opt-in (default empty so pre-upgrade
        # serialisation stays identical).
        assert resp.service_token == ""

    def test_health_response_includes_service_token(self):
        """/health round-trips the identity token."""
        resp = HealthResponse(
            status="ready",
            cuda=True,
            models_loaded=True,
            service_token="abc123",
        )
        assert resp.service_token == "abc123"
        # The token must serialise - consumers parse the JSON payload.
        assert resp.model_dump()["service_token"] == "abc123"
        assert resp.uptime_s == 0.0
        assert resp.backend_capabilities.same_project_search_strategy == "serialized"


class TestPathTraversalValidation:
    """Test path validation logic used by get_code_file."""

    def test_traversal_with_dotdot_detected(self, tmp_path: Path) -> None:
        """Paths with .. that escape the root should be caught."""
        root_resolved: Path = tmp_path.resolve()
        malicious = "../../etc/passwd"
        full_path: Path = (root_resolved / malicious).resolve()
        assert not full_path.is_relative_to(root_resolved)

    def test_valid_relative_path_passes(self, tmp_path: Path) -> None:
        """A normal relative path should stay within root."""
        root_resolved: Path = tmp_path.resolve()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1", encoding="utf-8")
        full_path: Path = (root_resolved / "src/main.py").resolve()
        assert full_path.is_relative_to(root_resolved)

    def test_symlink_escaping_root_detected(self, tmp_path: Path) -> None:
        """A symlink pointing outside the workspace should be caught."""
        import os

        root_resolved: Path = tmp_path.resolve()
        link_path: Path = tmp_path / "escape_link"
        try:
            os.symlink(tmp_path.parent, link_path)
        except OSError:
            pytest.fail("Cannot create symlink - test requires symlink support")
        full_path: Path = (root_resolved / "escape_link" / "other_file.txt").resolve()
        assert not full_path.is_relative_to(root_resolved)


class TestVaultBoundaryValidation:
    """SEC-001: _validate_vault_root rejects paths without .vault/."""

    def test_valid_vault_root(self, tmp_path: Path) -> None:
        (tmp_path / ".vault").mkdir()
        result = _validate_vault_root(tmp_path)
        assert result == tmp_path

    def test_missing_vault_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match=r"no \.vault/ directory"):
            _validate_vault_root(tmp_path)

    def test_nonexistent_path_raises(self, tmp_path: Path) -> None:
        fake: Path = tmp_path / "does-not-exist"
        with pytest.raises(ValueError, match=r"no \.vault/ directory"):
            _validate_vault_root(fake)

    def test_resolve_root_rejects_non_vault(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match=r"no \.vault/ directory"):
            _resolve_root(str(tmp_path))

    def test_resolve_root_accepts_vault(self, tmp_path: Path) -> None:
        (tmp_path / ".vault").mkdir()
        result = _resolve_root(str(tmp_path))
        assert result == tmp_path.resolve()


class TestSensitiveFileDenyList:
    """SEC-002: _is_sensitive_path blocks sensitive file patterns."""

    @pytest.mark.parametrize(
        "path",
        [
            ".env",
            ".env.local",
            ".env.production",
            ".git/config",
            ".git/HEAD",
            "deploy/secrets.yaml",
            "config/credentials.json",
            "tls/server.pem",
            "tls/server.key",
            "service.json",
            ".vaultspec-rag/service.json",
            # Nested sensitive dirs
            "vendor/.git/objects/pack",
            "sub/dir/.vaultspec-rag/data",
            # Mid-name matches for credentials/secrets patterns
            "my-credentials-backup.txt",
            "app.secrets.yaml",
        ],
    )
    def test_sensitive_paths_blocked(self, path: str) -> None:
        assert _is_sensitive_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "src/main.py",
            "README.md",
            ".vault/adr/test.md",
            "docs/environment.md",
            "config/settings.toml",
            "src/services/auth.py",
            # Edge cases that should NOT be blocked
            "src/service.py",
            "envconfig.toml",
            ".github/workflows/ci.yml",
        ],
    )
    def test_safe_paths_allowed(self, path: str) -> None:
        assert _is_sensitive_path(path) is False

    def test_backslash_normalization(self):
        assert _is_sensitive_path(".git\\config") is True
        assert _is_sensitive_path("src\\main.py") is False


class TestClampTopK:
    """Test the _clamp_top_k helper."""

    def test_clamp_within_range(self):
        assert _clamp_top_k(5) == 5

    def test_clamp_below_minimum(self):
        assert _clamp_top_k(0) == 1
        assert _clamp_top_k(-10) == 1

    def test_clamp_above_maximum(self):
        assert _clamp_top_k(200) == 100
        assert _clamp_top_k(101) == 100

    def test_clamp_boundary_values(self):
        assert _clamp_top_k(1) == 1
        assert _clamp_top_k(100) == 100


class TestResolveRoot:
    """Test the _resolve_root and _default_root helpers."""

    def test_resolve_root_explicit(self, tmp_path: Path) -> None:
        (tmp_path / ".vault").mkdir()
        result = _resolve_root(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_resolve_root_none_uses_default(self):
        """When project_root is None and env unset, falls back to cwd."""
        from pathlib import Path

        orig = os.environ.pop(EnvVar.RAG_ROOT, None)
        try:
            result = _resolve_root(None)
            assert result == Path.cwd().resolve()
        finally:
            if orig is not None:
                os.environ[EnvVar.RAG_ROOT] = orig

    def test_resolve_root_from_env(self, tmp_path: Path) -> None:
        (tmp_path / ".vault").mkdir()
        orig = os.environ.get(EnvVar.RAG_ROOT)
        os.environ[EnvVar.RAG_ROOT] = str(tmp_path)
        try:
            result = _resolve_root(None)
            assert result == tmp_path.resolve()
        finally:
            if orig is not None:
                os.environ[EnvVar.RAG_ROOT] = orig
            else:
                os.environ.pop(EnvVar.RAG_ROOT, None)

    def test_default_root_from_env(self, tmp_path: Path) -> None:
        (tmp_path / ".vault").mkdir()
        orig = os.environ.get(EnvVar.RAG_ROOT)
        os.environ[EnvVar.RAG_ROOT] = str(tmp_path)
        try:
            result = _default_root()
            assert result == tmp_path.resolve()
        finally:
            if orig is not None:
                os.environ[EnvVar.RAG_ROOT] = orig
            else:
                os.environ.pop(EnvVar.RAG_ROOT, None)

    def test_default_root_cwd(self):
        from pathlib import Path

        orig = os.environ.pop(EnvVar.RAG_ROOT, None)
        try:
            result = _default_root()
            assert result == Path.cwd().resolve()
        finally:
            if orig is not None:
                os.environ[EnvVar.RAG_ROOT] = orig


class TestMainTransportSetup:
    """The stdio runner's lifecycle wiring, driven for real."""

    def test_stdio_runner_wires_cleanup_and_loads_no_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Stdio is a thin client: it wires watcher cleanup and loads nothing.

        Two contracts share one drive of ``_run_stdio_mcp`` because both are
        observed at the same instant - when the transport is entered - and
        because each extra substitution site has to earn itself (see
        ``test_substitution_discipline``).

        The previous tests here asserted neither contract. One scanned
        ``inspect.getsource(server.main)`` for ``"load_model"``, but ``main``
        only dispatches to ``_run_stdio_mcp``, so a load added where the work
        actually happens passed the scan untouched. The other assigned
        ``registry._on_close_project`` in the test body and then asserted its
        own assignment, never calling production at all.

        Mutations this catches: any ``load_model()`` reachable from
        ``_run_stdio_mcp``, and dropping its ``_on_close_project`` wiring.
        """
        import vaultspec_rag.server as mod

        from ..server import _main
        from ..server import _stdio_lifetime as stdio_lifetime
        from ..service import ServiceRegistry

        loads: list[str | None] = []

        def _record_load(_self: ServiceRegistry, model_name: str | None = None) -> None:
            loads.append(model_name)

        def _no_watchdog(*_args: object, **_kwargs: object) -> None:
            return None

        seen_hooks: list[object] = []
        entered: list[str] = []

        class _FakeMcp:
            @staticmethod
            def run(transport: str) -> None:
                entered.append(transport)
                seen_hooks.append(mod._registry._on_close_project)

        monkeypatch.setattr(ServiceRegistry, "load_model", _record_load)
        monkeypatch.setattr(
            stdio_lifetime, "install_stdio_lifetime_watchdog", _no_watchdog
        )
        monkeypatch.setattr("vaultspec_rag.mcp.mcp", _FakeMcp())

        from ..registry import reset_registry

        original_hook = mod._registry._on_close_project
        mod._registry._on_close_project = None
        try:
            _main._run_stdio_mcp(None)
        finally:
            mod._registry._on_close_project = original_hook
            # The runner closes the process-wide registry on its way out, so
            # driving it for real - which is what stopped this being a source
            # scan - leaves the singleton refusing every later lease. Discard
            # it here or the next file to reach the registry inherits a
            # shut-down one and fails for reasons that have nothing to do with
            # it.
            reset_registry()

        # Non-emptiness first: if the runner never reached the transport, the
        # two assertions below would both hold vacuously.
        assert entered == ["stdio"], entered
        assert seen_hooks == [mod._stop_watcher], seen_hooks
        assert loads == [], (
            "stdio MCP must not load a model; it delegates to the daemon"
        )


class TestServiceRegistryIntegration:
    """Test that the module-level _registry is a ServiceRegistry."""

    def test_registry_exists(self):
        from ..server import _registry
        from ..service import ServiceRegistry

        assert isinstance(_registry, ServiceRegistry)

    def test_registry_has_gpu_lock(self):
        from ..server import _registry

        assert isinstance(_registry.gpu_lock, threading.Lock)


class TestHealthHandler:
    """Test the health_handler async function."""

    def test_health_handler_returns_json(self):
        """health_handler returns a JSONResponse with expected keys."""
        from starlette.testclient import TestClient

        app = create_http_app(
            ServerRouteRuntime(
                token="health-response-token",
                registry=ServiceRegistry(),
                port=8765,
            ),
            lifespan=None,
        )
        client: httpx.Client = cast("httpx.Client", TestClient(app))
        resp: httpx.Response = client.get("/health")
        assert resp.status_code == 200
        data: dict[str, object] = cast("dict[str, object]", resp.json())
        assert "status" in data
        assert "cuda" in data
        assert "models_loaded" in data
        assert "project_count" in data
        assert "uptime_s" in data
        assert data["port"] == 8765
        capabilities = cast("dict[str, object]", data["backend_capabilities"])
        assert capabilities["concurrent_search_supported"] is True
        assert capabilities["same_project_search_strategy"] == "serialized"
        profile = cast("dict[str, object]", data["support_profile"])
        domains = cast("dict[str, dict[str, int]]", profile["domains"])
        assert set(domains) == {"code", "document"}
        expected_limits = {
            "source_files",
            "source_bytes",
            "generated_chunks",
            "weighted_bytes",
            "extracted_bytes",
            "queue_bytes",
            "rss_bytes",
            "cuda_bytes",
        }
        assert set(domains["code"]) == expected_limits
        assert set(domains["document"]) == expected_limits
        assert domains["code"] != domains["document"]

    def test_health_status_reflects_model_state(self):
        """Without models loaded, status should not be 'ready'.

        Uses a fresh, model-less registry to keep the route state isolated.
        """
        from starlette.testclient import TestClient

        app = create_http_app(
            ServerRouteRuntime(
                token="health-model-state-token",
                registry=ServiceRegistry(),
                port=8765,
            ),
            lifespan=None,
        )
        client: httpx.Client = cast("httpx.Client", TestClient(app))
        # A fresh registry is not enough: the not-started verdict reads a
        # reassigned process global that lifespan startup stamps once and
        # never clears, so any earlier test that ran a lifespan leaves this
        # asserting the opposite of what it names. The isolation the
        # docstring claims has to cover that global too.
        from .. import server as _m

        prior_start_time = _m._start_time
        _m._start_time = 0.0
        try:
            resp: httpx.Response = client.get("/health")
            data: dict[str, object] = cast("dict[str, object]", resp.json())
            assert data["status"] == "error"
            assert data["models_loaded"] is False
        finally:
            _m._start_time = prior_start_time


class TestHealthInfoReduction:
    """SEC-003: Health endpoint does not leak sensitive information."""

    def test_health_no_project_paths(self):
        """Health response must not contain absolute project paths."""
        from starlette.testclient import TestClient

        app = create_http_app(
            ServerRouteRuntime(
                token="health-project-path-token",
                registry=ServiceRegistry(),
                port=8765,
            ),
            lifespan=None,
        )
        client: httpx.Client = cast("httpx.Client", TestClient(app))
        raw = client.get("/health").json()
        data: dict[str, object] = cast("dict[str, object]", raw)
        assert "projects" not in data
        assert "project_count" in data
        assert isinstance(data["project_count"], int)

    def test_health_no_gpu_name(self):
        """Health response must not contain GPU device name."""
        from starlette.testclient import TestClient

        app = create_http_app(
            ServerRouteRuntime(
                token="health-gpu-name-token",
                registry=ServiceRegistry(),
                port=8765,
            ),
            lifespan=None,
        )
        client: httpx.Client = cast("httpx.Client", TestClient(app))
        raw = client.get("/health").json()
        data: dict[str, object] = cast("dict[str, object]", raw)
        assert "gpu_name" not in data

    def test_index_status_no_gpu_name(self):
        """IndexStatus model must not have gpu_name field."""
        status = IndexStatus(
            vault_count=10,
            code_count=50,
            storage_path="/tmp/db",
            target_dir="/tmp/ws",
        )
        assert (
            not hasattr(status, "gpu_name")
            or "gpu_name" not in IndexStatus.model_fields
        )


class TestMultiProjectWatcher:
    """``_stop_all_watchers`` really drains every registered project root."""

    def test_stop_watcher_on_an_unregistered_root_returns_no_cleanup(
        self,
        tmp_path: Path,
    ) -> None:
        """An unknown root has nothing to drain, so no cleanup task is owed.

        Mutation this catches: manufacturing a drain (and therefore a cleanup
        task) for a root that was never registered. The earlier version of
        this test called ``_stop_watcher`` and asserted nothing at all, so it
        held for any return value.
        """
        from .. import server
        from ..server import _stop_watcher
        from ..server import _watcher as watcher_lifecycle

        root = tmp_path.resolve()
        assert root not in server._watcher_tasks

        assert _stop_watcher(root) is None
        assert root not in watcher_lifecycle._watcher_drains

    async def test_stop_all_watchers_drains_every_registered_root(
        self,
        tmp_path: Path,
    ) -> None:
        """Two roots are registered; one call must clear intake for both.

        Mutation this catches: an early ``return ()`` from
        ``_stop_all_watchers``, or a body that visits only one root. The
        previous tests here asserted ``callable(...)``, ``isinstance(..., dict)``
        and "does not raise" against already-empty state, so all of them held
        against a ``_stop_all_watchers`` whose body did nothing at all.
        """
        from .. import server
        from ..server import _stop_all_watchers, _watcher_stops, _watcher_tasks
        from ..server import _watcher as watcher_lifecycle

        release = asyncio.Event()

        async def _intake() -> None:
            await release.wait()

        roots = [(tmp_path / "a").resolve(), (tmp_path / "b").resolve()]
        intakes: dict[Path, asyncio.Task[None]] = {}
        try:
            for root in roots:
                root.mkdir()
                intakes[root] = asyncio.create_task(_intake())
                with server._watcher_lock:
                    _watcher_tasks[root] = intakes[root]
                    _watcher_stops[root] = asyncio.Event()

            # Precondition: both roots really are registered, so the
            # post-conditions below cannot pass over empty state.
            assert all(root in _watcher_tasks for root in roots)

            cleanups = _stop_all_watchers()

            assert len(cleanups) == len(roots), cleanups
            for root in roots:
                assert root not in _watcher_tasks, root
                assert root not in _watcher_stops, root
                assert root in watcher_lifecycle._watcher_drains, root
        finally:
            release.set()
            for root in roots:
                assert await server._wait_for_watcher_cleanup(root, timeout_seconds=10)
            await asyncio.gather(*intakes.values(), return_exceptions=True)

        for root in roots:
            assert root not in watcher_lifecycle._watcher_drains, root


class TestDaemonServesNativeRestOnly:
    """The HTTP daemon serves native REST only - no MCP surface is mounted.

    Stdio is the sole MCP transport. The daemon's ``Mount("/mcp")`` and the
    ``_mcp_no_redirect`` ASGI path-rewrite wrapper were removed outright (no
    shim, no feature-flagged path), so a tool call no longer loops back into
    the daemon that serves it.

    This drives the real route factory and reads the real route table, rather
    than scanning ``main``'s source. The scan could not see this contract at
    all: ``main`` is a two-line dispatcher, so it contains neither the mount
    nor the app it would be added to.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    @staticmethod
    def _served_paths() -> list[str]:
        """Return the real route paths of the app the daemon serves."""
        app = create_http_app(
            ServerRouteRuntime(
                token="native-rest-only-token",
                registry=ServiceRegistry(),
                port=8765,
            ),
            lifespan=None,
        )
        return [str(getattr(route, "path", "")) for route in app.routes]

    def test_daemon_mounts_no_mcp_surface(self) -> None:
        """No route the daemon serves sits under /mcp.

        Mutation this catches: adding a ``Mount("/mcp", ...)`` - with or
        without the streamable-HTTP app behind it - to the route table.
        """
        paths = self._served_paths()

        # Non-emptiness first: an empty route table would satisfy the
        # no-/mcp assertion below while proving nothing.
        assert "/health" in paths, paths
        assert not [p for p in paths if p.startswith("/mcp")], paths


class TestDaemonLifecycleHelpers:
    """_lifecycle_log + _heartbeat_tick_sync + cleanup helpers."""

    def test_lifecycle_log_emits_info_with_structured_format(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from ..server import _lifecycle_log

        with caplog.at_level("INFO", logger="vaultspec_rag.server"):
            _lifecycle_log("startup", pid=42, port=8766)

        records: list[logging.LogRecord] = [
            r for r in caplog.records if r.name == "vaultspec_rag.server"
        ]
        assert records, "lifecycle log did not surface on the expected logger"
        rec: logging.LogRecord = records[-1]
        assert rec.levelname == "INFO"
        rendered: str = rec.getMessage()
        assert rendered.startswith("service.lifecycle ")
        assert "event=startup" in rendered
        assert "pid=42" in rendered
        assert "port=8766" in rendered

    def test_heartbeat_tick_sync_no_status_file(
        self,
        discovery_publisher: _DiscoveryPublisher,
    ) -> None:
        """The owner publishes a complete snapshot when no status file exists."""
        from .. import server

        sf = server._status_file_path()
        assert not sf.exists()
        server._heartbeat_tick_sync(discovery_publisher)
        assert sf.exists()

    def test_heartbeat_tick_sync_writes_last_heartbeat(
        self,
        discovery_publisher: _DiscoveryPublisher,
    ) -> None:
        """The owner replaces stale discovery fields with its current snapshot."""
        from datetime import UTC, datetime

        from .. import server

        sf = server._status_file_path()
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(
            json.dumps({"pid": 1, "port": 2, "started_at": "x"}),
            encoding="utf-8",
        )

        server._heartbeat_tick_sync(discovery_publisher)

        data: dict[str, object] = json.loads(sf.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()
        assert data["parent_pid"] == os.getppid()
        assert data["port"] == 8766
        assert data["started_at"] == discovery_publisher.started_at
        assert "last_heartbeat" in data
        # Parses as a valid ISO-8601 timestamp.
        ts = datetime.fromisoformat(cast("str", data["last_heartbeat"]))
        assert ts.tzinfo is not None
        delta = (datetime.now(UTC) - ts).total_seconds()
        # Bounded by the project's own definition of a stale heartbeat rather
        # than a hand-picked number. What this pins is that the tick stamps
        # NOW - a stale or absent stamp is off by the age of the record, which
        # is orders of magnitude past this bound. The 5s it used to assert was
        # narrower than the freshness anything actually requires, so on a
        # loaded runner the scheduling gap between the write and this read
        # failed a heartbeat that was entirely correct.
        #
        # Mutation: made _discovery_timestamp stamp one hour in the past.
        # Observed this fail on the assertion below with 3600.4 < 60, so the
        # wider bound still discriminates a stale stamp from a fresh one.
        # Restored, and it passes.
        assert -1 < delta < HEARTBEAT_STALENESS_SECONDS

    def test_heartbeat_tick_sync_merges_service_token(
        self,
        discovery_publisher: _DiscoveryPublisher,
    ) -> None:
        """The retained owner's service token is published authoritatively."""
        from .. import server

        sf = server._status_file_path()
        server._heartbeat_tick_sync(discovery_publisher)

        data: dict[str, object] = json.loads(sf.read_text(encoding="utf-8"))
        assert data["service_token"] == "test-owner-token"

    def test_heartbeat_tick_sync_replaces_stale_token(
        self,
        discovery_publisher: _DiscoveryPublisher,
    ) -> None:
        """A stale token cannot survive an owner-authenticated heartbeat."""
        from .. import server

        sf = server._status_file_path()
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(
            json.dumps(
                {
                    "pid": 1,
                    "port": 2,
                    "started_at": "x",
                    "service_token": "previous-token",
                },
            ),
            encoding="utf-8",
        )

        server._heartbeat_tick_sync(discovery_publisher)

        data: dict[str, object] = json.loads(sf.read_text(encoding="utf-8"))
        assert data["service_token"] == "test-owner-token"

    def test_discovery_cleanup_missing_is_idempotent(
        self,
        discovery_publisher: _DiscoveryPublisher,
    ) -> None:
        """Repeated owner cleanup converges when both views are absent."""
        assert discovery_publisher.cleanup() is True
        assert discovery_publisher.cleanup() is True

    def test_record_shutdown_is_idempotent(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """First call wins; subsequent calls do not emit a second record."""
        from .. import server

        prior = server._shutdown_recorded
        server._shutdown_recorded = False
        try:
            with caplog.at_level("INFO", logger="vaultspec_rag.server"):
                server._record_shutdown("test-first")
                server._record_shutdown("test-second")
        finally:
            server._shutdown_recorded = prior

        first: list[logging.LogRecord] = [
            r
            for r in caplog.records
            if r.name == "vaultspec_rag.server"
            and "reason=test-first" in r.getMessage()
        ]
        second: list[logging.LogRecord] = [
            r
            for r in caplog.records
            if r.name == "vaultspec_rag.server"
            and "reason=test-second" in r.getMessage()
        ]
        assert first, "first shutdown should log"
        assert not second, "second shutdown should be suppressed"
