"""Tests for the interactive jobs interface.

Operator feedback is a rendered artefact, so every assertion here runs against
what the interface actually painted, driven by real key presses through
Textual's pilot. Asserting on the model instead would prove only that a value
was computed, which is the failure mode this project has already paid for once.

Controls go to a real loopback service that records the requests it receives,
so a test can distinguish an action that was refused before it was sent from
one that was sent and answered.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import threading
import time
import typing

import pytest

from ..cli._jobs_tui import JobsTuiApp

pytestmark = [pytest.mark.unit]

_HANDOFF_TIMEOUT = 5.0


def _job(
    job_id: str,
    *,
    phase: str = "running",
    state: str = "running",
    root: str = "Y:/code/vaultspec-rag-worktrees/main",
    completed: int = 300,
    total: int | None = 1000,
    remaining: float | None = 140.0,
    rate: float | None = 5.0,
    capabilities: dict[str, bool] | None = None,
) -> dict[str, object]:
    """Build one job resource in the shape the service publishes."""
    return {
        "id": job_id,
        "revision": 3,
        "phase": phase,
        "state": state,
        "desired_state": state,
        "source": "code",
        "trigger": "tool",
        "started_at": 1000.0,
        "finished_at": None,
        "admission_acquired_at": 1001.0,
        "runtime_seconds": 75.0,
        "last_progress_age_seconds": 1.0,
        "stalled": False,
        "progress_rate_per_second": rate,
        "estimated_remaining_seconds": remaining,
        "progress": {
            "step": "embed + upsert chunks",
            "completed": completed,
            "total": total,
            "last_updated": 1070.0,
        },
        "initiator": {
            "kind": "tool",
            "command": "reindex_codebase",
            "project_root": root,
        },
        "capabilities": capabilities
        if capabilities is not None
        else {
            "pausable": True,
            "resumable": False,
            "cancellable": True,
            "retryable": False,
            "deletable": False,
            "force_killable": False,
        },
    }


class _ControlServer:
    """A real loopback service recording every control request it receives."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        recorder = self.requests

        class _Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                return

            def _answer(self, payload: dict[str, object]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                recorder.append(("GET", self.path))
                if self.path.startswith("/logs"):
                    self._answer(
                        {
                            "ok": True,
                            "groups": [
                                {"source": "service", "lines": ["a logged line"]}
                            ],
                        }
                    )
                    return
                self._answer({"ok": True, "jobs": [], "total": 0, "returned": 0})

            def do_PUT(self) -> None:
                recorder.append(("PUT", self.path))
                self._answer({"ok": True, "code": "accepted", "job": {}})

            def do_POST(self) -> None:
                recorder.append(("POST", self.path))
                self._answer({"ok": True, "code": "accepted", "job": {}})

            def do_DELETE(self) -> None:
                recorder.append(("DELETE", self.path))
                self._answer({"ok": True, "code": "deleted", "job": {}})

        self.server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=_HANDOFF_TIMEOUT)

    def control_paths(self) -> list[str]:
        return [path for method, path in self.requests if method != "GET"]


def _app(
    jobs: list[dict[str, object]],
    port: int,
) -> JobsTuiApp:
    def fetch() -> dict[str, object] | None:
        return {"jobs": jobs, "total": len(jobs), "returned": len(jobs)}

    # A long interval keeps the periodic refresh out of the way; every test
    # drives the first load explicitly.
    return JobsTuiApp(fetch=fetch, port=port, interval=3600.0)


def _screen_text(app: JobsTuiApp) -> str:
    """Return what the interface actually painted, as text."""
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


@pytest.fixture
def control_service() -> typing.Iterator[_ControlServer]:
    server = _ControlServer()
    try:
        yield server
    finally:
        server.close()


class TestRenderedRows:
    """What the operator can read off the screen."""

    @pytest.mark.asyncio
    async def test_the_row_shows_the_full_project_path(
        self, control_service: _ControlServer
    ) -> None:
        app = _app([_job("abc123def456")], control_service.port)
        async with app.run_test(size=(200, 24)) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        # The basename alone cannot distinguish two worktrees of one repo,
        # and the discriminating part of a root is its tail - so the tail is
        # what must survive when the column cannot show the whole path.
        assert "worktrees/main" in painted

    @pytest.mark.asyncio
    async def test_the_row_shows_elapsed_and_remaining_time(
        self, control_service: _ControlServer
    ) -> None:
        app = _app([_job("abc123def456")], control_service.port)
        async with app.run_test(size=(200, 24)) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "1m15s" in painted, "elapsed runtime must be on the row"
        assert "2m20s left" in painted, "the estimate must be on the row"

    @pytest.mark.asyncio
    async def test_an_absent_estimate_is_not_rendered_as_zero(
        self, control_service: _ControlServer
    ) -> None:
        app = _app(
            [_job("abc123def456", remaining=None, rate=None)],
            control_service.port,
        )
        async with app.run_test(size=(200, 24)) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "left" not in painted, "no estimate must not render as a duration"
        assert "0s" not in painted, "unknown must never be painted as zero"

    @pytest.mark.asyncio
    async def test_the_progress_bar_fits_the_column_it_lands_in(
        self, control_service: _ControlServer
    ) -> None:
        """The bar is sized from the terminal, not from a constant."""
        job = [_job("abc123def456")]
        narrow = _app(job, control_service.port)
        async with narrow.run_test(size=(120, 24)) as pilot:
            await _ready(pilot, narrow)
            narrow_cells = narrow._bar_cells

        wide = _app(job, control_service.port)
        async with wide.run_test(size=(260, 24)) as pilot:
            await _ready(pilot, wide)
            wide_cells = wide._bar_cells

        assert wide_cells > narrow_cells, (
            "a wider terminal must give the bar more room, not the same room"
        )


class TestResponsiveLayout:
    """One composition, reflowed from the width the terminal reports."""

    @pytest.mark.asyncio
    async def test_a_wide_terminal_shows_the_log_beside_the_table(
        self, control_service: _ControlServer
    ) -> None:
        app = _app([_job("abc123def456")], control_service.port)
        async with app.run_test(size=(200, 24)) as pilot:
            await _ready(pilot, app)
            classes = app.screen.classes
            log_visible = app.query_one("#logpane").display

        assert "-wide" in classes
        assert log_visible, "a wide terminal shows both panes at once"

    @pytest.mark.asyncio
    async def test_a_narrow_terminal_hides_the_log_until_asked(
        self, control_service: _ControlServer
    ) -> None:
        app = _app([_job("abc123def456")], control_service.port)
        async with app.run_test(size=(80, 24)) as pilot:
            await _ready(pilot, app)
            assert "-narrow" in app.screen.classes
            assert not app.query_one("#logpane").display

            await pilot.press("l")
            await pilot.pause()
            assert app.query_one("#logpane").display, "toggling must reveal the log"
            assert not app.query_one("#jobs").display, (
                "a narrow terminal shows one pane at a time, not two squeezed"
            )


class TestCapabilityGating:
    """An action the service would refuse is not offered and not sent."""

    @pytest.mark.asyncio
    async def test_a_permitted_action_reaches_the_service(
        self, control_service: _ControlServer
    ) -> None:
        app = _app([_job("abc123def456")], control_service.port)
        async with app.run_test(size=(200, 24)) as pilot:
            await _ready(pilot, app)
            await pilot.press("p")
            await pilot.pause()
            await _settle(pilot)

        assert any(
            path.endswith("/desired-state") for path in control_service.control_paths()
        ), "pause is published as permitted, so it must be sent"

    @pytest.mark.asyncio
    async def test_an_unpermitted_action_is_never_sent(
        self, control_service: _ControlServer
    ) -> None:
        """A denied capability must issue no request, by either route.

        There are two gates and the test drives both, because either one alone
        passing would hide the other's removal. Pressing the key exercises the
        binding gate, which refuses before the action method is ever entered.
        Calling the action method directly exercises the check inside it, which
        is what still has to hold when a binding fires anyway.

        Proven able to fail: deleting the capability check in ``_actionable``
        leaves the key press still blocked but makes the direct call reach the
        service, failing on the empty-requests assertion; restored, it passes.
        """
        app = _app([_job("abc123def456")], control_service.port)
        async with app.run_test(size=(200, 24)) as pilot:
            await _ready(pilot, app)
            # ``deletable`` is False on this job.
            await pilot.press("d")
            await pilot.pause()
            app.action_job_delete()
            await pilot.pause()
            await _settle(pilot)

        assert control_service.control_paths() == [], (
            "a capability the service denies must not produce a request"
        )

    @pytest.mark.asyncio
    async def test_the_footer_disables_rather_than_hides_a_denied_action(
        self, control_service: _ControlServer
    ) -> None:
        app = _app([_job("abc123def456")], control_service.port)
        async with app.run_test(size=(200, 24)) as pilot:
            await _ready(pilot, app)
            # ``None`` greys the key; ``False`` would remove it entirely, and
            # an operator cannot learn a control exists from its absence.
            assert app.check_action("job_delete", ()) is None
            assert app.check_action("job_pause", ()) is True
            painted = _screen_text(app)

        assert "Delete" in painted, "a denied action stays visible, greyed"


class TestPendingControl:
    """A requested state is never shown as an observed one."""

    @pytest.mark.asyncio
    async def test_a_requested_control_renders_as_requested(
        self, control_service: _ControlServer
    ) -> None:
        app = _app([_job("abc123def456")], control_service.port)
        async with app.run_test(size=(200, 24)) as pilot:
            await _ready(pilot, app)
            await pilot.press("p")
            await pilot.pause()
            painted = _screen_text(app)

        assert "pause requested" in painted, (
            "the view must say the control was requested, not that it took effect"
        )
        assert "paused" not in painted, (
            "an unacknowledged request must not be painted as the new state"
        )


class TestLogPane:
    """The log region is scoped to the selected job."""

    @pytest.mark.asyncio
    async def test_the_selected_job_scopes_the_log_request(
        self, control_service: _ControlServer
    ) -> None:
        app = _app([_job("abc123def456")], control_service.port)
        async with app.run_test(size=(200, 24)) as pilot:
            await _ready(pilot, app)
            await _settle(pilot)
            painted = _screen_text(app)

        log_requests = [
            path
            for method, path in control_service.requests
            if method == "GET" and path.startswith("/logs")
        ]
        assert log_requests, "selecting a row must fetch that job's log"
        assert any("abc123def456" in path for path in log_requests), (
            "the log request must carry the selected job id"
        )
        assert "a logged line" in painted, "log lines must reach the screen"


async def _ready(pilot: typing.Any, app: JobsTuiApp) -> None:
    """Wait until the interface has completed its first real paint.

    Mounting, the threaded fetch, and the deferred column division each take
    their own turn of the event loop, so a single pause can observe a screen
    that has a summary but no rows. Asserting there would be asserting about
    a half-drawn frame.
    """
    deadline = time.monotonic() + _HANDOFF_TIMEOUT
    while time.monotonic() < deadline:
        await pilot.pause()
        table = app.query("#jobs")
        if (
            app._jobs
            and table
            and table.only_one().row_count == len(app._jobs)
            and app._bar_cells > 0
            and not any(worker.is_running for worker in pilot.app.workers)
        ):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("the interface never completed its first paint")


async def _settle(pilot: typing.Any) -> None:
    """Wait for the interface's worker threads to finish their requests."""
    deadline = time.monotonic() + _HANDOFF_TIMEOUT
    while time.monotonic() < deadline:
        await pilot.pause()
        if not any(worker.is_running for worker in pilot.app.workers):
            return
    raise AssertionError("the interface's workers did not settle")
