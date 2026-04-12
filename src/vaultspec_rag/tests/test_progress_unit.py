"""Unit tests for the ``progress`` module."""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from rich.console import Console

from vaultspec_rag.progress import (
    NullProgressReporter,
    ProgressReporter,
    RichProgressReporter,
)


class CountingProgressReporter:
    """Reporter that records every event for test assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def phase_start(self, name: str, total: int | None) -> None:
        self.events.append(("phase_start", (name, total)))

    def advance(self, n: int = 1) -> None:
        self.events.append(("advance", n))

    def phase_end(self) -> None:
        self.events.append(("phase_end", None))

    def log(self, message: str) -> None:
        self.events.append(("log", message))


def _make_non_tty_console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=120)
    return console, buf


class TestNullProgressReporter:
    def test_protocol_compliance(self) -> None:
        reporter = NullProgressReporter()
        assert isinstance(reporter, ProgressReporter)

    def test_all_methods_accept_calls(self) -> None:
        reporter = NullProgressReporter()
        reporter.phase_start("scan", 42)
        reporter.advance()
        reporter.advance(5)
        reporter.log("hello")
        reporter.phase_end()

    def test_phase_start_accepts_none_total(self) -> None:
        reporter = NullProgressReporter()
        reporter.phase_start("scan", None)
        reporter.phase_end()


class TestRichProgressReporterFallback:
    def test_non_tty_detection(self) -> None:
        console, _ = _make_non_tty_console()
        reporter = RichProgressReporter(console)
        assert reporter._is_tty is False

    def test_phase_events_emit_lines(self) -> None:
        console, buf = _make_non_tty_console()
        reporter = RichProgressReporter(console)
        reporter.phase_start("hash documents", 3)
        reporter.advance(1)
        reporter.advance(2)
        reporter.phase_end()
        out = buf.getvalue()
        assert "==> hash documents (3 items)" in out
        assert "done (3)" in out

    def test_zero_total_emits_empty_phase(self) -> None:
        console, buf = _make_non_tty_console()
        reporter = RichProgressReporter(console)
        reporter.phase_start("hash documents", 0)
        reporter.phase_end()
        out = buf.getvalue()
        assert "==> hash documents (0 items)" in out
        assert "done" in out

    def test_unknown_total_renders_question_mark(self) -> None:
        console, buf = _make_non_tty_console()
        reporter = RichProgressReporter(console)
        reporter.phase_start("scan vault", None)
        reporter.advance(7)
        reporter.phase_end()
        out = buf.getvalue()
        assert "==> scan vault (? items)" in out
        assert "done (7)" in out

    def test_log_prints_message(self) -> None:
        console, buf = _make_non_tty_console()
        reporter = RichProgressReporter(console)
        reporter.log("component ready")
        assert "component ready" in buf.getvalue()

    def test_multiple_phases_sequential(self) -> None:
        console, buf = _make_non_tty_console()
        reporter = RichProgressReporter(console)
        reporter.phase_start("hash", 2)
        reporter.advance(2)
        reporter.phase_end()
        reporter.phase_start("embed", 2)
        reporter.advance(2)
        reporter.phase_end()
        out = buf.getvalue()
        assert out.count("done") == 2

    def test_threaded_advance_counter(self) -> None:
        console, _ = _make_non_tty_console()
        reporter = RichProgressReporter(console)
        reporter.phase_start("embed documents (dense)", 1000)
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(reporter.advance, 1) for _ in range(1000)]
            for f in futures:
                f.result()
        with reporter._lock:
            observed = reporter._phase_count
        assert observed == 1000
        reporter.phase_end()

    def test_context_manager_non_tty(self) -> None:
        console, _ = _make_non_tty_console()
        with RichProgressReporter(console) as reporter:
            reporter.phase_start("scan", 1)
            reporter.advance(1)
            reporter.phase_end()

    def test_protocol_compliance(self) -> None:
        console, _ = _make_non_tty_console()
        reporter = RichProgressReporter(console)
        assert isinstance(reporter, ProgressReporter)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
