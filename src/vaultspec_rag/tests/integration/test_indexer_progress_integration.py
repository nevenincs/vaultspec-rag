"""Integration smoke tests asserting indexer phase events fire correctly.

Drives a ``CountingProgressReporter`` through a real full-index of the
synthetic vault and codebase fixtures on the real GPU. No mocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from ...indexer import CodebaseIndexer, VaultIndexer
from ...store import VaultStore
from ..corpus import build_synthetic_vault

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import TempPathFactory

    from ...embeddings import EmbeddingModel

pytestmark = [pytest.mark.integration]


@dataclass
class PhaseStartEvent:
    name: str
    total: int | None


@dataclass
class AdvanceEvent:
    n: int


@dataclass
class PhaseEndEvent:
    pass


@dataclass
class LogEvent:
    message: str


ProgressEvent = PhaseStartEvent | AdvanceEvent | PhaseEndEvent | LogEvent


class CountingProgressReporter:
    """Records every event for assertion."""

    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    def phase_start(self, name: str, total: int | None) -> None:
        self.events.append(PhaseStartEvent(name=name, total=total))

    def advance(self, n: int = 1) -> None:
        self.events.append(AdvanceEvent(n=n))

    def phase_end(self) -> None:
        self.events.append(PhaseEndEvent())

    def log(self, message: str) -> None:
        self.events.append(LogEvent(message=message))

    def phase_names(self) -> list[str]:
        return [e.name for e in self.events if isinstance(e, PhaseStartEvent)]

    def advance_total_between(self, start_idx: int, end_idx: int) -> int:
        total = 0
        for event in self.events[start_idx:end_idx]:
            if isinstance(event, AdvanceEvent):
                total += event.n
        return total


def _assert_phase_balanced(events: list[ProgressEvent]) -> None:
    depth = 0
    for event in events:
        if isinstance(event, PhaseStartEvent):
            assert depth == 0, "phase_start while another phase active"
            depth += 1
        elif isinstance(event, PhaseEndEvent):
            assert depth == 1, "phase_end with no active phase"
            depth -= 1
    assert depth == 0, "unclosed phase at end"


class TestVaultIndexerProgress:
    @pytest.mark.timeout(300)
    def test_full_index_emits_expected_phases(
        self,
        embedding_model: EmbeddingModel,
        tmp_path_factory: TempPathFactory,
    ) -> None:
        root: Path = tmp_path_factory.mktemp("progress-vault")
        build_synthetic_vault(root, n_docs=8, seed=101)

        store = VaultStore(root)
        try:
            indexer = VaultIndexer(root, embedding_model, store)
            reporter = CountingProgressReporter()
            result = indexer.full_index(clean=True, reporter=reporter)
            assert result.added > 0

            names = reporter.phase_names()
            expected = [
                "scan vault",
                "parse documents",
                "prepare collection",
                "embed + upsert documents",
                "purge stale documents",
                "write metadata",
            ]
            assert names == expected, f"unexpected phase order: {names}"

            _assert_phase_balanced(reporter.events)

            n_docs = result.added
            phase_totals: dict[str, int] = {}
            current: str | None = None
            for event in reporter.events:
                if isinstance(event, PhaseStartEvent):
                    current = event.name
                    phase_totals.setdefault(current, 0)
                elif isinstance(event, AdvanceEvent) and current is not None:
                    phase_totals[current] += event.n
                elif isinstance(event, PhaseEndEvent):
                    current = None

            assert phase_totals["parse documents"] >= n_docs
            assert phase_totals["prepare collection"] == 1
            assert phase_totals["embed + upsert documents"] == n_docs
            # Fresh collection - no stale IDs to purge.
            assert phase_totals["purge stale documents"] == 0
            assert phase_totals["write metadata"] == 1
        finally:
            store.close()


class TestCodebaseIndexerProgress:
    @pytest.mark.timeout(300)
    def test_full_index_emits_expected_phases(
        self,
        embedding_model: EmbeddingModel,
        tmp_path_factory: TempPathFactory,
    ) -> None:
        root: Path = tmp_path_factory.mktemp("progress-code")
        build_synthetic_vault(root, n_docs=4, seed=202)

        src = root / "pkg"
        src.mkdir(parents=True, exist_ok=True)
        (src / "sample.py").write_text(
            "def hello():\n    return 1\n\n\ndef world():\n    return 2\n",
            encoding="utf-8",
        )

        store = VaultStore(root)
        try:
            code_indexer = CodebaseIndexer(root, embedding_model, store)
            reporter = CountingProgressReporter()
            result = code_indexer.full_index(clean=True, reporter=reporter)

            names = reporter.phase_names()
            # The codebase full index reads each file once (#155 P03): the
            # separate "hash files" phase is gone, and chunking + embedding are
            # pipelined into a single "chunk + embed" phase (#155 P02) that
            # advances once per file as workers complete.
            expected = [
                "scan codebase",
                "prepare collection",
                "chunk + embed",
                "purge stale chunks",
                "write metadata",
            ]
            assert names == expected, f"unexpected phase order: {names}"

            _assert_phase_balanced(reporter.events)

            phase_totals: dict[str, int] = {}
            current: str | None = None
            for event in reporter.events:
                if isinstance(event, PhaseStartEvent):
                    current = event.name
                    phase_totals.setdefault(current, 0)
                elif isinstance(event, AdvanceEvent) and current is not None:
                    phase_totals[current] += event.n
                elif isinstance(event, PhaseEndEvent):
                    current = None

            n_chunks = result.added
            if n_chunks > 0:
                assert phase_totals["prepare collection"] == 1
                # The pipelined phase advances once per scanned file.
                assert phase_totals["chunk + embed"] == result.files
                assert phase_totals["purge stale chunks"] == 0
                assert phase_totals["write metadata"] == 1
        finally:
            store.close()
