"""Root-scoped barriers for one failed served indexing attempt and its retry."""

from __future__ import annotations

import atexit
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...indexer._codebase_indexer import CodebaseIndexer
from ...indexer._run_checkpoint import CodeRunCheckpoint
from .._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from ...indexer._consumer_pipeline import CodePipelineRun
    from ...indexer._streaming_types import CodeFileSegment


def install(root: Path, control: Path) -> None:
    """Change only the explicitly selected root in this canonical server child."""
    monkeypatch = pytest.MonkeyPatch()
    original_commit = CodeRunCheckpoint.record_confirmed_segments
    original_pipeline = CodebaseIndexer._pipeline_chunk_and_embed
    failed = False
    committed_path: Path | None = None
    committed_text: str | None = None
    atexit.register(monkeypatch.undo)

    def commit(
        self: CodeRunCheckpoint,
        segments: tuple[CodeFileSegment, ...],
        source_digests: dict[str, str],
    ) -> int:
        nonlocal failed, committed_path, committed_text
        try:
            inserted = original_commit(self, segments, source_digests)
            if Path(self.generation.signature.root_identity) == root and not failed:
                complete = next((s for s in segments if s.is_file_end), None)
                if inserted and complete is not None:
                    committed_path = root / complete.path
                    committed_text = committed_path.read_text(encoding="utf-8")
                    (control / "committed.json").write_text(
                        json.dumps({"path": complete.path}), encoding="utf-8"
                    )
                    failed = True
                    raise RuntimeError("controlled failure after durable source commit")
            return inserted
        except BaseException:
            if not failed:
                monkeypatch.undo()
            raise

    def pipeline(
        self: CodebaseIndexer, paths: list[Path], run: CodePipelineRun
    ) -> tuple[set[str], int, dict[str, str]]:
        if self.root_dir.resolve() != root or not failed:
            return original_pipeline(self, paths, run)
        try:
            assert committed_path is not None and committed_text is not None
            before = committed_path.stat()
            (control / "admitted").touch()
            deadline = time.monotonic() + CHILD_PROCESS_TIMEOUT_SECONDS
            while not (control / "changed").exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("parent did not change the admitted source")
                time.sleep(0.05)
            after = committed_path.stat()
            assert (after.st_size, after.st_mtime_ns) != (
                before.st_size,
                before.st_mtime_ns,
            )
            assert committed_path.read_text(encoding="utf-8") != committed_text
            return original_pipeline(self, paths, run)
        finally:
            monkeypatch.undo()
            (control / "restored").touch()

    try:
        # Failing after a real durable commit gives the retry usable history;
        # a natural disk failure could corrupt unrelated service storage.
        monkeypatch.setattr(CodeRunCheckpoint, "record_confirmed_segments", commit)
        # Coordinate a real source edit after admission, then run the actual
        # pipeline. Timing a writer against live inference cannot do this reliably.
        monkeypatch.setattr(CodebaseIndexer, "_pipeline_chunk_and_embed", pipeline)
        (control / "installed").touch()
    except BaseException:
        monkeypatch.undo()
        raise
