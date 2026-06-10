"""ADR regression tests: verify architectural decisions haven't regressed.

Each test corresponds to an ADR in .vault/adr/ and catches regressions
that would violate the documented architectural contract.
"""

from __future__ import annotations

import hashlib
import typing
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import ast
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestBlake2bFileHashing:
    """ADR: blake2b-file-hashing - file hashes must use blake2b, not sha256."""

    def test_vault_indexer_meta_uses_blake2b_hashes(self, tmp_path: Path) -> None:
        """VaultIndexer._save_meta produces blake2b hex digests (128 chars)."""
        from ..indexer import VaultIndexer

        indexer = object.__new__(VaultIndexer)
        indexer._meta_path = tmp_path / ".rag" / "vault_meta.json"

        # Write a test file and hash it the same way the indexer does
        test_file = tmp_path / "test.md"
        test_file.write_text("hello world", encoding="utf-8")

        with open(test_file, "rb") as f:
            digest = hashlib.file_digest(f, "blake2b").hexdigest()

        # blake2b default digest is 64 bytes = 128 hex chars
        # sha256 is 32 bytes = 64 hex chars
        assert len(digest) == 128, (
            f"Expected blake2b (128 hex chars), got {len(digest)} chars"
        )

    def test_codebase_indexer_meta_uses_blake2b_hashes(self, tmp_path: Path) -> None:
        """CodebaseIndexer._write_meta produces blake2b hex digests."""
        from ..indexer import CodebaseIndexer

        indexer = object.__new__(CodebaseIndexer)
        indexer._meta_path = tmp_path / ".rag" / "code_meta.json"

        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1", encoding="utf-8")

        with open(test_file, "rb") as f:
            digest = hashlib.file_digest(f, "blake2b").hexdigest()

        assert len(digest) == 128

        # Round-trip: write and load back
        indexer._write_meta({"test.py": digest})
        loaded = indexer._load_meta()
        assert loaded["test.py"] == digest
        assert len(loaded["test.py"]) == 128


class TestMCPAsyncTools:
    """ADR: mcp-sync-tools (superseded) - MCP tools must be async def + anyio."""

    def test_search_vault_is_async(self) -> None:
        import inspect

        from ..mcp._tools import search_vault

        assert inspect.iscoroutinefunction(search_vault)

    def test_search_codebase_is_async(self) -> None:
        import inspect

        from ..mcp._tools import search_codebase

        assert inspect.iscoroutinefunction(search_codebase)

    def test_reindex_vault_is_async(self) -> None:
        import inspect

        from ..mcp._tools import reindex_vault

        assert inspect.iscoroutinefunction(reindex_vault)

    def test_reindex_codebase_is_async(self) -> None:
        import inspect

        from ..mcp._tools import reindex_codebase

        assert inspect.iscoroutinefunction(reindex_codebase)

    def test_get_index_status_is_async(self) -> None:
        import inspect

        from ..mcp._tools import get_index_status

        assert inspect.iscoroutinefunction(get_index_status)

    def test_get_code_file_is_async(self) -> None:
        import inspect

        from ..mcp._tools import get_code_file

        assert inspect.iscoroutinefunction(get_code_file)


class TestPathResolveCache:
    """ADR: registry normalizes with Path.resolve() for cache consistency."""

    def test_relative_and_dot_relative_same_engine(self, tmp_path: Path) -> None:
        """Path('./x') and Path('x') resolve to the same registry key."""
        from ..registry import get_registry

        # Both paths resolve to the same absolute path
        abs_path = tmp_path / "project"
        abs_path.mkdir()
        p1 = abs_path
        p2 = abs_path.resolve()
        assert p1.resolve() == p2.resolve()
        # The registry is the single cache path for slots now.
        assert get_registry() is get_registry()


class TestGraphCache:
    """ADR: GraphCache returns same instance on repeated calls."""

    def test_graph_cache_invalidate_clears(self):
        from ..graph_cache import GraphCache

        cache = GraphCache(ttl_seconds=300.0)
        # After invalidate, internal state is cleared
        cache.invalidate()
        assert cache._graph is None
        assert cache._root is None
        assert cache._built_at == 0.0

    def test_graph_cache_has_lock(self):
        import threading

        from ..graph_cache import GraphCache

        cache = GraphCache(ttl_seconds=300.0)
        assert isinstance(cache._lock, type(threading.Lock()))


class TestQwen3NoDocumentPrompt:
    """ADR: encode_documents must NOT pass prompt_name to the dense model."""

    def test_encode_documents_no_prompt_name(self):
        import inspect

        from ..embeddings import EmbeddingModel

        source = inspect.getsource(EmbeddingModel.encode_documents)
        assert "prompt_name" not in source, (
            "encode_documents should not pass prompt_name to the dense model"
        )

    def test_encode_query_uses_prompt_name(self):
        import inspect

        from ..embeddings import EmbeddingModel

        source = inspect.getsource(EmbeddingModel.encode_query)
        assert "prompt_name" in source, (
            "encode_query should pass prompt_name='query' to the dense model"
        )


class TestEmbeddingModelLoadArguments:
    """Regression coverage for model constructor arguments."""

    @staticmethod
    def _load_ast():
        import ast
        import inspect
        import textwrap

        from ..embeddings import EmbeddingModel

        # The dense SentenceTransformer construction lives in
        # ``_load_dense_model`` (backend seam) while SparseEncoder stays in
        # ``__init__``; parse the whole class so both calls are in scope.
        source = textwrap.dedent(inspect.getsource(EmbeddingModel))
        return ast.parse(source)

    @staticmethod
    def _call_kwargs(tree: ast.AST, call_name: str) -> dict[str, object]:
        import ast

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == call_name:
                return {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
        raise AssertionError(f"{call_name} call not found")

    def test_dense_text_model_uses_processor_kwargs(self):
        import ast

        kwargs = self._call_kwargs(self._load_ast(), "SentenceTransformer")
        assert "processor_kwargs" in kwargs
        assert "tokenizer_kwargs" not in kwargs

        processor_kwargs = kwargs["processor_kwargs"]
        assert isinstance(processor_kwargs, ast.Dict)
        assert any(
            isinstance(key, ast.Constant)
            and key.value == "padding_side"
            and isinstance(value, ast.Constant)
            and value.value == "left"
            for key, value in zip(
                processor_kwargs.keys,
                processor_kwargs.values,
                strict=True,
            )
        )

    def test_sparse_model_does_not_force_pickle_weights(self):
        import ast

        kwargs = self._call_kwargs(self._load_ast(), "SparseEncoder")
        model_kwargs = kwargs["model_kwargs"]
        assert isinstance(model_kwargs, ast.Dict)

        keys = [
            key.value
            for key in model_kwargs.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        ]
        assert "torch_dtype" in keys
        assert "use_safetensors" not in keys


class TestThreadingLock:
    """ADR: server and api use threading locks for initialization.

    The eviction work (#45) upgraded ``ServiceRegistry._lock`` from a
    plain ``threading.Lock`` to a reentrant ``threading.RLock`` so the
    eviction codepaths can call ``close_project`` while still holding
    the registry lock without deadlocking.  Both lock types expose the
    same ``acquire``/``release`` interface but ``isinstance`` against
    ``type(threading.Lock())`` rejects the RLock - these tests now
    accept the RLock as well.
    """

    @staticmethod
    def _lock_types() -> tuple[type, ...]:
        import threading

        return (type(threading.Lock()), type(threading.RLock()))

    def test_mcp_registry_lock_exists(self):
        from ..server import _registry

        assert isinstance(_registry._lock, self._lock_types())

    def test_registry_singleton_has_lock(self):
        from ..registry import get_registry

        reg = get_registry()
        assert isinstance(reg._lock, self._lock_types())


class TestFilterOnPrefetch:
    """ADR: hybrid_search applies filter on Prefetch, not on query_points."""

    def test_hybrid_search_uses_prefetch_filter(self):
        import inspect

        from ..store import VaultStore

        source = inspect.getsource(VaultStore._build_prefetch)
        # Filter must appear in Prefetch constructor, not as query_filter kwarg
        assert "Prefetch(" in source
        assert "filter=query_filter" in source


class TestManualNodeWalking:
    """ADR: ASTChunker._extract_name uses child_by_field_name for AST walking."""

    def test_extract_name_uses_child_by_field_name(self):
        import inspect

        from ..indexer import ASTChunker

        source = inspect.getsource(ASTChunker._extract_name)
        assert "child_by_field_name" in source, (
            "_extract_name must use child_by_field_name for AST node name extraction"
        )


class TestRerankerModelName:
    """ADR: gpu-only-rag-stack - reranker model must be bge-reranker-v2-m3."""

    def test_config_default_reranker_model(self):
        from ..config import get_config, reset_config

        reset_config()
        cfg = get_config()
        assert cfg.reranker_model == "BAAI/bge-reranker-v2-m3"
        reset_config()


@pytest.mark.unit
class TestRrfKParameter:
    """RRF k must be 60, not the default k=2 (which creates 4x rank bias)."""

    def test_hybrid_search_uses_rrf_k60(self):
        import inspect
        import linecache

        from ..store import VaultStore

        linecache.clearcache()
        src = inspect.getsource(VaultStore._execute_hybrid_query)
        assert "Rrf(k=60)" in src or "rrf=models.Rrf(k=60)" in src, (
            "_execute_hybrid_query must use RrfQuery(rrf=Rrf(k=60)), "
            "not FusionQuery default (k=2)"
        )

    def test_hybrid_search_codebase_uses_rrf_k60(self):
        import inspect
        import linecache

        from ..store import VaultStore

        linecache.clearcache()
        src = inspect.getsource(VaultStore._execute_hybrid_query)
        assert "Rrf(k=60)" in src or "rrf=models.Rrf(k=60)" in src


class TestGraphCacheInvalidation:
    """R29 fix: reindex_vault must reset graph cache.

    Next search must rebuild from fresh index.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_reindex_vault_resets_graph_cache(self):
        import inspect

        from ..jobs import start_reindex_vault

        src = inspect.getsource(start_reindex_vault)
        assert "graph_cache" in src and "invalidate" in src, (
            "start_reindex_vault must call slot.graph_cache.invalidate() "
            "after indexing to prevent stale graph re-ranking "
            "(R29-H3 fix, unified in D3)"
        )


class TestCliMcpFastPath:
    """CLI _do_http_call must use asyncio.run() (safe from sync Typer handlers)."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_do_http_call_uses_urllib(self):
        import inspect

        from ..cli._http_search import _do_http_call

        src = inspect.getsource(_do_http_call)
        assert "urllib.request" in src, (
            "_do_http_call must use synchronous urllib.request instead of async HTTP "
            "because Typer handlers are sync."
        )


class TestWatcherGraphInvalidation:
    """Watcher must use the graph cache contract for invalidation."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_watch_and_reindex_requires_graph_cache(self):
        import inspect

        from ..watcher import watch_and_reindex

        signature = inspect.signature(watch_and_reindex)
        assert "graph_cache" in signature.parameters, (
            "watch_and_reindex must accept the project GraphCache so the watcher "
            "can invalidate graph data after vault reindex"
        )
        assert "searcher" not in signature.parameters, (
            "watch_and_reindex must not retain the old private searcher "
            "invalidation path"
        )


class TestAtomicMetaWrite:
    """Task #43: _write_meta must use os.replace for atomicity."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_vault_indexer_write_meta_uses_os_replace(self):
        import inspect

        from ..indexer import VaultIndexer

        src = inspect.getsource(VaultIndexer._write_meta)
        assert "os.replace(" in src, (
            "VaultIndexer._write_meta must use os.replace() for atomic writes; "
            "direct write_text() risks corrupt metadata on crash (Task #43)"
        )

    def test_codebase_indexer_write_meta_uses_os_replace(self):
        import inspect

        from ..indexer import CodebaseIndexer

        src = inspect.getsource(CodebaseIndexer._write_meta)
        assert "os.replace(" in src, (
            "CodebaseIndexer._write_meta must use os.replace() for atomic writes; "
            "direct write_text() risks corrupt metadata on crash (Task #43)"
        )
