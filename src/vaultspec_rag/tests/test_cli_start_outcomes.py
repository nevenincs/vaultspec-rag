"""The three failure outcomes of the ``server start`` health wait.

``start_died``, ``start_timeout``, and ``start_interrupted`` had no coverage at
all, which mattered because the wait's success condition was changed: it now
completes once the daemon can serve rather than when ``/health`` reports the
literal status ``ready``. Nothing protected the failure side of that change.

No mocks, patches, or fakes. Liveness is a real process - this interpreter for
the alive case, a genuinely exited subprocess for the dead one - and the silent
daemon is a real closed port, so ``_try_http_health`` performs a real connection
attempt and really fails. The interrupt is delivered by a real reporter raising
``KeyboardInterrupt`` from the wait, which is where a console Ctrl+C lands.
"""

from __future__ import annotations

import http.server
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING, cast

import pytest
import typer

from ..cli._progress import StartupStatusReporter
from ..cli._service_start import _await_service_ready, _ServiceReadinessRequest
from ._http_stubs import QuietHandler
from ._ports import free_loopback_port

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _dead_pid() -> int:
    """Return the pid of a process that has really exited.

    ``wait`` before returning, so the pid is genuinely reaped rather than
    racing the liveness probe the test is about to perform.
    """
    proc = subprocess.Popen(  # fixed argv, no shell
        [sys.executable, "-c", "raise SystemExit(0)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.wait(timeout=30)
    return proc.pid


class _InterruptingReporter(StartupStatusReporter):
    """A real reporter that interrupts the wait on its first heartbeat.

    A console Ctrl+C surfaces as ``KeyboardInterrupt`` at an interpreter check
    inside the polling loop, and the heartbeat is a point the loop genuinely
    reaches on every iteration. Raising there reproduces the operator's
    interrupt without patching the clock or the transport.
    """

    def heartbeat(self, label: str) -> None:
        del label
        raise KeyboardInterrupt


@pytest.mark.usefixtures("isolated_singleton_dirs")
class TestStartFailureOutcomes:
    """Each terminal failure emits exactly one envelope and exits non-zero."""

    def _envelope(self, captured: str) -> dict[str, object]:
        documents = [
            json.loads(line)
            for line in captured.splitlines()
            if line.strip().startswith("{")
        ]
        # The lifecycle contract is one structured document per exit path, so
        # the count is asserted, not just the content of the first match.
        assert len(documents) == 1, f"expected one envelope, got {documents}"
        return documents[0]

    def test_a_daemon_that_exited_reports_start_died(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log_path = tmp_path / "service.log"
        log_path.write_text("Traceback: model load failed\n", encoding="utf-8")
        with pytest.raises(typer.Exit) as exit_info:
            _await_service_ready(
                _ServiceReadinessRequest(
                    pid=_dead_pid(),
                    port=free_loopback_port(),
                    log_path=log_path,
                    json_mode=True,
                    started_at=time.perf_counter(),
                )
            )
        assert exit_info.value.exit_code == 1
        envelope = self._envelope(capsys.readouterr().out)
        assert envelope["ok"] is False
        assert envelope["error"] == "start_died"

    def test_a_live_but_silent_daemon_reports_start_timeout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # This interpreter is alive and the port answers nothing, which is the
        # wedged-daemon shape: the process never dies, health never arrives.
        log_path = tmp_path / "service.log"
        with pytest.raises(typer.Exit) as exit_info:
            _await_service_ready(
                _ServiceReadinessRequest(
                    pid=__import__("os").getpid(),
                    port=free_loopback_port(),
                    log_path=log_path,
                    json_mode=True,
                    started_at=time.perf_counter(),
                    deadline=0.35,
                )
            )
        assert exit_info.value.exit_code == 1
        envelope = self._envelope(capsys.readouterr().out)
        assert envelope["error"] == "start_timeout"
        data = cast("dict[str, object]", envelope["data"])
        # The timeout names the last phase the daemon published rather than a
        # bare "not ready"; without a daemon at all that is the waiting label.
        assert data["last_phase"] == "waiting for the daemon to come up"

    def test_an_interrupted_wait_reports_start_interrupted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log_path = tmp_path / "service.log"
        with (
            _InterruptingReporter(json_mode=True) as reporter,
            pytest.raises(typer.Exit) as exit_info,
        ):
            _await_service_ready(
                _ServiceReadinessRequest(
                    pid=__import__("os").getpid(),
                    port=free_loopback_port(),
                    log_path=log_path,
                    json_mode=True,
                    started_at=time.perf_counter(),
                    progress=reporter,
                )
            )
        # Interrupting the foreground wait leaves the detached daemon starting,
        # so the requested state is unconfirmed and the exit must stay non-zero.
        assert exit_info.value.exit_code == 1
        envelope = self._envelope(capsys.readouterr().out)
        assert envelope["error"] == "start_interrupted"

    def test_a_serving_daemon_is_not_reported_as_a_timeout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A degraded-but-serving daemon ends the wait as a success.

        This is the regression guard for a start that burned its whole deadline
        against a daemon that had been answering the entire time. The payload is
        the shape a real service reports once any indexing job has ever failed:
        every infrastructure signal healthy, the only complaint job history.
        A real HTTP server stands in for the daemon's health surface.
        """
        import http.server
        import threading

        port = free_loopback_port()
        payload = json.dumps(
            {
                "status": "degraded",
                "models_loaded": True,
                "qdrant": {"mode": "server", "alive": True},
                "degraded_reasons": ["the latest indexing job failed: other"],
            }
        ).encode("utf-8")

        class _Health(QuietHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = http.server.HTTPServer(("127.0.0.1", port), _Health)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            log_path = tmp_path / "service.log"
            _await_service_ready(
                _ServiceReadinessRequest(
                    pid=__import__("os").getpid(),
                    port=port,
                    log_path=log_path,
                    json_mode=True,
                    started_at=time.perf_counter(),
                    deadline=5.0,
                )
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        envelope = self._envelope(capsys.readouterr().out)
        assert envelope["ok"] is True
        data = cast("dict[str, object]", envelope["data"])
        assert data["status"] == "started"
        # The degradation travels with the success rather than being dropped.
        assert data["health"] == "degraded"
        assert data["degraded_reasons"] == ["the latest indexing job failed: other"]


def _visible(rendered: str) -> str:
    """Strip ANSI so an assertion reads the text a human would see."""
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", rendered)


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_the_daemons_phase_reaches_the_terminal_during_the_wait(
    tmp_path: Path,
) -> None:
    """The phase the daemon publishes is rendered as bytes on the console.

    This closes the loop that unit coverage kept missing. Other tests assert
    what ``_startup_phase_label`` RETURNS; none of them constructed a console,
    so every one stayed green through a long period in which the wait's live
    region emitted nothing at all and no operator ever saw a phase. The subject
    here is deliberately the rendered output, not the label function: assert on
    bytes written to a real ``Console``, never on a helper's return value.
    """
    from rich.console import Console

    port = free_loopback_port()
    # models_loaded false keeps the daemon un-servable, so the wait keeps
    # polling and keeps reporting instead of exiting on the first success.
    payload = json.dumps({"status": "degraded", "models_loaded": False}).encode("utf-8")

    class _Health(QuietHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    buffer = io.StringIO()
    console = Console(
        file=buffer,
        legacy_windows=False,
        highlight=False,
        force_terminal=True,
        force_interactive=True,
        width=100,
    )
    server = http.server.HTTPServer(("127.0.0.1", port), _Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        log_path = tmp_path / "service.log"
        with (
            StartupStatusReporter(
                json_mode=False, console=console, interactive=True
            ) as reporter,
            pytest.raises(typer.Exit),
        ):
            _await_service_ready(
                _ServiceReadinessRequest(
                    pid=os.getpid(),
                    port=port,
                    log_path=log_path,
                    json_mode=False,
                    started_at=time.perf_counter(),
                    progress=reporter,
                    deadline=0.6,
                )
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    rendered = _visible(buffer.getvalue())
    assert "Starting service..." in rendered
    # The daemon's own health status, carried through _startup_phase_label and
    # actually painted. Asserting merely that output is non-empty would NOT do:
    # the live region emits ~12 bytes of cursor hide/show codes regardless of
    # whether it ever paints, so a byte-count check stays green through exactly
    # the regression this test exists to catch.
    assert "serving, health: degraded" in rendered
