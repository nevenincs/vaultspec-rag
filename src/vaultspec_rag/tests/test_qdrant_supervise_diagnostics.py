"""Qdrant supervisor failure-legibility tests (plan W01.P01).

Verifies that the supervisor captures the child's output and reports a non-ready
exit with its cause, rather than the opaque timeout that hid a real Rust panic.
No mocks and no GPU: the drain is driven with a real in-memory stream, and the
non-ready path uses the real Python interpreter as a benign child that exits
without ever serving. A free, non-default port is used so the test can never
touch a running Qdrant on 8765.
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import pytest

from ..qdrant_runtime._supervise import QdrantSupervisor


class TestSupervisorOutputCapture:
    """The drain thread must retain output in the ring and the log file."""

    def test_drain_captures_to_ring_and_log(self, tmp_path: Path) -> None:
        log_path = tmp_path / "qdrant.log"
        sup = QdrantSupervisor(
            tmp_path / "unused-binary",
            http_port=59991,
            storage_dir=tmp_path / "storage",
            log_path=log_path,
        )
        stream = io.StringIO("starting up\nERROR Panic backtrace: boom\n")
        sup._drain_output(stream)  # pyright: ignore[reportPrivateUsage]

        tail = sup.recent_output_tail()
        assert "Panic backtrace: boom" in tail
        assert "Panic backtrace: boom" in log_path.read_text(encoding="utf-8")

    def test_recent_output_ring_is_bounded(self, tmp_path: Path) -> None:
        sup = QdrantSupervisor(
            tmp_path / "unused-binary",
            http_port=59992,
            storage_dir=tmp_path / "storage",
            log_path=None,
        )
        sup._drain_output(  # pyright: ignore[reportPrivateUsage]
            io.StringIO("".join(f"line {i}\n" for i in range(500)))
        )
        # Only the most-recent lines are retained; the last line survives.
        assert "line 499" in sup.recent_output_tail(max_lines=5)
        assert "line 0\n" not in sup.recent_output_tail(max_lines=50)


class TestNonReadyChildDiagnosis:
    """A child that exits without serving fails fast with a named cause."""

    def test_non_ready_child_is_bounded_and_diagnosed(self, tmp_path: Path) -> None:
        # The real interpreter with DEVNULL stdin never serves /readyz, so it
        # stands in for a child that fails to come up. The readiness wait must
        # be bounded by the supplied timeout (never the 300s default) and the
        # raised error must name the cause, not be silent.
        sup = QdrantSupervisor(
            Path(sys.executable),
            http_port=59993,
            storage_dir=tmp_path / "storage",
            log_path=tmp_path / "qdrant.log",
        )
        timeout = 3.0
        started = time.monotonic()
        with pytest.raises(RuntimeError) as excinfo:
            sup.start(timeout=timeout)
        elapsed = time.monotonic() - started

        # Bounded by the timeout (plus teardown), never the 300s default.
        assert elapsed < 30.0, f"readiness wait was not bounded, took {elapsed:.1f}s"
        msg = str(excinfo.value)
        assert "failed to become ready" in msg
        # Either captured output or the explicit no-output note - never silent.
        assert "output" in msg.lower()
        assert not sup.is_alive()
