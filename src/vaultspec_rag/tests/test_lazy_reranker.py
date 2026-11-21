"""The reranker has one lazy loader, and it loads only under the GPU lock."""

from __future__ import annotations

import ast
import threading
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import pytest

from ..embeddings import LazyReranker

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder


def _loader_call_sites(path: Path) -> list[str]:
    """Name the enclosing ``Class.method`` of every ``load_reranker`` call."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    sites: list[str] = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                visit(child, (*scope, child.name))
                continue
            if isinstance(child, ast.Call):
                func = child.func
                name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else func.attr
                    if isinstance(func, ast.Attribute)
                    else None
                )
                if name == "load_reranker":
                    sites.append(".".join(scope))
            visit(child, scope)

    visit(tree, ())
    return sites


@pytest.mark.unit
def test_only_the_lazy_reranker_calls_the_loader() -> None:
    package = Path(__file__).resolve().parents[1]
    sites = sorted(
        f"{path.relative_to(package).as_posix()}:{site}"
        for path in package.rglob("*.py")
        if "tests" not in path.relative_to(package).parts
        for site in _loader_call_sites(path)
    )
    # Catches a second lazy loader: adding a direct ``load_reranker()`` call
    # to the service or the searcher (as each once had) adds a site here.
    assert sites == ["embeddings.py:LazyReranker.load_locked"]


@pytest.mark.unit
def test_load_locked_refuses_a_caller_without_the_lock() -> None:
    slot = LazyReranker(threading.Lock())

    # The refusal precedes the load, so nothing is cached: a load that ran
    # first would leave a reranker behind.
    with pytest.raises(RuntimeError, match="only while the GPU lock is held"):
        slot.load_locked()
    assert slot.loaded is None


class TestRealLoad:
    """The cache around a real CrossEncoder, loaded from the model cache."""

    pytestmark: ClassVar = [pytest.mark.cuda]

    def test_get_loads_while_the_gpu_lock_is_held(
        self, shared_reranker: CrossEncoder
    ) -> None:
        gpu_lock = threading.Lock()
        held_during_load: list[bool] = []
        slot = LazyReranker(
            gpu_lock, on_load=lambda _loaded: held_during_load.append(gpu_lock.locked())
        )

        try:
            first = slot.get()
            second = slot.get()

            # Catches the load leaving the lock: removing the ``timed_gpu_lock``
            # block from ``get`` makes the precondition in ``load_locked``
            # raise, and a load outside the lock would record ``False`` here.
            assert held_during_load == [True]
            assert first is second is slot.loaded
            assert first is not shared_reranker
            assert not gpu_lock.locked()
        finally:
            slot.clear()

    @pytest.mark.usefixtures("shared_reranker")
    def test_load_runs_on_load_under_the_lock_and_clear_drops_it(self) -> None:
        gpu_lock = threading.Lock()
        observed: list[tuple[object, bool]] = []
        slot = LazyReranker(
            gpu_lock, on_load=lambda r: observed.append((r, gpu_lock.locked()))
        )

        try:
            with gpu_lock:
                loaded = slot.load_locked()

            assert observed == [(loaded, True)]
        finally:
            slot.clear()
        assert slot.loaded is None

    def test_a_preloaded_reranker_is_served_without_loading(
        self, shared_reranker: CrossEncoder
    ) -> None:
        loads: list[object] = []
        slot = LazyReranker(None, shared_reranker, on_load=loads.append)

        # A load would replace the cache and call ``on_load``; the early return
        # does neither.
        assert slot.get() is shared_reranker
        assert slot.loaded is shared_reranker
        assert loads == []
