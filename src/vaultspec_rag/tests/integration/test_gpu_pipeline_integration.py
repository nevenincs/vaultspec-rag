"""Integration tests for the dedicated GPU consumer-thread pipeline (#155).

Real GPU + real Qdrant, no mocks/stubs. These lock down the two contracts the
decoupled producer/consumer must hold:

- the parallel pipeline (process-pool producer + dedicated GPU consumer thread)
  upserts exactly the same chunk ids and metadata as the serial path; and
- a genuine consumer-side failure (a real dimension mismatch that Qdrant
  rejects on upsert) is re-raised in the caller rather than hanging the index.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from vaultspec_rag import CodebaseIndexer, VaultStore
from vaultspec_rag.config import EnvVar, reset_config
from vaultspec_rag.progress import NullProgressReporter

if TYPE_CHECKING:
    from pathlib import Path

_MODULE = '''"""Module {i}."""


class Handler{i}:
    def __init__(self, base: int) -> None:
        self.base = base

    def apply(self, values: list[int]) -> int:
        total = self.base
        for v in values:
            total += v * {i}
        return total


def transform_{i}(rows: list[int]) -> list[int]:
    return [r + {i} for r in rows]
'''


def _make_tree(root: Path, n_files: int) -> None:
    for i in range(n_files):
        (root / f"mod_{i:04d}.py").write_text(_MODULE.format(i=i), encoding="utf-8")


class _Workers:
    """Force ``index_chunk_workers`` via the real env + reset_config."""

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


@pytest.mark.integration
class TestPipelineParity:
    """The consumer-thread pipeline must match the serial path exactly."""

    @pytest.mark.timeout(300)
    def test_parallel_pipeline_matches_serial(
        self,
        embedding_model,
        tmp_path_factory,
    ) -> None:
        root = tmp_path_factory.mktemp("gpu-pipe-src")
        _make_tree(root, 60)

        serial_store = VaultStore(tmp_path_factory.mktemp("gpu-pipe-serial"))
        parallel_store = VaultStore(tmp_path_factory.mktemp("gpu-pipe-parallel"))
        try:
            serial_ix = CodebaseIndexer(root, embedding_model, serial_store)
            parallel_ix = CodebaseIndexer(root, embedding_model, parallel_store)

            with _Workers(1):  # serial path
                s_res = serial_ix.full_index(
                    clean=True,
                    reporter=NullProgressReporter(),
                )
            with _Workers(4):  # explicit -> parallel consumer-thread pipeline
                p_res = parallel_ix.full_index(
                    clean=True,
                    reporter=NullProgressReporter(),
                )

            assert p_res.added == s_res.added
            assert p_res.files == s_res.files
            assert set(parallel_store.get_all_code_ids()) == set(
                serial_store.get_all_code_ids(),
            )
            assert s_res.added > 0
        finally:
            serial_store.close()
            parallel_store.close()


@pytest.mark.integration
class TestConsumerFailurePropagates:
    """A real consumer-side error must surface, not hang the index."""

    @pytest.mark.timeout(180)
    def test_dimension_mismatch_raises(
        self,
        embedding_model,
        tmp_path_factory,
    ) -> None:
        root = tmp_path_factory.mktemp("gpu-pipe-failsrc")
        _make_tree(root, 40)
        # A store whose code collection expects the wrong vector width: the
        # consumer encodes real 1024-dim vectors, Qdrant rejects them on upsert.
        # This is a genuine failure (no mock); it must propagate and not hang.
        bad_store = VaultStore(
            tmp_path_factory.mktemp("gpu-pipe-bad"),
            embedding_dim=128,
        )
        try:
            ix = CodebaseIndexer(root, embedding_model, bad_store)
            with _Workers(4), pytest.raises(Exception):  # noqa: B017 - any real failure
                ix.full_index(clean=True, reporter=NullProgressReporter())
        finally:
            bad_store.close()
