"""Unit tests for the MCP server module."""

from __future__ import annotations

import asyncio

import pytest

from vaultspec_rag.mcp_server import (
    IndexResponse,
    IndexStatus,
    SearchResponse,
    SearchResultItem,
    analyze_feature,
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
            "search_all",
            "get_index_status",
            "get_code_file",
            "reindex_vault",
            "reindex_codebase",
        }
        assert expected == tool_names

    def test_tool_count(self):
        tools = _run(mcp.list_tools())
        assert len(tools) == 7

    def test_all_tools_have_descriptions(self):
        tools = _run(mcp.list_tools())
        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"


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
        # Create a symlink inside workspace pointing to parent dir
        link_path = tmp_path / "escape_link"
        try:
            os.symlink(tmp_path.parent, link_path)
        except OSError:
            pytest.fail("Cannot create symlink — test requires symlink support")
        # Resolve follows the symlink — result is outside workspace
        full_path = (root_resolved / "escape_link" / "other_file.txt").resolve()
        assert not full_path.is_relative_to(root_resolved)


class TestClampTopK:
    """Test the _clamp_top_k helper."""

    def test_clamp_within_range(self):
        from vaultspec_rag.mcp_server import _clamp_top_k

        assert _clamp_top_k(5) == 5

    def test_clamp_below_minimum(self):
        from vaultspec_rag.mcp_server import _clamp_top_k

        assert _clamp_top_k(0) == 1
        assert _clamp_top_k(-10) == 1

    def test_clamp_above_maximum(self):
        from vaultspec_rag.mcp_server import _clamp_top_k

        assert _clamp_top_k(200) == 100
        assert _clamp_top_k(101) == 100

    def test_clamp_boundary_values(self):
        from vaultspec_rag.mcp_server import _clamp_top_k

        assert _clamp_top_k(1) == 1
        assert _clamp_top_k(100) == 100


class TestGetCompFailureCaching:
    """Test that get_comp() caches initialization failures."""

    def test_comp_error_cached(self):
        """After a failed init, subsequent calls raise immediately."""
        import vaultspec_rag.mcp_server as mod

        # Save original state
        orig_comp = mod._comp
        orig_error = mod._comp_error

        try:
            # Simulate a prior failure
            mod._comp = None
            mod._comp_error = RuntimeError("GPU not available")

            with pytest.raises(RuntimeError, match="previously failed"):
                mod.get_comp()
        finally:
            # Restore original state
            mod._comp = orig_comp
            mod._comp_error = orig_error

    def test_comp_lock_exists(self):
        """get_comp uses a threading.Lock for thread safety."""
        import threading

        import vaultspec_rag.mcp_server as mod

        assert isinstance(mod._comp_lock, threading.Lock)


class TestRagComponentsDataclass:
    """Test that RagComponents is a proper dataclass."""

    def test_is_dataclass(self):
        import dataclasses

        from vaultspec_rag.mcp_server import RagComponents

        assert dataclasses.is_dataclass(RagComponents)

    def test_has_expected_fields(self):
        import dataclasses

        from vaultspec_rag.mcp_server import RagComponents

        field_names = {f.name for f in dataclasses.fields(RagComponents)}
        expected = {
            "store",
            "model",
            "searcher",
            "vault_indexer",
            "code_indexer",
            "root_dir",
        }
        assert expected == field_names
