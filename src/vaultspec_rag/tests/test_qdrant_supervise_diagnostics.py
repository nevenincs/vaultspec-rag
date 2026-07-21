"""Qdrant supervisor failure-legibility tests (plan W01.P01).

Verifies that the supervisor captures and bounds a real child process's output,
and reports a non-ready exit with its cause rather than the opaque timeout that
hid a real Rust panic. No mocks and no GPU: every drain reads a real subprocess
pipe and writes real files. A free, non-default port prevents contact with a
running Qdrant on 8765.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from ..qdrant_runtime._supervise import QdrantSupervisor


def _drain_process_output(supervisor: QdrantSupervisor, output: str) -> None:
    """Drain exact text emitted by a real child process."""
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write(sys.argv[1]); sys.stdout.flush()",
            output,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    assert process.stdout is not None
    supervisor._drain_output(process.stdout)  # pyright: ignore[reportPrivateUsage]
    assert process.wait(timeout=10.0) == 0


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
        _drain_process_output(sup, "starting up\nERROR Panic backtrace: boom\n")

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
        _drain_process_output(sup, "".join(f"line {i}\n" for i in range(500)))
        # Only the most-recent lines are retained; the last line survives.
        assert "line 499" in sup.recent_output_tail(max_lines=5)
        assert "line 0\n" not in sup.recent_output_tail(max_lines=50)

    def test_raw_output_rolls_before_write_and_retains_exact_count(
        self,
        tmp_path: Path,
    ) -> None:
        log_path = tmp_path / "qdrant.log"
        sup = QdrantSupervisor(
            tmp_path / "unused-binary",
            http_port=59994,
            storage_dir=tmp_path / "storage",
            log_path=log_path,
            log_max_bytes=30,
            log_backup_count=2,
        )

        _drain_process_output(
            sup,
            "".join(f"record-{index:02d}\n" for index in range(7)),
        )

        assert {path.name for path in tmp_path.glob("qdrant.log*")} == {
            "qdrant.log",
            "qdrant.log.1",
            "qdrant.log.2",
        }
        assert log_path.read_text(encoding="utf-8") == "record-06\n"
        assert (
            log_path.with_name("qdrant.log.1").read_text(encoding="utf-8")
            == "record-04\nrecord-05\n"
        )
        assert (
            log_path.with_name("qdrant.log.2").read_text(encoding="utf-8")
            == "record-02\nrecord-03\n"
        )
        assert "record-00" not in "".join(
            path.read_text(encoding="utf-8") for path in tmp_path.glob("qdrant.log*")
        )
        assert "record-00" in sup.recent_output_tail(max_lines=50)

    def test_preexisting_oversized_active_rolls_before_fresh_output(
        self,
        tmp_path: Path,
    ) -> None:
        log_path = tmp_path / "qdrant.log"
        prior = b"previous-child-output\n"
        log_path.write_bytes(prior)
        sup = QdrantSupervisor(
            tmp_path / "unused-binary",
            http_port=59995,
            storage_dir=tmp_path / "storage",
            log_path=log_path,
            log_max_bytes=len(prior),
            log_backup_count=2,
        )

        _drain_process_output(sup, "fresh-child-output\n")

        assert log_path.read_bytes() == b"fresh-child-output\n"
        assert log_path.with_name("qdrant.log.1").read_bytes() == prior
        assert not log_path.with_name("qdrant.log.2").exists()

    def test_reopened_drain_appends_across_child_restart_boundary(
        self,
        tmp_path: Path,
    ) -> None:
        log_path = tmp_path / "qdrant.log"
        sup = QdrantSupervisor(
            tmp_path / "unused-binary",
            http_port=59996,
            storage_dir=tmp_path / "storage",
            log_path=log_path,
            log_max_bytes=1024,
            log_backup_count=2,
        )

        _drain_process_output(sup, "before-restart\n")
        _drain_process_output(sup, "after-restart\n")

        assert log_path.read_text(encoding="utf-8") == (
            "before-restart\nafter-restart\n"
        )

    def test_restart_refuses_while_previous_child_pipe_is_still_held_open(
        self,
        tmp_path: Path,
    ) -> None:
        log_path = tmp_path / "qdrant.log"
        release_path = tmp_path / "release-grandchild"
        supervisor = QdrantSupervisor(
            Path(sys.executable),
            http_port=59990,
            storage_dir=tmp_path / "storage",
            log_path=log_path,
            log_max_bytes=1024,
            log_backup_count=2,
        )
        grandchild_code = (
            "import pathlib,sys,time;"
            f"release=pathlib.Path({str(release_path)!r});"
            "print('grandchild-holds-pipe');sys.stdout.flush();"
            "deadline=time.monotonic()+30;"
            "\nwhile not release.exists() and time.monotonic()<deadline:"
            " time.sleep(0.02)"
        )
        parent_code = (
            "import subprocess,sys;"
            "subprocess.Popen([sys.executable,'-c',sys.argv[1]],"
            "stdin=subprocess.DEVNULL,stdout=sys.stdout,stderr=sys.stderr);"
            "print('parent-exits');sys.stdout.flush()"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", parent_code, grandchild_code],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="strict",
        )
        assert process.stdout is not None
        supervisor._proc = process  # pyright: ignore[reportPrivateUsage]
        supervisor._start_output_drain()  # pyright: ignore[reportPrivateUsage]
        old_drain = supervisor._drain_thread  # pyright: ignore[reportPrivateUsage]
        assert old_drain is not None

        try:
            assert process.wait(timeout=10.0) == 0
            assert old_drain.is_alive()

            assert supervisor.restart(timeout=0.1) is False
            assert (
                supervisor._drain_thread is old_drain  # pyright: ignore[reportPrivateUsage]
            )
            assert old_drain.is_alive()
            assert supervisor._proc is None  # pyright: ignore[reportPrivateUsage]

            release_path.touch()
            old_drain.join(timeout=10.0)
            assert not old_drain.is_alive()
            assert "grandchild-holds-pipe" in supervisor.recent_output_tail()

            # A later stop reaps the completed reference, after which a new
            # real child and its drain may start normally.
            supervisor.stop(timeout=0.1)
            assert (
                supervisor._drain_thread is None  # pyright: ignore[reportPrivateUsage]
            )
            supervisor.spawn()
        finally:
            release_path.touch(exist_ok=True)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10.0)
            old_drain.join(timeout=10.0)
            supervisor.stop(timeout=0.1)

        assert "grandchild-holds-pipe" in log_path.read_text(encoding="utf-8")

    def test_sparse_and_excess_generations_converge_to_retention_bound(
        self,
        tmp_path: Path,
    ) -> None:
        log_path = tmp_path / "qdrant.log"
        active = b"active-before-rollover\n"
        log_path.write_bytes(active)
        log_path.with_name("qdrant.log.1").write_bytes(b"generation-one\n")
        log_path.with_name("qdrant.log.3").write_bytes(b"generation-three\n")
        log_path.with_name("qdrant.log.9").write_bytes(b"stale-generation\n")
        sup = QdrantSupervisor(
            tmp_path / "unused-binary",
            http_port=59997,
            storage_dir=tmp_path / "storage",
            log_path=log_path,
            log_max_bytes=len(active),
            log_backup_count=4,
        )

        _drain_process_output(sup, "fresh\n")

        assert {path.name for path in tmp_path.glob("qdrant.log*")} == {
            "qdrant.log",
            "qdrant.log.1",
            "qdrant.log.2",
            "qdrant.log.4",
        }
        assert log_path.read_bytes() == b"fresh\n"
        assert log_path.with_name("qdrant.log.1").read_bytes() == active
        assert log_path.with_name("qdrant.log.2").read_bytes() == b"generation-one\n"
        assert log_path.with_name("qdrant.log.4").read_bytes() == (
            b"generation-three\n"
        )

    def test_zero_backup_count_truncates_and_removes_stale_generations(
        self,
        tmp_path: Path,
    ) -> None:
        log_path = tmp_path / "qdrant.log"
        active = b"active-at-threshold\n"
        log_path.write_bytes(active)
        log_path.with_name("qdrant.log.1").write_bytes(b"generation-one\n")
        log_path.with_name("qdrant.log.4").write_bytes(b"stale-generation\n")
        sup = QdrantSupervisor(
            tmp_path / "unused-binary",
            http_port=59999,
            storage_dir=tmp_path / "storage",
            log_path=log_path,
            log_max_bytes=len(active),
            log_backup_count=0,
        )

        _drain_process_output(sup, "fresh\n")

        assert {path.name for path in tmp_path.glob("qdrant.log*")} == {"qdrant.log"}
        assert log_path.read_bytes() == b"fresh\n"

    def test_rollover_failure_preserves_recent_output_and_stops_file_growth(
        self,
        tmp_path: Path,
    ) -> None:
        log_path = tmp_path / "qdrant.log"
        prior = b"active-at-threshold\n"
        log_path.write_bytes(prior)
        # A real directory at the first-backup path makes backup removal fail
        # on every supported platform without a patched filesystem API.
        log_path.with_name("qdrant.log.1").mkdir()
        sup = QdrantSupervisor(
            tmp_path / "unused-binary",
            http_port=59998,
            storage_dir=tmp_path / "storage",
            log_path=log_path,
            log_max_bytes=len(prior),
            log_backup_count=1,
        )

        _drain_process_output(sup, "first-after-failure\nlast-after-failure\n")

        assert log_path.read_bytes() == prior
        assert "last-after-failure" in sup.recent_output_tail()


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
