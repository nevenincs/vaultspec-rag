"""Unit tests for the MCP server module."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import typing
from contextlib import asynccontextmanager

import pytest

from vaultspec_rag.mcp._mcp import mcp
from vaultspec_rag.mcp._resources import analyze_feature

from ..config import EnvVar
from ..server import (
    BackendCapabilities,
    HealthResponse,
    IndexResponse,
    IndexStatus,
    SearchResponse,
    SearchResultItem,
    _clamp_top_k,
    _default_root,
    _is_sensitive_path,
    _resolve_root,
    _validate_vault_root,
    health_handler,
)

pytestmark = [pytest.mark.unit]


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


@asynccontextmanager
async def _empty_lifespan(_app):
    yield


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


class TestToolRegistration:
    """Verify all expected tools are registered on the FastMCP instance."""

    def test_expected_tools_registered(self):
        tools = _run(mcp.list_tools())
        tool_names = {t.name for t in tools}
        expected = {
            "search_vault",
            "search_codebase",
            "get_index_status",
            "get_code_file",
            "reindex_vault",
            "reindex_codebase",
            "list_projects",
            "evict_project",
            "get_watcher_state",
            "start_watcher",
            "stop_watcher",
            "reconfigure_watcher",
            "get_service_state",
            "get_logs",
            "get_jobs",
            "benchmark",
            "quality",
        }
        assert expected == tool_names

    def test_tool_count(self):
        tools = _run(mcp.list_tools())
        assert len(tools) == 17

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
            "get_index_status",
            "get_code_file",
            "reindex_vault",
            "reindex_codebase",
            "benchmark",
        }
        for tool in tools:
            if tool.name in tools_with_project_root:
                param_names = set(tool.inputSchema.get("properties", {}).keys())
                assert "project_root" in param_names, (
                    f"Tool {tool.name} missing project_root parameter"
                )

    def test_search_vault_exposes_filter_params(self):
        """search_vault must expose doc_type/feature/date/tag explicit params."""
        tools = _run(mcp.list_tools())
        sv = next(t for t in tools if t.name == "search_vault")
        params = set(sv.inputSchema.get("properties", {}).keys())
        assert {"doc_type", "feature", "date", "tag"}.issubset(params)

    def test_search_codebase_exposes_path_param(self):
        """search_codebase must expose path as an explicit filter param."""
        tools = _run(mcp.list_tools())
        sc = next(t for t in tools if t.name == "search_codebase")
        params = set(sc.inputSchema.get("properties", {}).keys())
        assert "path" in params
        # And the original four code filters stay exposed.
        assert {"language", "node_type", "function_name", "class_name"}.issubset(params)

    def test_search_codebase_exposes_glob_params(self):
        """search_codebase must expose include_paths/exclude_paths list[str]."""
        tools = _run(mcp.list_tools())
        sc = next(t for t in tools if t.name == "search_codebase")
        properties = sc.inputSchema.get("properties", {})
        assert "include_paths" in properties
        assert "exclude_paths" in properties
        # FastMCP renders list[str] | None as anyOf [array, null]; accept
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
        )
        assert item.language == "python"
        assert item.line_start == 1

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

    def test_traversal_with_dotdot_detected(self, tmp_path):
        """Paths with .. that escape the root should be caught."""
        root_resolved = tmp_path.resolve()
        malicious = "../../etc/passwd"
        full_path = (root_resolved / malicious).resolve()
        assert not full_path.is_relative_to(root_resolved)

    def test_valid_relative_path_passes(self, tmp_path):
        """A normal relative path should stay within root."""
        root_resolved = tmp_path.resolve()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1", encoding="utf-8")
        full_path = (root_resolved / "src/main.py").resolve()
        assert full_path.is_relative_to(root_resolved)

    def test_symlink_escaping_root_detected(self, tmp_path):
        """A symlink pointing outside the workspace should be caught."""
        import os

        root_resolved = tmp_path.resolve()
        link_path = tmp_path / "escape_link"
        try:
            os.symlink(tmp_path.parent, link_path)
        except OSError:
            pytest.fail("Cannot create symlink - test requires symlink support")
        full_path = (root_resolved / "escape_link" / "other_file.txt").resolve()
        assert not full_path.is_relative_to(root_resolved)


class TestVaultBoundaryValidation:
    """SEC-001: _validate_vault_root rejects paths without .vault/."""

    def test_valid_vault_root(self, tmp_path):
        (tmp_path / ".vault").mkdir()
        result = _validate_vault_root(tmp_path)
        assert result == tmp_path

    def test_missing_vault_raises(self, tmp_path):
        with pytest.raises(ValueError, match=r"no \.vault/ directory"):
            _validate_vault_root(tmp_path)

    def test_nonexistent_path_raises(self, tmp_path):
        fake = tmp_path / "does-not-exist"
        with pytest.raises(ValueError, match=r"no \.vault/ directory"):
            _validate_vault_root(fake)

    def test_resolve_root_rejects_non_vault(self, tmp_path):
        with pytest.raises(ValueError, match=r"no \.vault/ directory"):
            _resolve_root(str(tmp_path))

    def test_resolve_root_accepts_vault(self, tmp_path):
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
    def test_sensitive_paths_blocked(self, path):
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
    def test_safe_paths_allowed(self, path):
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

    def test_resolve_root_explicit(self, tmp_path):
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

    def test_resolve_root_from_env(self, tmp_path):
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

    def test_default_root_from_env(self, tmp_path):
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


class TestHttpModeResolveRoot:
    """HTTP mode requires explicit project_root - no env/cwd fallback."""

    def test_default_root_raises_in_http_mode(self):
        import vaultspec_rag.server as mod

        orig = mod._http_mode
        mod._http_mode = True
        try:
            with pytest.raises(ValueError, match="project_root is required"):
                _default_root()
        finally:
            mod._http_mode = orig

    def test_resolve_root_none_raises_in_http_mode(self):
        import vaultspec_rag.server as mod

        orig = mod._http_mode
        mod._http_mode = True
        try:
            with pytest.raises(ValueError, match="project_root is required"):
                _resolve_root(None)
        finally:
            mod._http_mode = orig

    def test_resolve_root_explicit_works_in_http_mode(self, tmp_path):
        import vaultspec_rag.server as mod

        (tmp_path / ".vault").mkdir()
        orig = mod._http_mode
        mod._http_mode = True
        try:
            result = _resolve_root(str(tmp_path))
            assert result == tmp_path.resolve()
        finally:
            mod._http_mode = orig

    def test_resolve_root_env_ignored_in_http_mode(self, tmp_path):
        """Even with VAULTSPEC_RAG_ROOT set, HTTP mode rejects None."""
        import vaultspec_rag.server as mod

        (tmp_path / ".vault").mkdir()
        orig_mode = mod._http_mode
        orig_env = os.environ.get(EnvVar.RAG_ROOT)
        mod._http_mode = True
        os.environ[EnvVar.RAG_ROOT] = str(tmp_path)
        try:
            with pytest.raises(ValueError, match="project_root is required"):
                _resolve_root(None)
        finally:
            mod._http_mode = orig_mode
            if orig_env is not None:
                os.environ[EnvVar.RAG_ROOT] = orig_env
            else:
                os.environ.pop(EnvVar.RAG_ROOT, None)

    def test_resolve_root_empty_string_raises(self):
        """Empty string project_root is rejected in both modes."""
        with pytest.raises(ValueError, match="must not be empty"):
            _resolve_root("")

    def test_resolve_root_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _resolve_root("   ")

    def test_vault_resource_raises_in_http_mode(self):
        """get_vault_document should raise with resource-specific message."""
        import vaultspec_rag.server as mod

        orig = mod._http_mode
        mod._http_mode = True
        try:
            with pytest.raises(
                ValueError,
                match="only available in stdio mode",
            ):
                from vaultspec_rag.mcp._resources import get_vault_document

                _run(get_vault_document("adr/overview"))
        finally:
            mod._http_mode = orig


class TestMainTransportSetup:
    """Verify main() correctly sets transport mode and lifecycle hooks."""

    def test_http_mode_flag_for_http(self):
        """port=8888 → _http_mode=True."""
        import vaultspec_rag.server as mod

        orig = mod._http_mode
        try:
            port = 8888
            mod._http_mode = port is not None
            assert mod._http_mode is True
        finally:
            mod._http_mode = orig

    def test_http_mode_flag_for_stdio(self):
        """port=None → _http_mode=False."""
        import vaultspec_rag.server as mod

        orig = mod._http_mode
        try:
            port = None
            mod._http_mode = port is not None
            assert mod._http_mode is False
        finally:
            mod._http_mode = orig

    def test_stdio_wires_on_close_project(self):
        """Stdio path must wire _on_close_project for watcher cleanup."""
        import vaultspec_rag.server as mod

        orig = mod._registry._on_close_project
        try:
            # Simulate what main(port=None) does before mcp.run()
            mod._registry._on_close_project = mod._stop_watcher
            assert mod._registry._on_close_project is mod._stop_watcher
        finally:
            mod._registry._on_close_project = orig

    def test_stop_all_watchers_clears_state(self):
        """_stop_all_watchers empties both dicts even when empty."""
        import vaultspec_rag.server as mod

        # Verify it's safe to call with no watchers running
        mod._stop_all_watchers()
        assert len(mod._watcher_tasks) == 0
        assert len(mod._watcher_stops) == 0


class TestServiceRegistryIntegration:
    """Test that the module-level _registry is a ServiceRegistry."""

    def test_registry_exists(self):
        from ..server import _registry
        from ..service import ServiceRegistry

        assert isinstance(_registry, ServiceRegistry)

    def test_registry_has_gpu_lock(self):
        from ..server import _registry

        assert isinstance(_registry.gpu_lock, threading.Lock)

    def test_stateless_http_enabled(self):
        """FastMCP instance should have stateless_http=True."""
        assert mcp.settings.stateless_http is True


class TestHealthHandler:
    """Test the health_handler async function."""

    def test_health_handler_returns_json(self):
        """health_handler returns a JSONResponse with expected keys."""
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient

        app = Starlette(
            routes=[Route("/health", health_handler)],
            lifespan=_empty_lifespan,
        )
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "cuda" in data
        assert "models_loaded" in data
        assert "project_count" in data
        assert "uptime_s" in data
        assert data["backend_capabilities"]["concurrent_search_supported"] is True
        assert (
            data["backend_capabilities"]["same_project_search_strategy"] == "serialized"
        )

    def test_health_status_reflects_model_state(self):
        """Without models loaded, status should not be 'ready'.

        Swaps in a fresh, model-less registry for the duration of the
        test and restores the original in finally.
        """
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient

        import vaultspec_rag.server as mod

        from ..service import ServiceRegistry

        orig_registry = mod._registry
        orig_start = mod._start_time

        try:
            mod._registry = ServiceRegistry()
            mod._start_time = 0.0

            app = Starlette(
                routes=[Route("/health", health_handler)],
                lifespan=_empty_lifespan,
            )
            client = TestClient(app)
            resp = client.get("/health")
            data = resp.json()
            assert data["status"] == "error"
            assert data["models_loaded"] is False
        finally:
            mod._registry = orig_registry
            mod._start_time = orig_start


class TestHealthInfoReduction:
    """SEC-003: Health endpoint does not leak sensitive information."""

    def test_health_no_project_paths(self):
        """Health response must not contain absolute project paths."""
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient

        app = Starlette(
            routes=[Route("/health", health_handler)],
            lifespan=_empty_lifespan,
        )
        client = TestClient(app)
        data = client.get("/health").json()
        assert "projects" not in data
        assert "project_count" in data
        assert isinstance(data["project_count"], int)

    def test_health_no_gpu_name(self):
        """Health response must not contain GPU device name."""
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient

        app = Starlette(
            routes=[Route("/health", health_handler)],
            lifespan=_empty_lifespan,
        )
        client = TestClient(app)
        data = client.get("/health").json()
        assert "gpu_name" not in data

    def test_index_status_no_gpu_name(self):
        """IndexStatus model must not have gpu_name field."""
        status = IndexStatus(
            vault_count=10,
            code_count=50,
            storage_path="/tmp/db",
            target_dir="/tmp/ws",
        )
        assert not hasattr(status, "gpu_name") or "gpu_name" not in status.model_fields


class TestMultiProjectWatcher:
    """Module-level watcher state supports multiple projects (PHASE3-001)."""

    def test_watcher_tasks_is_dict(self):
        from ..server import _watcher_tasks

        assert isinstance(_watcher_tasks, dict)

    def test_watcher_stops_is_dict(self):
        from ..server import _watcher_stops

        assert isinstance(_watcher_stops, dict)

    def test_stop_all_watchers_callable(self):
        from ..server import _stop_all_watchers

        assert callable(_stop_all_watchers)

    def test_stop_watcher_callable(self):
        from ..server import _stop_watcher

        assert callable(_stop_watcher)

    def test_ensure_watcher_callable(self):
        from ..server import _ensure_watcher

        assert callable(_ensure_watcher)

    def test_stop_all_on_empty_is_safe(self):
        """Calling _stop_all_watchers with no running watchers is a no-op."""
        from ..server import _stop_all_watchers

        _stop_all_watchers()  # must not raise

    def test_stop_watcher_nonexistent_root_is_safe(self, tmp_path):
        """Stopping a watcher for a root that was never started is safe."""
        from ..server import _stop_watcher

        _stop_watcher(tmp_path)  # must not raise


class TestAdminTools:
    """list_projects and evict_project MCP admin tools."""

    def test_list_projects_empty_registry(self) -> None:
        """With no slots, returns empty projects and config-matched caps."""
        from vaultspec_rag.mcp._admin_tools import list_projects
        from vaultspec_rag.server import _registry

        from ..config import get_config

        # Force an empty registry.
        with _registry._lock:
            roots = list(_registry._projects.keys())
        for r in roots:
            _registry.close_project(r)

        result = _run(list_projects())
        assert result["projects"] == []
        cfg = get_config()
        assert result["max_projects"] == cfg.service_max_projects
        assert result["idle_ttl_seconds"] == float(cfg.service_idle_ttl_seconds)

    def test_evict_project_unknown_returns_not_found(self, tmp_path) -> None:
        from vaultspec_rag.mcp._admin_tools import evict_project

        result = _run(evict_project(str(tmp_path / "never-seen")))
        assert result == {"evicted": False, "reason": "not_found"}

    def test_list_projects_help_tool_registered(self) -> None:
        tools = _run(mcp.list_tools())
        names = {t.name for t in tools}
        assert "list_projects" in names
        assert "evict_project" in names


class TestRegistryFullErrorShape:
    """MCP tool handlers translate RegistryFullError into a structured dict."""

    def test_error_dict_shape(self) -> None:
        """_registry_full_error_dict contains every ADR D4 key."""
        from ..server import (
            _registry,
            _registry_full_error_dict,
        )
        from ..service import RegistryFullError

        exc = RegistryFullError(_registry.max_projects)
        result = _registry_full_error_dict(exc)
        assert result["ok"] is False
        assert result["error"] == "registry_full"
        assert result["max_projects"] == _registry.max_projects
        assert isinstance(result["busy_projects"], list)
        assert result["message"]  # non-empty message

    def test_local_store_locked_error_dict_shape(self, tmp_path) -> None:
        """Local Qdrant lock contention returns an actionable MCP payload."""
        from ..server import _local_store_locked_error_dict
        from ..store import VaultStoreLockedError

        db_path = tmp_path / ".vault" / "data" / "search-data" / "qdrant"
        exc = VaultStoreLockedError(str(db_path))
        result = _local_store_locked_error_dict(exc)

        assert result["ok"] is False
        assert result["error"] == "local_store_locked"
        assert result["db_path"] == str(db_path)
        caps = result["backend_capabilities"]
        assert caps["backend"] == "qdrant-local"
        assert caps["concurrent_search_supported"] is True
        assert caps["same_project_search_strategy"] == "serialized"
        assert caps["cross_project_search_strategy"] == "parallel"
        assert caps["local_storage_process_model"] == "exclusive"
        assert "resident vaultspec-rag service" in result["message"]

    def test_ensure_watcher_uses_peek_project(self) -> None:
        """_ensure_watcher must not bump ref_count on the slot.

        Reads the module source directly so the assertion is robust to
        whether the watcher task is running.
        """
        import inspect

        from .. import server

        source = inspect.getsource(server._ensure_watcher)
        assert "_registry.peek_project" in source
        assert "_registry.get_project" not in source


class TestMcpPathRewrite:
    """Bare ``/mcp`` is rewritten to ``/mcp/`` in-process - no 307 hop."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_main_uses_path_rewriting_wrapper(self):
        """Regression guard: main() must hand the wrapper to uvicorn.run.

        Without the wrapper, Starlette's ``Mount("/mcp")`` issues a 307
        redirect on the bare path, costing every MCP call a round-trip
        and breaking the documented client URL. The function-source
        check is cheap, stable, and survives refactors that keep the
        wrapper-passing intent.
        """
        import inspect

        from .. import server

        source = inspect.getsource(server.main)
        assert "_mcp_no_redirect" in source, (
            "main() lost the path-rewriting wrapper; /mcp will 307-redirect"
        )
        # The wrapper must actually be what's handed to uvicorn - not
        # just defined and ignored.
        assert "uvicorn.run(\n                _mcp_no_redirect" in source

    def test_path_rewrite_logic(self):
        """The ASGI rewrite promotes bare /mcp to /mcp/, leaves other paths."""
        captured: dict[str, dict[str, object]] = {}

        async def _stub_app(scope, _receive, _send):
            captured["scope"] = scope

        async def _wrapper(scope, receive, send):
            if scope["type"] == "http" and scope.get("path") == "/mcp":
                scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
            await _stub_app(scope, receive, send)

        # Bare /mcp gets rewritten.
        asyncio.run(
            _wrapper(
                {"type": "http", "path": "/mcp", "raw_path": b"/mcp"},
                lambda: None,
                lambda _m: None,
            ),
        )
        assert captured["scope"]["path"] == "/mcp/"
        assert captured["scope"]["raw_path"] == b"/mcp/"

        # /mcp/ passes through unchanged.
        asyncio.run(
            _wrapper(
                {"type": "http", "path": "/mcp/", "raw_path": b"/mcp/"},
                lambda: None,
                lambda _m: None,
            ),
        )
        assert captured["scope"]["path"] == "/mcp/"

        # /health passes through unchanged.
        asyncio.run(
            _wrapper(
                {"type": "http", "path": "/health", "raw_path": b"/health"},
                lambda: None,
                lambda _m: None,
            ),
        )
        assert captured["scope"]["path"] == "/health"


class TestDaemonLifecycleHelpers:
    """_lifecycle_log + _heartbeat_tick_sync + cleanup helpers."""

    def test_lifecycle_log_emits_warning_with_structured_format(
        self,
        caplog,
    ) -> None:
        from ..server import _lifecycle_log

        with caplog.at_level("WARNING", logger="vaultspec_rag.server"):
            _lifecycle_log("startup", pid=42, port=8766)

        records = [r for r in caplog.records if r.name == "vaultspec_rag.server"]
        assert records, "lifecycle log did not surface on the expected logger"
        rec = records[-1]
        assert rec.levelname == "WARNING"
        rendered = rec.getMessage()
        assert "service.lifecycle" in rendered
        assert "event=startup" in rendered
        assert "pid=42" in rendered
        assert "port=8766" in rendered

    def test_heartbeat_tick_sync_no_status_file(self, tmp_path, monkeypatch) -> None:
        """Missing service.json → no-op (no exception, no file created)."""
        from .. import server

        monkeypatch.setattr(
            server,
            "_status_file_path",
            lambda: tmp_path / "service.json",
        )
        # Should not raise and should not create the file.
        server._heartbeat_tick_sync()
        assert not (tmp_path / "service.json").exists()

    def test_heartbeat_tick_sync_writes_last_heartbeat(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Existing service.json gets last_heartbeat merged in atomically."""
        from datetime import UTC, datetime

        from .. import server

        sf = tmp_path / "service.json"
        sf.write_text(
            json.dumps({"pid": 1, "port": 2, "started_at": "x"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(server, "_status_file_path", lambda: sf)

        server._heartbeat_tick_sync()

        data = json.loads(sf.read_text(encoding="utf-8"))
        assert data["pid"] == 1
        assert data["port"] == 2
        assert data["started_at"] == "x"
        assert "last_heartbeat" in data
        # Parses as a valid ISO-8601 timestamp.
        ts = datetime.fromisoformat(data["last_heartbeat"])
        assert ts.tzinfo is not None
        delta = (datetime.now(UTC) - ts).total_seconds()
        assert -1 < delta < 5

    def test_heartbeat_tick_sync_merges_service_token(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Non-empty _SERVICE_TOKEN gets written into the heartbeat.

        Empty token (initial state before service_lifespan fires) is
        skipped so a stale token from a previous daemon does not get
        overwritten with empty.
        """
        from .. import server

        sf = tmp_path / "service.json"
        sf.write_text(
            json.dumps({"pid": 1, "port": 2, "started_at": "x"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(server, "_status_file_path", lambda: sf)
        monkeypatch.setattr(server, "_SERVICE_TOKEN", "deadbeef" * 4)

        server._heartbeat_tick_sync()

        data = json.loads(sf.read_text(encoding="utf-8"))
        assert data["service_token"] == "deadbeef" * 4

    def test_heartbeat_tick_sync_skips_empty_token(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Empty _SERVICE_TOKEN must not overwrite an existing token."""
        from .. import server

        sf = tmp_path / "service.json"
        # Simulate a service.json that already has a token (e.g.
        # written by a previous tick that fired before this guard
        # check was introduced).
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
        monkeypatch.setattr(server, "_status_file_path", lambda: sf)
        monkeypatch.setattr(server, "_SERVICE_TOKEN", "")

        server._heartbeat_tick_sync()

        data = json.loads(sf.read_text(encoding="utf-8"))
        # Token preserved - empty token guard prevents the overwrite.
        assert data["service_token"] == "previous-token"

    def test_unlink_status_file_silently_missing_is_noop(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Calling cleanup with no file does not raise."""
        from .. import server

        monkeypatch.setattr(
            server,
            "_status_file_path",
            lambda: tmp_path / "nope.json",
        )
        server._unlink_status_file_silently()  # no exception

    def test_record_shutdown_is_idempotent(
        self,
        tmp_path,
        monkeypatch,
        caplog,
    ) -> None:
        """First call wins; subsequent calls do not log or unlink twice."""
        from .. import server

        sf = tmp_path / "service.json"
        sf.write_text(json.dumps({"pid": 1, "port": 2}), encoding="utf-8")
        monkeypatch.setattr(server, "_status_file_path", lambda: sf)
        # Reset the module-level guard so this test is isolated.
        monkeypatch.setattr(server, "_shutdown_recorded", False)

        with caplog.at_level("WARNING", logger="vaultspec_rag.server"):
            server._record_shutdown("test-first")
            assert not sf.exists()
            server._record_shutdown("test-second")

        first = [
            r
            for r in caplog.records
            if r.name == "vaultspec_rag.server"
            and "reason=test-first" in r.getMessage()
        ]
        second = [
            r
            for r in caplog.records
            if r.name == "vaultspec_rag.server"
            and "reason=test-second" in r.getMessage()
        ]
        assert first, "first shutdown should log"
        assert not second, "second shutdown should be suppressed"
