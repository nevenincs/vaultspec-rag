"""Parity tests for parallel chunking and single-read hashing (#155).

These exercise a real ``spawn`` process pool and real tree-sitter parsing with
no GPU, no model, and no mocks. They lock down the three correctness contracts
the indexing rework must preserve:

- the process-pool chunk path produces byte-identical chunk ids to the serial
  path (so search results never depend on worker count);
- the worker's content hash equals ``hashlib.file_digest`` (so incremental
  change detection is unaffected by the single-read fold);
- single-read decoding reproduces ``Path.read_text`` universal-newline
  semantics (so CRLF files chunk identically to the pre-rework code).
"""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

from vaultspec_rag import CodebaseIndexer
from vaultspec_rag.config import EnvVar, reset_config
from vaultspec_rag.indexer import _chunk_worker
from vaultspec_rag.progress import NullProgressReporter

if TYPE_CHECKING:
    from pathlib import Path

_MODULE_TEMPLATE = '''"""Synthetic module {i}."""


class Widget{i}:
    """A small class with a couple of methods."""

    def __init__(self, value: int) -> None:
        self.value = value

    def scaled(self, factor: int) -> int:
        return self.value * factor + {i}

    def combined(self, other: "Widget{i}") -> int:
        return self.value + other.value


def helper_{i}(a: int, b: int) -> int:
    """Free function {i}."""
    total = a + b
    for _ in range(b):
        total += a
    return total + {i}
'''


def _chunk_only_indexer(root: Path) -> CodebaseIndexer:
    """Build a CodebaseIndexer for chunk-only use without a model or store.

    Mirrors the established unit-test pattern (``__new__`` + manual attribute
    setup): the chunking, scanning, and worker-planning methods never touch the
    embedding model or vector store, so constructing them is unnecessary.
    """
    indexer = CodebaseIndexer.__new__(CodebaseIndexer)
    indexer.root_dir = root
    indexer._extra_excludes = []
    return indexer


def _make_code_tree(root: Path, n_files: int) -> None:
    """Write *n_files* synthetic Python modules plus one YAML file."""
    for i in range(n_files):
        (root / f"mod_{i}.py").write_text(
            _MODULE_TEMPLATE.format(i=i),
            encoding="utf-8",
        )
    (root / "config.yaml").write_text(
        "name: synthetic\nversion: 1\nitems:\n  - a\n  - b\n  - c\n",
        encoding="utf-8",
    )


class _Workers:
    """Context manager forcing a specific ``index_chunk_workers`` value.

    Uses the real environment variable + ``reset_config`` rather than a mock so
    the production resolution path is exercised end to end.
    """

    def __init__(self, value: int) -> None:
        self._value = str(value)
        self._prev: str | None = None

    def __enter__(self) -> None:
        self._prev = os.environ.get(EnvVar.INDEX_CHUNK_WORKERS.value)
        os.environ[EnvVar.INDEX_CHUNK_WORKERS.value] = self._value
        reset_config()

    def __exit__(self, *exc: object) -> None:
        if self._prev is None:
            os.environ.pop(EnvVar.INDEX_CHUNK_WORKERS.value, None)
        else:
            os.environ[EnvVar.INDEX_CHUNK_WORKERS.value] = self._prev
        reset_config()


class TestChunkIdentityParity:
    """Process-pool chunking must match the serial path exactly."""

    def test_parallel_matches_serial(self, tmp_path: Path) -> None:
        _make_code_tree(tmp_path, 40)
        indexer = _chunk_only_indexer(tmp_path)
        paths = indexer.scan_files()
        assert len(paths) >= 40

        with _Workers(4):
            parallel = indexer._chunk_paths(paths, reporter=NullProgressReporter())
        serial = indexer._chunk_paths_serial(paths, NullProgressReporter())

        assert {c.id for c in parallel} == {c.id for c in serial}
        assert len(parallel) == len(serial)

    def test_parallel_pipeline_hashes_every_file(self, tmp_path: Path) -> None:
        _make_code_tree(tmp_path, 20)
        indexer = _chunk_only_indexer(tmp_path)
        paths = indexer.scan_files()
        # chunk_and_hash_file is the pipeline worker; its meta must cover every
        # readable file even when a file yields zero chunks.
        meta: dict[str, str] = {}
        for p in paths:
            res = _chunk_worker.chunk_and_hash_file(p, tmp_path)
            assert res is not None
            meta[res.rel_path] = res.content_hash
        assert len(meta) == len(paths)


class TestWorkerGating:
    """Auto worker selection must gate on total source bytes (#155)."""

    def test_small_tree_auto_stays_serial(self, tmp_path: Path) -> None:
        _make_code_tree(tmp_path, 20)  # ~tens of KB, well under 8 MiB
        indexer = _chunk_only_indexer(tmp_path)
        paths = indexer.scan_files()
        with _Workers(0):  # auto
            assert indexer._plan_chunk_workers(paths) == 1

    def test_small_tree_explicit_bypasses_gate(self, tmp_path: Path) -> None:
        _make_code_tree(tmp_path, 20)
        indexer = _chunk_only_indexer(tmp_path)
        paths = indexer.scan_files()
        with _Workers(3):  # explicit request ignores the byte gate
            assert indexer._plan_chunk_workers(paths) == 3

    def test_zero_threshold_enables_parallel(self, tmp_path: Path) -> None:
        _make_code_tree(tmp_path, 20)
        indexer = _chunk_only_indexer(tmp_path)
        paths = indexer.scan_files()
        prev = os.environ.get(EnvVar.INDEX_PARALLEL_MIN_BYTES.value)
        os.environ[EnvVar.INDEX_PARALLEL_MIN_BYTES.value] = "0"
        reset_config()
        try:
            with _Workers(0):  # auto, but gate disabled
                assert indexer._plan_chunk_workers(paths) > 1
        finally:
            if prev is None:
                os.environ.pop(EnvVar.INDEX_PARALLEL_MIN_BYTES.value, None)
            else:
                os.environ[EnvVar.INDEX_PARALLEL_MIN_BYTES.value] = prev
            reset_config()


class TestHashParity:
    """The worker hash must equal hashlib.file_digest over the raw bytes."""

    def test_content_hash_matches_file_digest(self, tmp_path: Path) -> None:
        _make_code_tree(tmp_path, 5)
        indexer = _chunk_only_indexer(tmp_path)
        for p in indexer.scan_files():
            res = _chunk_worker.chunk_and_hash_file(p, tmp_path)
            assert res is not None
            with open(p, "rb") as f:
                expected = hashlib.file_digest(f, "blake2b").hexdigest()
            assert res.content_hash == expected


class TestNewlineParity:
    """Single-read decoding must reproduce Path.read_text newline handling."""

    def test_crlf_chunks_match_read_text(self, tmp_path: Path) -> None:
        crlf = tmp_path / "crlf_module.py"
        crlf.write_bytes(
            b'"""CRLF doc."""\r\n\r\n\r\n'
            b"class Thing:\r\n"
            b"    def run(self, x):\r\n"
            b"        return x + 1\r\n\r\n\r\n"
            b"def standalone(a, b):\r\n"
            b"    return a * b\r\n",
        )
        # New single-read path.
        new_chunks = _chunk_worker.chunk_file(crlf, tmp_path)
        # Reference: the pre-rework behaviour decoded via Path.read_text, which
        # applies universal-newline translation.
        ref_content = crlf.read_text(encoding="utf-8")
        ref_chunks = _chunk_worker._chunk_decoded(ref_content, crlf, tmp_path)

        assert [c.id for c in new_chunks] == [c.id for c in ref_chunks]
        assert [c.content for c in new_chunks] == [c.content for c in ref_chunks]
        # And no carriage returns survive translation.
        assert all("\r" not in c.content for c in new_chunks)
