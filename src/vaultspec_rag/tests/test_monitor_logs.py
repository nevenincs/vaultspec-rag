"""Live inspection over production HTTP routes and real managed-log files."""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
import uuid
from typing import TYPE_CHECKING

import pytest
import uvicorn

from ..cli._jobs_tui import ServerWatchApp
from ..cli._jobs_tui_constants import LOG_LINES
from ..config._settings import get_config
from ..job_models import JobSource
from ..jobs import record_finish, record_start
from ..logging_config import (
    MAX_MANAGED_LOG_RECORD_BYTES,
    QDRANT_LOG_NAME,
    query_managed_logs,
)
from ..server import ServerRouteRuntime, create_http_app
from ..server._search_activity import SearchActivityCompletion, SearchActivityStart
from ..server._state import search_activity_ledger
from ..service import ServiceRegistry
from ..serviceclient._discovery import _merge_service_status
from ..serviceclient._transport import _try_http_admin
from ._jobs_tui_harness import _screen_text, _settle

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def monitor_http(isolated_status_dir: Path) -> Iterator[tuple[int, Path]]:
    """Serve the actual read routes without a daemon lifespan or inference."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = int(listener.getsockname()[1])
    _merge_service_status(
        {"pid": os.getpid(), "port": port, "service_token": "monitor-test-token"}
    )
    application = create_http_app(
        ServerRouteRuntime(
            token="monitor-test-token", registry=ServiceRegistry(), port=port
        ),
        lifespan=None,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
    )
    worker = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started:
            if not worker.is_alive() or time.monotonic() >= deadline:
                raise TimeoutError("production test routes did not start")
            time.sleep(0.005)
        yield port, isolated_status_dir
    finally:
        server.should_exit = True
        worker.join(timeout=5)
        listener.close()
        if worker.is_alive():
            raise TimeoutError("production test routes did not stop")


async def _wait_for_log(app: ServerWatchApp, expected: str) -> str:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        rendered = _screen_text(app)
        if expected in rendered:
            return rendered
        await asyncio.sleep(0.01)
    raise AssertionError(f"focused log did not show {expected!r}: {_screen_text(app)}")


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(220, 40), (80, 40)])
async def test_selected_job_and_request_logs_update_without_reselection(
    monitor_http: tuple[int, Path],
    size: tuple[int, int],
) -> None:
    port, directory = monitor_http
    job_id = record_start(JobSource.CODE, "tool", project_root=directory)
    ledger = search_activity_ledger()
    request_id = uuid.uuid4().hex
    ticket = ledger.start(
        SearchActivityStart(request_id, "inspection query", "code", str(directory), 3)
    )
    path = directory / get_config().log_file
    path.write_text(
        f"job_id={job_id} initial-job\nrequest_id={request_id} initial-request\n",
        encoding="utf-8",
    )
    (directory / QDRANT_LOG_NAME).write_text("backend-own-record\n", encoding="utf-8")

    def fetch_jobs() -> dict[str, object] | None:
        return _try_http_admin("get_jobs", {"limit": 20}, port)

    app = ServerWatchApp(fetch=fetch_jobs, port=port, interval=1, watch_mode="server")
    try:
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await pilot.press("l")
            await _wait_for_log(app, "initial-job")
            with path.open("a", encoding="utf-8") as log:
                log.write(f"job_id={job_id} next-job\n")
            job_frame = await _wait_for_log(app, "next-job")
            assert app.selected_id == job_id
            assert "indexing job" in job_frame
            assert "initial-request" not in job_frame
            # Close the narrow overlay before changing its originating lane.
            await pilot.press("l", "s", "l")
            request_frame = await _wait_for_log(app, "initial-request")
            assert "served request" in request_frame
            assert "next-job" not in request_frame
            with path.open("a", encoding="utf-8") as log:
                log.write(f"request_id={request_id} next-request\n")
            await _wait_for_log(app, "next-request")
            assert app.selected_search_id == request_id
            log_view = app._log_view()
            assert log_view is not None
            app.set_focus(log_view)
            await pilot.pause()
            # Removing this guard failed this assertion in the wide view;
            # restoring it passed. The indexing job remains selected beside it.
            assert not app._job_action_context_available()
            await pilot.press("m")
            global_frame = await _wait_for_log(app, "backend-own-record")
            assert "[service]" in global_frame and "[qdrant]" in global_frame
            assert "next-job" in global_frame and "next-request" in global_frame
    finally:
        record_finish(job_id, result="completed")
        ledger.finish(ticket, completion=SearchActivityCompletion("succeeded", 200))


@pytest.mark.asyncio
async def test_focused_logs_report_the_actual_tail_and_server_truncation(
    monitor_http: tuple[int, Path],
) -> None:
    """An unconditional queued resize tail-scroll failed the retained top
    assertion (exit 1); honoring current follow state passed it (exit 0).
    """
    port, directory = monitor_http
    job_id = record_start(JobSource.CODE, "tool", project_root=directory)
    path = directory / get_config().log_file
    records = [f"job_id={job_id} bounded-record-{index}" for index in range(205)]
    records.append(f"job_id={job_id} oversized " + "z" * MAX_MANAGED_LOG_RECORD_BYTES)
    path.write_text("\n".join(records) + "\n", encoding="utf-8")

    def fetch_jobs() -> dict[str, object] | None:
        return _try_http_admin("get_jobs", {"limit": 20}, port)

    app = ServerWatchApp(fetch=fetch_jobs, port=port, interval=3600, watch_mode="jobs")
    try:
        async with app.run_test(size=(220, 40)) as pilot:
            await pilot.pause()
            await _settle(pilot)
            painted = await _wait_for_log(app, "TRUNCATED by server")
            assert "tail 200" in painted
            assert "shortened 1 records" in painted
            assert "service: 200 records" in painted
            assert "refreshed" in painted
            log_view = app._log_view()
            assert log_view is not None and log_view.max_scroll_y > 0
            # Queue the same tail callback used after a resize, then let the
            # reader navigate before the framework delivers that callback.
            log_view.call_after_refresh(log_view.scroll_followed_tail)
            log_view.jump_top()
            await pilot.pause()
            assert log_view.scroll_offset.y == 0, (
                "queued tail scroll overrode navigation"
            )
            with path.open("a", encoding="utf-8") as log:
                log.write(f"job_id={job_id} latest-while-reading\n")
            app.refresh_focused_logs()
            await _settle(pilot)
            await pilot.pause()
            assert "latest-while-reading" in log_view._records[-1].raw
            assert log_view.scroll_offset.y == 0
    finally:
        record_finish(job_id, result="completed")


@pytest.mark.asyncio
async def test_focused_log_rejects_stale_or_mis_scoped_payloads(
    monitor_http: tuple[int, Path],
) -> None:
    """Bypassing ordering and filter identity each failed its assertion, then passed
    after restoration: current-record and invalid-service-response respectively.
    """
    port, directory = monitor_http
    job_id = record_start(JobSource.CODE, "tool", project_root=directory)
    path = directory / get_config().log_file
    path.write_text(f"job_id={job_id} old-record\n", encoding="utf-8")

    def fetch_jobs() -> dict[str, object] | None:
        return _try_http_admin("get_jobs", {"limit": 20}, port)

    app = ServerWatchApp(fetch=fetch_jobs, port=port, interval=3600, watch_mode="jobs")
    try:
        async with app.run_test(size=(200, 40)) as pilot:
            await pilot.pause()
            await _settle(pilot)
            await _wait_for_log(app, "old-record")
            stale = dict(
                query_managed_logs(
                    LOG_LINES, source="service", job_id=job_id, status_dir=directory
                )
            )
            stale_generation = app._focused_log.stamps.issue()
            path.write_text(f"job_id={job_id} current-record\n", encoding="utf-8")
            fresh = dict(
                query_managed_logs(
                    LOG_LINES, source="service", job_id=job_id, status_dir=directory
                )
            )
            app._apply_logs(("job", job_id), fresh, app._focused_log.stamps.issue())
            app._apply_logs(("job", job_id), stale, stale_generation)
            await pilot.pause()
            painted = _screen_text(app)
            assert "current-record" in painted
            assert "old-record" not in painted
            wrong_scope = dict(
                query_managed_logs(LOG_LINES, source="service", status_dir=directory)
            )
            app._apply_logs(
                ("job", job_id), wrong_scope, app._focused_log.stamps.issue()
            )
            await pilot.pause()
            invalid = _screen_text(app)
            assert "invalid service response" in invalid
            assert "current-record" in invalid
            assert "refreshed" in invalid
    finally:
        record_finish(job_id, result="completed")
