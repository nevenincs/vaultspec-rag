"""The reranker has one lazy loader, and it loads only under the GPU lock."""

from __future__ import annotations

import ast
import threading
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from .. import embeddings
from ..embeddings import LazyReranker

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

pytestmark = [pytest.mark.unit]


class _Sentinel:
    device = "sentinel"


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


def test_get_loads_while_the_gpu_lock_is_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gpu_lock = threading.Lock()
    held_during_load: list[bool] = []

    def _load() -> CrossEncoder:
        held_during_load.append(gpu_lock.locked())
        return cast("CrossEncoder", _Sentinel())

    monkeypatch.setattr(embeddings, "load_reranker", _load)
    slot = LazyReranker(gpu_lock)

    first = slot.get()
    second = slot.get()

    # Catches the load leaving the lock: removing the ``timed_gpu_lock``
    # block from ``get`` makes the precondition in ``load_locked`` raise, and
    # an unlocked load would record ``False`` here.
    assert held_during_load == [True]
    assert first is second is slot.loaded
    assert not gpu_lock.locked()


def test_load_locked_refuses_a_caller_without_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loads: list[None] = []

    def _load() -> CrossEncoder:
        loads.append(None)
        return cast("CrossEncoder", _Sentinel())

    monkeypatch.setattr(embeddings, "load_reranker", _load)
    slot = LazyReranker(threading.Lock())

    with pytest.raises(RuntimeError, match="only while the GPU lock is held"):
        slot.load_locked()
    assert loads == []
    assert slot.loaded is None


def test_load_runs_on_load_under_the_lock_and_clear_drops_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gpu_lock = threading.Lock()
    observed: list[tuple[object, bool]] = []
    monkeypatch.setattr(
        embeddings, "load_reranker", lambda: cast("CrossEncoder", _Sentinel())
    )
    slot = LazyReranker(
        gpu_lock, on_load=lambda r: observed.append((r, gpu_lock.locked()))
    )

    with gpu_lock:
        loaded = slot.load_locked()

    assert observed == [(loaded, True)]
    slot.clear()
    assert slot.loaded is None


def test_a_preloaded_reranker_is_served_without_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _load() -> CrossEncoder:
        raise AssertionError("a pre-loaded reranker must not load again")

    monkeypatch.setattr(embeddings, "load_reranker", _load)
    preloaded = cast("CrossEncoder", _Sentinel())

    assert LazyReranker(None, preloaded).get() is preloaded
