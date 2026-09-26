"""A vault full index reports every unit of progress inside its own phase."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ..indexer._run_ledger_models import RunAuthority
from ..indexer._vault_indexer import VaultIndexer
from ..progress import NullProgressReporter

if TYPE_CHECKING:
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..store_runtime import VaultStore

pytestmark = pytest.mark.unit


class _StoreReachedError(Exception):
    """Raised when the run first needs the store, after hashing."""


class _StoreStandIn:
    """Answers the activity stamp, then stops the run at its first real use."""

    def touch_manifest_last_indexed(self) -> None:
        return None

    @property
    def backend_identity(self) -> str:
        raise _StoreReachedError


class _RecordingReporter(NullProgressReporter):
    def __init__(self) -> None:
        self.phases: list[tuple[str, int | None, int]] = []
        self.stray_advances = 0
        self._open = False

    def phase_start(self, name: str, total: int | None) -> None:
        self.phases.append((name, total, 0))
        self._open = True

    def advance(self, n: int = 1) -> None:
        if not self._open:
            self.stray_advances += n
            return
        name, total, done = self.phases[-1]
        self.phases[-1] = (name, total, done + n)

    def phase_end(self) -> None:
        self._open = False


def test_hashing_reports_its_progress_in_its_own_phase(tmp_path: Path) -> None:
    # The job reporter keeps publishing into the last phase until the next one
    # starts. Hashing ran after the parse phase closed, so its advances landed
    # on "parse documents", overran that phase's total, and every vault rebuild
    # logged a rejected progress update at ERROR. Mutation: removing the hash
    # phase fails the stray-advance assertion below.
    root = tmp_path.resolve()
    for index in range(3):
        doc = root / ".vault" / "adr" / f"2026-01-0{index + 1}-topic{index}-adr.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(
            "---\ntags:\n  - '#adr'\n"
            f"  - '#topic{index}'\ndate: '2026-01-0{index + 1}'\n---\n"
            f"# topic{index} adr\n\nBody {index}.\n",
            encoding="utf-8",
        )
    reporter = _RecordingReporter()
    indexer = VaultIndexer(
        root,
        cast("EmbeddingModel", object()),
        cast("VaultStore", _StoreStandIn()),
    )

    with pytest.raises(_StoreReachedError):
        indexer.full_index(reporter=reporter, authority=RunAuthority.REBUILD)

    assert reporter.stray_advances == 0
    assert ("hash documents", 3, 3) in reporter.phases
    for name, total, done in reporter.phases:
        assert total is None or done <= total, name
