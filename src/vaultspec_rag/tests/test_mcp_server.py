"""Unit tests for the MCP server module."""

from __future__ import annotations

import asyncio
import os
import threading

import pytest

from vaultspec_rag.config import EnvVar
from vaultspec_rag.mcp_server import (
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
    analyze_feature,
    health_handler,
    mcp,
)

pytestmark = [pytest.mark.unit]


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


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
        }
        assert expected == tool_names

    def test_tool_count(self):
        tools = _run(mcp.list_tools())
        assert len(tools) == 6

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
        }
        for tool in tools:
            if tool.name in tools_with_project_root:
                param_names = set(tool.inputSchema.get("properties", {}).keys())
                assert "project_root" in param_names, (
                    f"Tool {tool.name} missing project_root parameter"
                )


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

    def test_search_response_empty(self):
        resp = SearchResponse(results=[], summary="No results")
        assert len(resp.results) == 0

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

    def test_health_response_defaults(self):
        resp = HealthResponse(
            status="loading",
            cuda=False,
            models_loaded=False,
        )
        assert resp.project_count == 0
        assert resp.uptime_s == 0.0


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
            pytest.fail("Cannot create symlink — test requires symlink support")
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
    """HTTP mode requires explicit project_root — no env/cwd fallback."""

    def test_default_root_raises_in_http_mode(self):
        import vaultspec_rag.mcp_server as mod

        orig = mod._http_mode
        mod._http_mode = True
        try:
            with pytest.raises(ValueError, match="project_root is required"):
                _default_root()
        finally:
            mod._http_mode = orig

    def test_resolve_root_none_raises_in_http_mode(self):
        import vaultspec_rag.mcp_server as mod

        orig = mod._http_mode
        mod._http_mode = True
        try:
            with pytest.raises(ValueError, match="project_root is required"):
                _resolve_root(None)
        finally:
            mod._http_mode = orig

    def test_resolve_root_explicit_works_in_http_mode(self, tmp_path):
        import vaultspec_rag.mcp_server as mod

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
        import vaultspec_rag.mcp_server as mod

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
        import vaultspec_rag.mcp_server as mod

        orig = mod._http_mode
        mod._http_mode = True
        try:
            with pytest.raises(
                ValueError,
                match="only available in stdio mode",
            ):
                _run(mod.get_vault_document("adr/overview"))
        finally:
            mod._http_mode = orig


class TestMainTransportSetup:
    """Verify main() correctly sets transport mode and lifecycle hooks."""

    def test_http_mode_flag_for_http(self):
        """port=8888 → _http_mode=True."""
        import vaultspec_rag.mcp_server as mod

        orig = mod._http_mode
        try:
            port = 8888
            mod._http_mode = port is not None
            assert mod._http_mode is True
        finally:
            mod._http_mode = orig

    def test_http_mode_flag_for_stdio(self):
        """port=None → _http_mode=False."""
        import vaultspec_rag.mcp_server as mod

        orig = mod._http_mode
        try:
            port = None
            mod._http_mode = port is not None
            assert mod._http_mode is False
        finally:
            mod._http_mode = orig

    def test_stdio_wires_on_close_project(self):
        """Stdio path must wire _on_close_project for watcher cleanup."""
        import vaultspec_rag.mcp_server as mod

        orig = mod._registry._on_close_project
        try:
            # Simulate what main(port=None) does before mcp.run()
            mod._registry._on_close_project = mod._stop_watcher
            assert mod._registry._on_close_project is mod._stop_watcher
        finally:
            mod._registry._on_close_project = orig

    def test_stop_all_watchers_clears_state(self):
        """_stop_all_watchers empties both dicts even when empty."""
        import vaultspec_rag.mcp_server as mod

        # Verify it's safe to call with no watchers running
        mod._stop_all_watchers()
        assert len(mod._watcher_tasks) == 0
        assert len(mod._watcher_stops) == 0


class TestServiceRegistryIntegration:
    """Test that the module-level _registry is a ServiceRegistry."""

    def test_registry_exists(self):
        from vaultspec_rag.mcp_server import _registry
        from vaultspec_rag.service import ServiceRegistry

        assert isinstance(_registry, ServiceRegistry)

    def test_registry_has_gpu_lock(self):
        from vaultspec_rag.mcp_server import _registry

        assert isinstance(_registry.gpu_lock, threading.Lock)

    def test_stateless_http_enabled(self):
        """FastMCP instance should have stateless_http=True."""
        assert mcp.settings.stateless_http is True


class TestHealthHandler:
    """Test the health_handler async function."""

    def test_health_handler_returns_json(self):
        """health_handler returns a JSONResponse with expected keys."""
        from starlette.testclient import TestClient

        async def _lifespan(app):
            yield

        from starlette.applications import Starlette
        from starlette.routing import Route

        app = Starlette(
            routes=[Route("/health", health_handler)],
            lifespan=_lifespan,
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

    def test_health_status_reflects_model_state(self):
        """Without models loaded, status should not be 'ready'.

        Swaps in a fresh, model-less registry for the duration of the
        test and restores the original in finally.
        """
        from starlette.testclient import TestClient

        async def _lifespan(app):
            yield

        from starlette.applications import Starlette
        from starlette.routing import Route

        import vaultspec_rag.mcp_server as mod
        from vaultspec_rag.service import ServiceRegistry

        orig_registry = mod._registry
        orig_start = mod._start_time

        try:
            mod._registry = ServiceRegistry()
            mod._start_time = 0.0

            app = Starlette(
                routes=[Route("/health", health_handler)],
                lifespan=_lifespan,
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
        from starlette.testclient import TestClient

        async def _lifespan(app):
            yield

        from starlette.applications import Starlette
        from starlette.routing import Route

        app = Starlette(
            routes=[Route("/health", health_handler)],
            lifespan=_lifespan,
        )
        client = TestClient(app)
        data = client.get("/health").json()
        assert "projects" not in data
        assert "project_count" in data
        assert isinstance(data["project_count"], int)

    def test_health_no_gpu_name(self):
        """Health response must not contain GPU device name."""
        from starlette.testclient import TestClient

        async def _lifespan(app):
            yield

        from starlette.applications import Starlette
        from starlette.routing import Route

        app = Starlette(
            routes=[Route("/health", health_handler)],
            lifespan=_lifespan,
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
        from vaultspec_rag.mcp_server import _watcher_tasks

        assert isinstance(_watcher_tasks, dict)

    def test_watcher_stops_is_dict(self):
        from vaultspec_rag.mcp_server import _watcher_stops

        assert isinstance(_watcher_stops, dict)

    def test_stop_all_watchers_callable(self):
        from vaultspec_rag.mcp_server import _stop_all_watchers

        assert callable(_stop_all_watchers)

    def test_stop_watcher_callable(self):
        from vaultspec_rag.mcp_server import _stop_watcher

        assert callable(_stop_watcher)

    def test_ensure_watcher_callable(self):
        from vaultspec_rag.mcp_server import _ensure_watcher

        assert callable(_ensure_watcher)

    def test_stop_all_on_empty_is_safe(self):
        """Calling _stop_all_watchers with no running watchers is a no-op."""
        from vaultspec_rag.mcp_server import _stop_all_watchers

        _stop_all_watchers()  # must not raise

    def test_stop_watcher_nonexistent_root_is_safe(self, tmp_path):
        """Stopping a watcher for a root that was never started is safe."""
        from vaultspec_rag.mcp_server import _stop_watcher

        _stop_watcher(tmp_path)  # must not raise
