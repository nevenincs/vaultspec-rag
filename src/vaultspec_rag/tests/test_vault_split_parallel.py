"""Real-object coverage for the parallel vault document split stage."""

from __future__ import annotations

import os

from .._store_models import VaultDocument
from ..config import EnvVar, reset_config
from ..indexer._vault_prep import (
    _plan_split_workers,
    split_document,
    split_documents,
)
from ._import_probe import assert_fresh_import_excludes, import_probe_source


class _Workers:
    """Context manager forcing a specific ``index_chunk_workers`` value.

    Uses the real environment variable + ``reset_config`` so the production
    resolution path is exercised end to end.
    """

    def __init__(self, value: int) -> None:
        self._value = str(value)
        self._prev: str | None = None

    def __enter__(self) -> None:
        self._prev = os.environ.get(EnvVar.INDEX_CHUNK_WORKERS.value)
        os.environ[EnvVar.INDEX_CHUNK_WORKERS.value] = self._value
        reset_config()

    def __exit__(self, *_exc: object) -> None:
        if self._prev is None:
            os.environ.pop(EnvVar.INDEX_CHUNK_WORKERS.value, None)
        else:
            os.environ[EnvVar.INDEX_CHUNK_WORKERS.value] = self._prev
        reset_config()


def _doc(index: int, body: str) -> VaultDocument:
    return VaultDocument(
        id=f"research/doc-{index:02d}",
        path=f"research/doc-{index:02d}.md",
        doc_type="research",
        feature="feature-x",
        date="2026-01-01",
        tags=["#research", "#feature-x"],
        related=[],
        title=f"Doc {index}",
        status="",
        content=body,
        vector=[],
    )


def _corpus(n_docs: int) -> list[VaultDocument]:
    return [
        _doc(
            index,
            "\n\n".join(
                f"## Section {section}\n\n" + (f"line {index}-{section} " * 40)
                for section in range(4)
            ),
        )
        for index in range(n_docs)
    ]


def test_parallel_split_output_is_identical_to_serial() -> None:
    """Spawn-pool splitting must be byte-identical, order included."""
    docs = _corpus(9)
    chunk_chars = 256
    serial = [chunk for doc in docs for chunk in split_document(doc, chunk_chars)]
    with _Workers(2):
        assert _plan_split_workers(docs) == 2
        parallel = split_documents(docs, chunk_chars)
    assert parallel == serial
    assert len(parallel) > len(docs)  # the corpus genuinely split


def test_auto_mode_stays_serial_below_the_byte_gate() -> None:
    """Auto worker planning must not spawn a pool for a small corpus."""
    docs = _corpus(4)
    with _Workers(0):
        assert _plan_split_workers(docs) == 1


def test_explicit_workers_clamp_to_the_document_count() -> None:
    docs = _corpus(2)
    with _Workers(8):
        assert _plan_split_workers(docs) == 2


def test_vault_prep_import_does_not_load_torch() -> None:
    """Importing the vault prep module must not pull in torch.

    Spawn split workers re-import this module; if any module on its import
    chain eagerly imported torch, every worker would initialise CUDA on
    startup and reintroduce the fork/spawn CUDA-context crash class.
    Checked in a fresh interpreter so the parent process's already-loaded
    torch cannot mask a regression. See rule ``index-workers-stay-cpu-only``.
    """
    assert_fresh_import_excludes(
        import_probe_source("vaultspec_rag.indexer._vault_prep")
    )
