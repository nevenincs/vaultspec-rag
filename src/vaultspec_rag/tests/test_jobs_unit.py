"""Unit tests for ``jobs.py``.

Covers (no GPU required):
- Both ``_bg_run`` closures in ``start_reindex_vault`` and
  ``start_reindex_codebase`` call ``load_model()`` before ``lease()``
  (AST structural assertion — regression guard for the fix).
- ``ServiceRegistry.load_model()`` is idempotent: a second call when
  ``_model`` is already set returns immediately without touching CUDA
  (proven by injecting a sentinel and asserting it is unchanged).
- ``jobs`` module-level helpers (``record_start``/``record_finish``/
  ``snapshot``) are exercised to ensure basic lifecycle correctness.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import TYPE_CHECKING, cast

import pytest

from ..jobs import record_finish, record_start, reset, snapshot
from ..service import ServiceRegistry

if TYPE_CHECKING:
    from ..embeddings import EmbeddingModel

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# AST regression guard
# ---------------------------------------------------------------------------


def _function_node_named(  # pyright: ignore[reportUnusedFunction]
    tree: ast.Module, name: str
) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function '{name}' not found in AST")


def _call_names_in_order(func_node: ast.FunctionDef) -> list[str]:
    """Return the dotted call names in textual order within *func_node*."""
    names: list[str] = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            match node.func:
                case ast.Attribute(attr=attr):
                    names.append(attr)
                case ast.Name(id=name):
                    names.append(name)
                case _:
                    pass
    return names


def _parse_jobs_module() -> ast.Module:
    import vaultspec_rag.jobs as jobs_mod

    src = inspect.getsource(jobs_mod)
    return ast.parse(textwrap.dedent(src))


class TestBgRunLoadModelBeforeLease:
    """AST-level guard: load_model() must precede lease() in both closures."""

    def _find_bg_run_nodes(self, tree: ast.Module) -> list[ast.FunctionDef]:
        return [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_bg_run"
        ]

    def test_two_bg_run_closures_exist(self) -> None:
        tree = _parse_jobs_module()
        nodes = self._find_bg_run_nodes(tree)
        assert len(nodes) == 2, (
            f"Expected exactly 2 _bg_run closures, found {len(nodes)}"
        )

    def test_load_model_before_lease_in_vault_bg_run(self) -> None:
        tree = _parse_jobs_module()
        nodes = self._find_bg_run_nodes(tree)
        # First _bg_run belongs to start_reindex_vault
        calls = _call_names_in_order(nodes[0])
        assert "load_model" in calls, "_bg_run (vault) must call load_model()"
        assert "lease" in calls, "_bg_run (vault) must call lease()"
        load_idx = calls.index("load_model")
        lease_idx = calls.index("lease")
        assert load_idx < lease_idx, (
            f"load_model() (pos {load_idx}) must appear before lease() "
            f"(pos {lease_idx}) in _bg_run (vault)"
        )

    def test_load_model_before_lease_in_codebase_bg_run(self) -> None:
        tree = _parse_jobs_module()
        nodes = self._find_bg_run_nodes(tree)
        # Second _bg_run belongs to start_reindex_codebase
        calls = _call_names_in_order(nodes[1])
        assert "load_model" in calls, "_bg_run (code) must call load_model()"
        assert "lease" in calls, "_bg_run (code) must call lease()"
        load_idx = calls.index("load_model")
        lease_idx = calls.index("lease")
        assert load_idx < lease_idx, (
            f"load_model() (pos {load_idx}) must appear before lease() "
            f"(pos {lease_idx}) in _bg_run (code)"
        )


# ---------------------------------------------------------------------------
# load_model() idempotency — no GPU needed
# ---------------------------------------------------------------------------


class TestLoadModelIdempotency:
    """load_model() is a no-op when _model is already set."""

    def test_second_call_does_not_overwrite_existing_model(self) -> None:
        """Inject a sentinel into _model; second load_model() must leave it."""
        reg = ServiceRegistry()
        sentinel = cast("EmbeddingModel", object())
        # Bypass the real EmbeddingModel construction by injecting directly.
        reg._model = sentinel
        reg.load_model()  # must return without touching _model
        assert reg._model is sentinel, (
            "load_model() must be idempotent: it replaced the existing model"
        )

    def test_model_property_raises_before_load(self) -> None:
        reg = ServiceRegistry()
        with pytest.raises(RuntimeError, match="call load_model\\(\\) first"):
            _ = reg.model

    def test_model_property_succeeds_after_sentinel_inject(self) -> None:
        reg = ServiceRegistry()
        sentinel = cast("EmbeddingModel", object())
        reg._model = sentinel
        assert reg.model is sentinel


# ---------------------------------------------------------------------------
# jobs module basic lifecycle
# ---------------------------------------------------------------------------


class TestJobsLifecycle:
    def setup_method(self) -> None:
        reset()

    def test_record_start_returns_id(self) -> None:
        job_id = record_start("vault", "tool")
        assert isinstance(job_id, str) and len(job_id) == 32

    def test_snapshot_contains_started_record(self) -> None:
        job_id = record_start("vault", "tool")
        records = snapshot()
        ids = [r["id"] for r in records]
        assert job_id in ids

    def test_record_finish_transitions_to_done(self) -> None:
        job_id = record_start("code", "watcher")
        record_finish(job_id, result="ok")
        records = {r["id"]: r for r in snapshot()}
        assert records[job_id]["phase"] == "done"

    def test_record_finish_transitions_to_error(self) -> None:
        job_id = record_start("vault", "watcher")
        record_finish(job_id, error="boom")
        records = {r["id"]: r for r in snapshot()}
        assert records[job_id]["phase"] == "error"
        assert records[job_id]["result"] == "boom"

    def test_snapshot_is_newest_first(self) -> None:
        id1 = record_start("vault", "tool")
        id2 = record_start("code", "tool")
        ids = [r["id"] for r in snapshot()]
        assert ids.index(id2) < ids.index(id1)
