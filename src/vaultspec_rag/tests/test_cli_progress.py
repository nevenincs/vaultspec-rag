"""Unit coverage for the long-running-command progress reporter."""

from __future__ import annotations

import contextlib
import io
import re
import sys
from typing import TYPE_CHECKING

import pytest

import vaultspec_rag.cli as _cli

from ..cli._core import _build_console, _stdout_is_tty
from ..cli._progress import StartupStatusReporter

if TYPE_CHECKING:
    from rich.console import Console

pytestmark = [pytest.mark.unit]

# Cursor hide/show and cursor-motion sequences carry no text, so a matcher
# limited to colour codes would leave them in and let an "output is not empty"
# assertion pass on control bytes alone.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07")

# Rich's "dots" spinner draws from the Unicode braille block. Nothing else the
# CLI prints does, which makes a braille character positive proof that a live
# frame - not a plain line - reached the stream.
_SPINNER_RE = re.compile(r"[⠀-⣿]")


class _Clock:
    """Hand-advanced monotonic clock for the heartbeat rate limit."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _plain_console(buffer: io.StringIO) -> Console:
    """Build the console the CLI uses off a terminal."""
    return _build_console(interactive=False, file=buffer)


def _terminal_console(buffer: io.StringIO) -> Console:
    """Build the console the CLI uses on a real terminal."""
    return _build_console(interactive=True, file=buffer)


def _plain(raw: str) -> str:
    return _ANSI_RE.sub("", raw)


def _lines(buffer: io.StringIO) -> list[str]:
    return [
        line.strip() for line in _plain(buffer.getvalue()).splitlines() if line.strip()
    ]


class TestPlainStream:
    """Reporting to a pipe, a file, or a capture buffer."""

    def test_announce_prints_once_off_a_terminal(self):
        """Announce lands exactly once even with interactivity auto-detected."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()) as real_stdout:
            assert not sys.stdout.isatty(), "premise: stdout must not be a terminal"
            # interactive is left unset so the reporter makes the real
            # production decision from the stream it is actually given.
            reporter = StartupStatusReporter(
                json_mode=False, console=_plain_console(buffer)
            )
            with reporter:
                reporter.announce("Starting service...")

            assert real_stdout.getvalue() == ""

        # Exact equality, not a substring: a reporter that wrongly went
        # interactive would wrap this line in cursor and spinner control bytes.
        assert buffer.getvalue() == "Starting service...\n"

    def test_announce_repeats_are_never_suppressed(self):
        """Announce is the started-guarantee, so it is never deduped."""
        buffer = io.StringIO()
        reporter = StartupStatusReporter(
            json_mode=False,
            console=_plain_console(buffer),
            interactive=False,
        )
        with reporter:
            reporter.announce("Starting service...")
            reporter.announce("Starting service...")

        assert _lines(buffer) == ["Starting service...", "Starting service..."]

    def test_stage_dedupes_repeats_but_prints_a_change(self):
        """A repeated activity is silent; a new one prints."""
        buffer = io.StringIO()
        reporter = StartupStatusReporter(
            json_mode=False,
            console=_plain_console(buffer),
            interactive=False,
        )
        with reporter:
            reporter.stage("Provisioning binary")
            reporter.stage("Provisioning binary")
            reporter.stage("Loading models")
            reporter.stage("Loading models")

        assert _lines(buffer) == ["Provisioning binary", "Loading models"]

    def test_heartbeat_is_rate_limited_by_the_injected_clock(self):
        """Ticks inside the interval are dropped, whatever the label says."""
        buffer = io.StringIO()
        clock = _Clock()
        reporter = StartupStatusReporter(
            json_mode=False,
            console=_plain_console(buffer),
            interactive=False,
            static_interval_s=5.0,
            now=clock,
        )
        with reporter:
            reporter.heartbeat("Waiting for readiness")
            clock.now = 1.0
            reporter.heartbeat("Waiting for readiness")
            clock.now = 4.999
            reporter.heartbeat("Still waiting for readiness")

        assert _lines(buffer) == ["Waiting for readiness"]

    def test_heartbeat_still_ticks_on_an_unchanged_label(self):
        """An idle wait stays visible once the interval has elapsed."""
        buffer = io.StringIO()
        clock = _Clock()
        reporter = StartupStatusReporter(
            json_mode=False,
            console=_plain_console(buffer),
            interactive=False,
            static_interval_s=5.0,
            now=clock,
        )
        with reporter:
            reporter.heartbeat("Waiting for readiness")
            clock.now = 5.0
            reporter.heartbeat("Waiting for readiness")
            clock.now = 10.0
            reporter.heartbeat("Waiting for readiness")

        assert _lines(buffer) == ["Waiting for readiness"] * 3

    def test_stage_arms_the_heartbeat_rate_limit(self):
        """A stage counts as a tick, so a heartbeat behind it stays quiet."""
        buffer = io.StringIO()
        clock = _Clock()
        reporter = StartupStatusReporter(
            json_mode=False,
            console=_plain_console(buffer),
            interactive=False,
            static_interval_s=5.0,
            now=clock,
        )
        with reporter:
            reporter.stage("Loading models")
            clock.now = 1.0
            reporter.heartbeat("Loading models")
            clock.now = 6.0
            reporter.heartbeat("Loading models")

        assert _lines(buffer) == ["Loading models", "Loading models"]


class TestJsonMode:
    """A machine-readable verb owes stdout exactly one envelope."""

    @pytest.mark.parametrize("interactive", [False, True])
    def test_json_mode_emits_nothing(self, interactive: bool):
        """No progress reaches the console or stdout, in either mode."""
        buffer = io.StringIO()
        clock = _Clock()
        reporter = StartupStatusReporter(
            json_mode=True,
            console=_plain_console(buffer),
            interactive=interactive,
            static_interval_s=0.0,
            now=clock,
        )
        with contextlib.redirect_stdout(io.StringIO()) as real_stdout:
            with reporter:
                reporter.announce("Starting service...")
                reporter.stage("Loading models")
                clock.now = 60.0
                reporter.heartbeat("Loading models")

            assert real_stdout.getvalue() == ""

        assert buffer.getvalue() == ""


class TestTerminalStream:
    """The live region on the console the CLI builds for a real terminal."""

    def test_the_live_region_actually_paints(self):
        """The region must paint, not merely be constructed.

        This is the regression guard for a live region driven by a console
        that reports itself non-interactive: Rich renders such a region zero
        times, so the operator sees nothing at all for the whole command.

        Both assertions are load-bearing and neither may be relaxed. A bare
        "output is not empty" would stay green through exactly this
        regression, because starting a region emits cursor-hide bytes before
        anything is painted. And the label alone would stay green if the
        reporter fell back to printing plain lines, which is not animation - so
        the spinner glyph is what proves a live frame reached the stream.
        """
        buffer = io.StringIO()
        reporter = StartupStatusReporter(
            json_mode=False,
            console=_terminal_console(buffer),
            interactive=True,
        )
        with reporter:
            reporter.stage("Loading models")
            reporter.heartbeat("Loading models")

        rendered = buffer.getvalue()
        assert "Loading models" in _ANSI_RE.sub("", rendered)
        assert _SPINNER_RE.search(rendered) is not None

    def test_a_shared_console_print_never_lands_inside_a_frame(self):
        """A foreign print during the region gets its own line.

        The start path prints warnings through the shared console while the
        region is open. Rich only erases the frame first when the print and
        the region share one console; a second console on the same stream
        leaves the print concatenated onto the spinner's line.
        """
        buffer = io.StringIO()
        console = _terminal_console(buffer)
        warning = "WARNING: the service interpreter is an ephemeral environment"
        reporter = StartupStatusReporter(
            json_mode=False,
            console=console,
            interactive=True,
        )
        with reporter:
            reporter.stage("Checking GPU support")
            console.print(warning)
            reporter.heartbeat("Starting service... loading models")

        plain = _ANSI_RE.sub("", buffer.getvalue())
        assert warning in plain
        collided = [
            line
            for line in plain.splitlines()
            if warning in line and _SPINNER_RE.search(line) is not None
        ]
        assert collided == [], f"print landed inside a spinner frame: {collided!r}"

    def test_announce_survives_alongside_the_live_region(self):
        """Announced lines still reach the stream while the region runs."""
        buffer = io.StringIO()
        reporter = StartupStatusReporter(
            json_mode=False,
            console=_terminal_console(buffer),
            interactive=True,
        )
        with reporter:
            reporter.stage("Loading models")
            reporter.announce("Service started on port 8766")

        assert "Service started on port 8766" in _ANSI_RE.sub("", buffer.getvalue())

    def test_nested_blocks_share_one_region(self):
        """Re-entering does not open a second region or lose the first."""
        buffer = io.StringIO()
        reporter = StartupStatusReporter(
            json_mode=False,
            console=_terminal_console(buffer),
            interactive=True,
        )
        with reporter:
            reporter.stage("Provisioning binary")
            with reporter:
                reporter.stage("Loading models")
            # The inner exit must leave the region usable, not tear it down.
            reporter.stage("Waiting for readiness")

        assert "Waiting for readiness" in _ANSI_RE.sub("", buffer.getvalue())


class TestStreamPlacement:
    """Where each mode's output lands, with no console supplied."""

    def test_static_lines_go_to_stderr_and_leave_stdout_clean(self):
        """Off a terminal, stdout stays the parseable result channel."""
        out, err = io.StringIO(), io.StringIO()
        reporter = StartupStatusReporter(json_mode=False, interactive=False)
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            reporter,
        ):
            reporter.announce("Starting service...")
            reporter.stage("Loading models")

        assert out.getvalue() == ""
        assert _plain(err.getvalue()).splitlines() == [
            "Starting service...",
            "Loading models",
        ]

    def test_json_mode_writes_to_neither_stream(self):
        """The one structured envelope owes stdout, and stderr, silence."""
        out, err = io.StringIO(), io.StringIO()
        reporter = StartupStatusReporter(json_mode=True, interactive=False)
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            reporter,
        ):
            reporter.announce("Starting service...")
            reporter.stage("Loading models")
            reporter.heartbeat("Loading models")

        assert out.getvalue() == ""
        assert err.getvalue() == ""


class TestSharedConsoleWiring:
    """How the reporter reaches the shared console, and how it is built."""

    def test_the_cli_console_matches_the_real_stdout(self):
        """Neither hardcoded on nor hardcoded off."""
        assert _cli.console.is_interactive == _stdout_is_tty()

    def test_the_factory_honours_the_interactivity_it_is_given(self):
        """Both modes are reachable through the one construction site."""
        assert _build_console(interactive=True, file=io.StringIO()).is_interactive
        assert not _build_console(interactive=False, file=io.StringIO()).is_interactive

    def test_the_console_is_read_late_from_the_package_namespace(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """A console swapped after construction must still be observed.

        Tests across this suite substitute ``vaultspec_rag.cli.console`` at
        runtime. Binding it at import - or even at reporter construction -
        makes every one of those substitutions inert while leaving them
        looking effective, so this asserts the swap is honoured even when it
        lands after the reporter already exists.
        """
        buffer = io.StringIO()
        reporter = StartupStatusReporter(json_mode=False, interactive=True)
        monkeypatch.setattr(_cli, "console", _terminal_console(buffer))

        with reporter:
            reporter.stage("Loading models")

        assert "Loading models" in _plain(buffer.getvalue())
