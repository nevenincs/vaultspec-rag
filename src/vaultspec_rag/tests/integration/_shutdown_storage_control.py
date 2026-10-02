"""One child/root-scoped shutdown barrier after real storage confirmation."""

from __future__ import annotations

import atexit
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...indexer._run_checkpoint import CodeRunCheckpoint
from .._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS, publish_marker

if TYPE_CHECKING:
    from ...indexer._streaming_types import CodeFileSegment


def install(root: Path, control: Path) -> None:
    """Hold an unpublished generation while preserving real storage and cancellation."""
    monkeypatch = pytest.MonkeyPatch()
    original = CodeRunCheckpoint.record_confirmed_segments
    witnessed = False
    atexit.register(monkeypatch.undo)

    def confirmed(
        self: CodeRunCheckpoint,
        segments: tuple[CodeFileSegment, ...],
        source_digests: dict[str, str],
    ) -> int:
        nonlocal witnessed
        try:
            inserted = original(self, segments, source_digests)
        except BaseException:
            monkeypatch.undo()
            raise
        if (
            witnessed
            or not (control / "armed").exists()
            or Path(self.generation.signature.root_identity).resolve() != root
            or inserted <= 0
            or not any(segment.is_file_end for segment in segments)
        ):
            return inserted
        witnessed = True
        try:
            publish_marker(control / "stored", str(inserted))
            deadline = time.monotonic() + CHILD_PROCESS_TIMEOUT_SECONDS
            while not (control / "release").exists():
                self.run_policy.checkpoint("confirmed storage shutdown barrier")
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "parent did not release confirmed storage barrier"
                    )
                time.sleep(0.05)
            self.run_policy.checkpoint("confirmed storage shutdown barrier release")
            return inserted
        finally:
            monkeypatch.undo()
            publish_marker(control / "restored", "1")

    try:
        # Real upserts and ledger accounting run first. Only this daemon/root
        # pauses before publication; polling alone can miss this shutdown premise.
        monkeypatch.setattr(CodeRunCheckpoint, "record_confirmed_segments", confirmed)
        publish_marker(control / "installed", "1")
    except BaseException:
        monkeypatch.undo()
        raise
