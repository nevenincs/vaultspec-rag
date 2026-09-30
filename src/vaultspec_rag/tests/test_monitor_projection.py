"""Rendered monitoring of real service activity projections without inference."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import cast

import pytest
from textual.widgets import DataTable

from ..cli._jobs_tui import ServerWatchApp
from ..cli._jobs_tui_cells import search_timings_line
from ..cli._jobs_tui_palette import semantic_tones
from ..cli._jobs_tui_payload import search_activity_error
from ..cli._jobs_tui_status import ServiceStatusHeader, render_status_details
from ..server._search_activity import (
    SearchActivityCompletion,
    SearchActivityLedger,
    SearchActivityStart,
)
from ._jobs_tui_harness import _screen_text, _settle

pytestmark = pytest.mark.unit


def _empty_jobs() -> dict[str, object]:
    return {"jobs": [], "total": 0, "summary": {}}


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(200, 35), (80, 35)])
async def test_queued_search_transitions_on_the_rendered_monitor(
    unused_tcp_port: int, size: tuple[int, int]
) -> None:
    ledger = SearchActivityLedger(max_active=1)
    first = ledger.start(SearchActivityStart("busy", "first query", "code", "/repo", 4))
    app = ServerWatchApp(
        fetch=_empty_jobs, port=unused_tcp_port, interval=3600, watch_mode="server"
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        waiting = executor.submit(
            ledger.start,
            SearchActivityStart("waiting", "queued query", "vault", "/repo", 4),
        )
        try:
            deadline = time.monotonic() + 3
            while ledger.snapshot(include_query=True)["queued_count"] != 1:
                if time.monotonic() >= deadline:
                    raise TimeoutError("the real request did not enter the queue")
                await asyncio.sleep(0.005)
            async with app.run_test(size=size) as pilot:
                await pilot.pause()
                await _settle(pilot)
                snapshot = dict(ledger.snapshot(include_query=True))
                app._apply_search_activity(snapshot, app._search.stamps.issue())
                await pilot.press("s")
                await pilot.pause()
                painted = _screen_text(app)
                table = cast("DataTable[object]", app.query_one("#searches", DataTable))
                assert table.row_count == 2
                assert "1 queued" in painted
                assert "queued query" in painted
                assert "waiting" in painted
                ledger.finish(
                    first, completion=SearchActivityCompletion("succeeded", 200)
                )
                second = waiting.result(timeout=3)
                ledger.finish(
                    second, completion=SearchActivityCompletion("succeeded", 200)
                )
                app._apply_search_activity(
                    dict(ledger.snapshot(include_query=True)),
                    app._search.stamps.issue(),
                )
                await pilot.pause()
                assert "0 queued" in _screen_text(app)
                assert "2 recent" in _screen_text(app)
                assert app.selected_search_id == "waiting"
        finally:
            ledger.finish(first, completion=SearchActivityCompletion("cancelled", 499))


@pytest.mark.asyncio
async def test_daemon_health_and_indexing_condition_are_separate(
    unused_tcp_port: int,
) -> None:
    app = ServerWatchApp(
        fetch=_empty_jobs, port=unused_tcp_port, interval=3600, watch_mode="server"
    )
    async with app.run_test(size=(180, 35)) as pilot:
        await pilot.pause()
        await _settle(pilot)
        app._apply_service_status(
            ServiceStatusHeader(
                reachable=True,
                status="degraded",
                degraded_reasons=("storage unavailable",),
                typesafe={"state": "cooldown", "retry_after_seconds": 12},
            ),
            app._status_stamps.issue(),
        )
        app._apply_result(
            {"jobs": [], "total": 0, "summary": {"degraded": 0, "stalled": 0}},
            app._job_stamps.issue(),
        )
        await pilot.pause()
        painted = _screen_text(app)
        assert "service degraded" in painted
        assert "index healthy" in painted
        assert "storage unavailable" in painted
        assert "TypeSafe:" in painted
        assert "standard ranking is used" in painted
        app._apply_service_status(
            ServiceStatusHeader(
                reachable=True, status="error", error="service answered HTTP 503"
            ),
            app._status_stamps.issue(),
        )
        await pilot.pause()
        assert "health error: service answered HTTP 503" in _screen_text(app)


@pytest.mark.parametrize("state", ["off", "pending", "active", "rejected", "cooldown"])
def test_typesafe_renders_daemon_evidence_with_redacted_details(state: str) -> None:
    from ..cli._status_labels import typesafe_label

    snapshot: dict[str, object] = {
        "state": state,
        "model": "systemone",
        "last_success_age_seconds": 10,
        "retry_after_seconds": 8 if state == "cooldown" else 0,
    }
    rendered = render_status_details(
        ServiceStatusHeader(reachable=True, status="ready", typesafe=snapshot),
        semantic_tones(""),
    ).plain
    assert typesafe_label(snapshot) in rendered
    assert "model systemone" in rendered
    assert "last success 10s ago" in rendered
    if state == "cooldown":
        assert "retry in 8s" in rendered


def test_typesafe_diagnostics_keep_units_and_counts() -> None:
    ledger = SearchActivityLedger()
    ticket = ledger.start(SearchActivityStart("units", "query", "code", None, 1))
    ledger.finish(
        ticket,
        completion=SearchActivityCompletion(
            "succeeded",
            200,
            timings={
                "typesafe_query_ms": 125,
                "typesafe_rank_ms": 250,
                "typesafe_input_tokens": 1000,
                "typesafe_requests": 2,
                "typesafe_intent_confidence": 0.8,
                "server_total_seconds": 1.5,
            },
        ),
    )
    record = ledger.snapshot(include_query=True)["recent"][0]
    rendered = search_timings_line(record)
    assert "typesafe_query_ms=125ms" in rendered
    assert "typesafe_rank_ms=250ms" in rendered
    assert "typesafe_input_tokens=1000 ·" in rendered
    assert "typesafe_requests=2" in rendered
    assert "typesafe_intent_confidence=0.8" in rendered
    assert "server_total_seconds=1.5s" in rendered


def test_queued_payload_validation_catches_invalid_record_identity() -> None:
    """Allowing repeated request ids fails the invalid-record assertion."""
    ledger = SearchActivityLedger()
    ticket = ledger.start(SearchActivityStart("identity", "query", "code", None, 1))
    projection = ledger.snapshot(include_query=True)
    snapshot = dict(projection)
    queued = dict(projection["active"][0])
    queued["state"] = "queued"
    snapshot["queued"] = [queued]
    snapshot["queued_count"] = 1
    assert (
        search_activity_error(snapshot)
        == "served-search activity unavailable: invalid record"
    )
    ledger.finish(ticket, completion=SearchActivityCompletion("succeeded", 200))
