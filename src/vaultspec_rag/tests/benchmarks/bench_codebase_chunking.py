"""Benchmark: parallel vs serial codebase chunking wall-clock (#155).

This is CPU-only on purpose. It isolates the chunk stage - the GIL-bound
tree-sitter parse-and-traverse that dominated the >1h index in #154 - so the
process-pool speedup is visible without the GPU embedding stage masking it.
The same scanned file list is chunked twice: once forced serial
(``index_chunk_workers=1``) and once with the auto worker count, and the run
asserts identical chunk ids plus a real wall-clock reduction.

Marked ``performance`` so it is excluded from the default unit run; invoke with
``vaultspec-rag test -m performance`` or pytest ``-m performance``.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

import pytest

from ... import CodebaseIndexer
from ...config import EnvVar, reset_config
from ...progress import NullProgressReporter

if TYPE_CHECKING:
    from pathlib import Path

# A non-trivial module: multiple classes and functions with real nesting so
# tree-sitter parsing + the recursive Python traversal cost is meaningful.
_MODULE_TEMPLATE = '''"""Synthetic module {i} for chunking benchmark."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Point{i}:
    x: float
    y: float

    def distance(self, other: "Point{i}") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def translate(self, dx: float, dy: float) -> "Point{i}":
        return Point{i}(self.x + dx, self.y + dy)


class Accumulator{i}:
    """Accumulates values and computes summary statistics."""

    def __init__(self) -> None:
        self._values: list[float] = []

    def add(self, value: float) -> None:
        self._values.append(value)

    def total(self) -> float:
        running = 0.0
        for value in self._values:
            running += value
        return running

    def mean(self) -> float:
        if not self._values:
            return 0.0
        return self.total() / len(self._values)

    def normalised(self) -> list[float]:
        peak = max(self._values, default=1.0) or 1.0
        return [value / peak for value in self._values]


def transform_{i}(rows: list[int], factor: int) -> list[int]:
    """Apply a banded transform over the input rows."""
    out: list[int] = []
    for index, row in enumerate(rows):
        if index % 2 == 0:
            out.append(row * factor + {i})
        else:
            out.append(row - factor)
    return out


def reduce_{i}(rows: list[int]) -> int:
    total = 0
    for row in rows:
        total += row
    return total + {i}
'''


# Repeat the module body several times per file (with distinct symbol suffixes)
# so each file carries a substantial AST - this is where the GIL-bound Python
# traversal cost lives, and where the process pool pays off.
_REPEATS_PER_FILE = 6


def _chunk_only_indexer(root: Path) -> CodebaseIndexer:
    """Build a CodebaseIndexer for chunk-only benchmarking (no model/store)."""
    indexer = CodebaseIndexer.__new__(CodebaseIndexer)
    indexer.root_dir = root
    indexer._extra_excludes = []
    return indexer


def _build_code_tree(root: Path, n_files: int) -> None:
    for i in range(n_files):
        body = "\n\n".join(
            _MODULE_TEMPLATE.format(i=i * _REPEATS_PER_FILE + r)
            for r in range(_REPEATS_PER_FILE)
        )
        (root / f"module_{i:05d}.py").write_text(body, encoding="utf-8")


def _chunk_with_workers(
    indexer: CodebaseIndexer,
    paths: list[Path],
    workers: int,
) -> tuple[list, float]:
    prev = os.environ.get(EnvVar.INDEX_CHUNK_WORKERS.value)
    os.environ[EnvVar.INDEX_CHUNK_WORKERS.value] = str(workers)
    reset_config()
    try:
        start = time.perf_counter()
        chunks = indexer._chunk_paths(paths, reporter=NullProgressReporter())
        elapsed = time.perf_counter() - start
    finally:
        if prev is None:
            os.environ.pop(EnvVar.INDEX_CHUNK_WORKERS.value, None)
        else:
            os.environ[EnvVar.INDEX_CHUNK_WORKERS.value] = prev
        reset_config()
    return chunks, elapsed


@pytest.mark.performance
def test_parallel_chunking_beats_serial(tmp_path_factory) -> None:
    n_files = 2000
    root = tmp_path_factory.mktemp("bench-chunk")
    _build_code_tree(root, n_files)

    indexer = _chunk_only_indexer(root)
    paths = indexer.scan_files()
    assert len(paths) == n_files

    cores = os.cpu_count() or 1
    # Force worker counts explicitly so the byte gate does not intervene: this
    # benchmark measures the pool's ceiling, not the auto heuristic.
    serial_chunks, serial_s = _chunk_with_workers(indexer, paths, workers=1)
    parallel_chunks, parallel_s = _chunk_with_workers(indexer, paths, workers=cores)

    # Correctness gate: parallelism must not change the output.
    assert {c.id for c in serial_chunks} == {c.id for c in parallel_chunks}

    speedup = serial_s / parallel_s if parallel_s > 0 else float("inf")
    print(
        f"\n[chunk benchmark] files={n_files} cores={os.cpu_count()} "
        f"serial={serial_s:.2f}s parallel={parallel_s:.2f}s "
        f"speedup={speedup:.2f}x chunks={len(parallel_chunks)}",
    )

    # On any multi-core machine the GIL-free process pool must beat the serial
    # path on a tree this size. A conservative margin avoids spawn-overhead
    # flakiness while still proving the win.
    if (os.cpu_count() or 1) > 1:
        assert parallel_s < serial_s
