"""Profiling probe pytest plugin: attributes wall time to infrastructure causes.

Loaded explicitly with ``-p perf_probe``. Counts and times, per test:

- socket connects (count + blocked seconds)
- ``time.sleep`` (count + seconds)
- subprocess spawns (count + argv head) and in-process waits on them
- sentence-transformers model constructions (dense/sparse/cross-encoder)
- ``EmbeddingModel`` construction
- indexing entry points (vault/codebase/document full_index)
- GPU forward entry points (encode + rerank predict)

Writes one JSON line per test to the path in ``PERF_PROBE_OUT`` (defaults to
``perf_probe.jsonl`` in the invocation directory), and a session aggregate
line at the end. Measurement only: every wrapper calls straight through.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from typing import Any

import pytest

_LOCK = threading.Lock()
_COUNTS: dict[str, list[float]] = {}
_EVENTS: list[dict[str, Any]] = []
_CURRENT_NODE: list[str] = ["<session>"]
_WRAPPED: set[str] = set()
_OUT_PATH = os.environ.get("PERF_PROBE_OUT", "perf_probe.jsonl")
_SESSION_T0 = time.perf_counter()


def _add(name: str, seconds: float) -> None:
    with _LOCK:
        cell = _COUNTS.setdefault(name, [0, 0.0])
        cell[0] += 1
        cell[1] += seconds


def _snapshot() -> dict[str, tuple[float, float]]:
    with _LOCK:
        return {k: (v[0], v[1]) for k, v in _COUNTS.items()}


def _record_event(kind: str, **payload: Any) -> None:
    with _LOCK:
        _EVENTS.append(
            {
                "kind": kind,
                "node": _CURRENT_NODE[-1],
                "t": time.perf_counter() - _SESSION_T0,
                **payload,
            }
        )


def _wrap_timed(obj: Any, attr: str, name: str, *, event: bool = False) -> None:
    key = (
        f"{getattr(obj, '__module__', '?')}.{getattr(obj, '__qualname__', obj)}.{attr}"
    )
    if key in _WRAPPED:
        return
    orig = getattr(obj, attr)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        t0 = time.perf_counter()
        try:
            return orig(*args, **kwargs)
        finally:
            dt = time.perf_counter() - t0
            _add(name, dt)
            if event:
                _record_event(name, seconds=round(dt, 4))

    setattr(obj, attr, wrapper)
    _WRAPPED.add(key)


def _install_base_hooks() -> None:
    _wrap_timed(socket.socket, "connect", "socket_connect")
    _wrap_timed(socket.socket, "connect_ex", "socket_connect_ex")
    _wrap_timed(time, "sleep", "sleep")

    orig_init = subprocess.Popen.__init__

    def popen_init(self: subprocess.Popen[Any], *args: Any, **kwargs: Any) -> None:
        t0 = time.perf_counter()
        argv = args[0] if args else kwargs.get("args")
        try:
            orig_init(self, *args, **kwargs)
        finally:
            dt = time.perf_counter() - t0
            _add("popen_spawn", dt)
            head: list[str] = []
            if isinstance(argv, (list, tuple)):
                head = [str(a) for a in argv][:8]
            elif isinstance(argv, str):
                head = argv.split()[:8]
            _record_event("popen_spawn", argv=head, seconds=round(dt, 4))

    subprocess.Popen.__init__ = popen_init  # type: ignore[method-assign]
    _wrap_timed(subprocess.Popen, "wait", "popen_wait")
    _wrap_timed(subprocess.Popen, "communicate", "popen_communicate")


def _install_lazy_hooks() -> None:
    """Wrap lazily imported heavy modules once they appear in sys.modules."""
    import sys

    st = sys.modules.get("sentence_transformers")
    if st is not None:
        _wrap_timed(
            st.SentenceTransformer, "__init__", "load_sentence_transformer", event=True
        )
        _wrap_timed(st.CrossEncoder, "__init__", "load_cross_encoder", event=True)
        _wrap_timed(st.CrossEncoder, "predict", "gpu_rerank_predict")
        sparse = getattr(st, "SparseEncoder", None)
        if sparse is not None:
            _wrap_timed(sparse, "__init__", "load_sparse_encoder", event=True)

    mp_process = sys.modules.get("multiprocessing.process")
    if mp_process is not None:
        _wrap_timed(mp_process.BaseProcess, "start", "mp_process_start")

    emb = sys.modules.get("vaultspec_rag.embeddings")
    if emb is not None:
        _wrap_timed(emb.EmbeddingModel, "__init__", "embedding_model_init", event=True)
        _wrap_timed(emb.EmbeddingModel, "encode_documents", "gpu_encode_documents")
        _wrap_timed(
            emb.EmbeddingModel,
            "encode_documents_on_device",
            "gpu_encode_documents_device",
        )
        _wrap_timed(emb.EmbeddingModel, "encode_query", "gpu_encode_query")
        _wrap_timed(
            emb.EmbeddingModel, "encode_documents_sparse", "gpu_encode_documents_sparse"
        )
        _wrap_timed(
            emb.EmbeddingModel, "encode_query_sparse", "gpu_encode_query_sparse"
        )

    for mod_name, cls_name, label in (
        ("vaultspec_rag.indexer._vault_indexer", "VaultIndexer", "vault_full_index"),
        (
            "vaultspec_rag.indexer._codebase_indexer",
            "CodebaseIndexer",
            "code_full_index",
        ),
        (
            "vaultspec_rag.indexer._document_indexer",
            "DocumentIndexer",
            "document_full_index",
        ),
    ):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, cls_name):
            _wrap_timed(getattr(mod, cls_name), "full_index", label, event=True)


def pytest_configure(config: pytest.Config) -> None:
    del config
    _install_base_hooks()
    if os.environ.get("PERF_PROBE_EAGER") == "1":
        # GPU-tier profiling: import the heavy modules up front so their
        # constructors are wrapped before any session fixture runs.
        import contextlib
        import importlib

        for mod_name in (
            "sentence_transformers",
            "vaultspec_rag.embeddings",
            "vaultspec_rag.indexer._vault_indexer",
            "vaultspec_rag.indexer._codebase_indexer",
            "vaultspec_rag.indexer._document_indexer",
            "multiprocessing.process",
        ):
            with contextlib.suppress(ImportError):
                importlib.import_module(mod_name)
        _install_lazy_hooks()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None):
    del nextitem
    _install_lazy_hooks()
    before = _snapshot()
    t0 = time.perf_counter()
    _CURRENT_NODE.append(item.nodeid)
    yield
    _CURRENT_NODE.pop()
    wall = time.perf_counter() - t0
    _install_lazy_hooks()
    after = _snapshot()
    delta = {}
    for name, (count, seconds) in after.items():
        prev = before.get(name, (0, 0.0))
        dc, ds = count - prev[0], seconds - prev[1]
        if dc or ds > 1e-4:
            delta[name] = [int(dc), round(ds, 4)]
    with _LOCK:
        events = list(_EVENTS)
        _EVENTS.clear()
    record = {
        "node": item.nodeid,
        "wall": round(wall, 4),
        "delta": delta,
        "events": events,
    }
    with _LOCK, open(_OUT_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del session
    record = {
        "node": "<session-total>",
        "exitstatus": int(exitstatus),
        "wall": round(time.perf_counter() - _SESSION_T0, 3),
        "totals": {k: [int(v[0]), round(v[1], 3)] for k, v in _snapshot().items()},
        "events": _EVENTS,
    }
    with open(_OUT_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
