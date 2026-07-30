"""Direct, compute-free coverage for the bounded served-search activity ledger."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Protocol, cast

import pytest
from starlette.requests import Request

from ..server._search_activity import (
    DEFAULT_MAX_ACTIVE_SEARCHES,
    SearchActivityCompletion,
    SearchActivityFilters,
    SearchActivityLedger,
    SearchActivityStart,
    SearchActivityTicket,
)

if TYPE_CHECKING:
    from collections.abc import Sized

pytestmark = [pytest.mark.unit]


class _ConditionWaiters(Protocol):
    """The observable wait queue exposed by CPython's real Condition."""

    _waiters: Sized


def _start(
    ledger: SearchActivityLedger,
    request_id: str,
    *,
    query: str | None = None,
    search_type: str = "vault",
    root: str = "Y:/workspace",
) -> SearchActivityTicket:
    """Start one ordinary served-query record through the production API."""
    return ledger.start(
        SearchActivityStart(
            request_id=request_id,
            query=query or f"query {request_id}",
            search_type=search_type,
            root=root,
            top_k=7,
        )
    )


def test_search_activity_preserves_query_only_for_authenticated_serialization() -> None:
    ledger = SearchActivityLedger(max_active=3, max_recent=3)
    query = "credential rotation investigation for incident 124"
    _start(ledger, "query-privacy", query=query)

    authenticated = ledger.snapshot(include_query=True)
    active = authenticated["active"]
    assert len(active) == 1
    assert active[0]["query"] == query
    assert active[0]["source"] == "vault"
    assert active[0]["type"] == "vault"
    assert active[0]["top_k"] == 7

    redacted = ledger.snapshot(include_query=False)
    redacted_active = redacted["active"]
    assert len(redacted_active) == 1
    assert "query" not in redacted_active[0]
    assert redacted_active[0]["query_redacted"] is True
    assert query not in str(redacted)


def test_search_activity_transitions_once_from_active_to_terminal() -> None:
    ledger = SearchActivityLedger(max_active=3, max_recent=3)
    ticket = _start(ledger, "once")

    assert ledger.finish(
        ticket,
        completion=SearchActivityCompletion(
            outcome="success",
            status_code=200,
            result_count=4,
            timings={"queue_wait_seconds": 0.02, "qdrant_seconds": 0.11},
        ),
    )
    assert not ledger.finish(
        ticket,
        completion=SearchActivityCompletion(
            outcome="failed",
            status_code=500,
            error_code="should_not_replace_first_terminal_outcome",
        ),
    )

    snapshot = ledger.snapshot(include_query=True)
    assert snapshot["active"] == []
    assert snapshot["counts"] == {
        "active": 0,
        "recent": 1,
        "total": 1,
    }
    record = snapshot["recent"][0]
    assert record["request_id"] == "once"
    assert record["state"] == "terminal"
    assert record["outcome"] == "success"
    assert record["status_code"] == 200
    assert record["result_count"] == 4
    assert record["timings"] == {
        "qdrant_seconds": 0.11,
        "queue_wait_seconds": 0.02,
    }
    assert record["finished_at"] is not None
    assert record["total_seconds"] is not None


def test_search_activity_capacity_backpressures_until_every_query_is_reviewable() -> (
    None
):
    """A full active ledger waits rather than retaining an unbounded overflow ticket.

    Proven able to fail: removing ``notify`` in ``finish`` leaves the waiting
    served query unadmitted and fails at the named admission assertion below.
    Restored, it continues only after the existing record terminalizes and
    both complete rows remain reviewable.
    """
    ledger = SearchActivityLedger(max_active=1, max_recent=3)
    active = _start(ledger, "active")
    admitted = threading.Event()
    terminalized = threading.Event()
    waiting_ticket: list[SearchActivityTicket] = []

    def wait_for_active_slot() -> None:
        ticket = _start(
            ledger,
            "waiting-success",
            query="the query held until an active activity slot is free",
            search_type="code",
            root="Y:/other",
        )
        waiting_ticket.append(ticket)
        admitted.set()
        assert ledger.finish(
            ticket,
            completion=SearchActivityCompletion(outcome="success", status_code=200),
        )
        terminalized.set()

    waiter = threading.Thread(target=wait_for_active_slot, daemon=True)
    waiter.start()

    assert not admitted.wait(timeout=0.1), (
        "a full active ledger must backpressure instead of creating overflow activity"
    )

    bounded = ledger.snapshot(include_query=True)
    assert bounded["counts"] == {
        "active": 1,
        "recent": 0,
        "total": 1,
    }
    assert [record["request_id"] for record in bounded["active"]] == ["active"]

    assert ledger.finish(
        active,
        completion=SearchActivityCompletion(outcome="success", status_code=200),
    )
    assert admitted.wait(timeout=1.0), "the blocked query must be admitted on release"
    assert terminalized.wait(timeout=1.0), "the newly admitted query must terminalize"
    waiter.join(timeout=1.0)
    assert not waiter.is_alive(), "the waiter must not remain blocked after release"
    assert len(waiting_ticket) == 1
    assert waiting_ticket[0].request_id == "waiting-success"
    assert not hasattr(waiting_ticket[0], "query"), (
        "a route ticket is a reference, not another full-query activity record"
    )

    terminal_records = ledger.snapshot(include_query=True)
    assert terminal_records["counts"] == {
        "active": 0,
        "recent": 2,
        "total": 2,
    }
    records = {record["request_id"]: record for record in terminal_records["recent"]}
    assert set(records) == {"active", "waiting-success"}
    assert records["waiting-success"]["query"] == (
        "the query held until an active activity slot is free"
    )
    assert records["waiting-success"]["outcome"] == "success"


def test_search_activity_filters_active_and_recent_records() -> None:
    ledger = SearchActivityLedger(max_active=4, max_recent=4)
    vault_recent = _start(ledger, "vault-recent", search_type="vault", root="Y:/alpha")
    assert ledger.finish(
        vault_recent,
        completion=SearchActivityCompletion(outcome="success", status_code=200),
    )
    code_recent = _start(ledger, "code-recent", search_type="code", root="Y:/beta")
    assert ledger.finish(
        code_recent,
        completion=SearchActivityCompletion(outcome="failed", status_code=500),
    )
    _start(ledger, "document-active", search_type="document", root="Y:/alpha")

    code_only = ledger.snapshot(
        include_query=True,
        filters=SearchActivityFilters(
            state="terminal",
            search_type="code",
            root="Y:/beta",
            limit=1,
        ),
    )
    assert code_only["active"] == []
    assert [record["request_id"] for record in code_only["recent"]] == ["code-recent"]
    assert code_only["filters"] == {
        "state": "terminal",
        "type": "code",
        "root": "Y:/beta",
        "request_id": None,
        "since": None,
        "limit": 1,
    }

    active = ledger.snapshot(
        include_query=True,
        filters=SearchActivityFilters(
            state="active",
            request_id="document-active",
            since=time.time() - 1.0,
        ),
    )
    assert [record["request_id"] for record in active["active"]] == ["document-active"]
    assert active["recent"] == []


def test_search_activity_retains_every_terminal_failure_outcome() -> None:
    ledger = SearchActivityLedger(max_active=6, max_recent=6)
    expected = {
        "validation": ("validation_rejected", 400, "bad_request"),
        "unavailable": ("unavailable", 503, "index_unavailable"),
        "combined": ("combined_failed", 503, "combined_search_failed"),
        "failure": ("failed", 500, "RuntimeError"),
    }
    for request_id, (outcome, status_code, error_code) in expected.items():
        ticket = _start(ledger, request_id)
        assert ledger.finish(
            ticket,
            completion=SearchActivityCompletion(
                outcome=outcome,
                status_code=status_code,
                error_code=error_code,
                availability_cause="collection_missing"
                if outcome == "unavailable"
                else None,
            ),
        )

    records = {
        record["request_id"]: record
        for record in ledger.snapshot(include_query=True)["recent"]
    }
    for request_id, (outcome, status_code, error_code) in expected.items():
        record = records[request_id]
        assert record["outcome"] == outcome
        assert record["status_code"] == status_code
        assert record["error_code"] == error_code
    assert records["unavailable"]["availability_cause"] == "collection_missing"


def test_search_activity_retention_evicts_the_oldest_query_text() -> None:
    """Terminal retention is finite, and eviction takes the query text with it.

    Proven able to fail: dropping the ``popleft`` eviction from the ledger's
    recent ring keeps every terminal record, and this test then fails on the
    retained-identity assertion below because the two oldest requests are still
    present. Restored, only the newest two survive and the evicted query text is
    unreachable through any serialization.
    """
    ledger = SearchActivityLedger(max_active=4, max_recent=2)
    evicted_query = "the oldest served query must not outlive its retention window"
    for index, query in enumerate(
        (evicted_query, "second query", "third query", "fourth query")
    ):
        ticket = _start(ledger, f"retained-{index}", query=query)
        assert ledger.finish(
            ticket,
            completion=SearchActivityCompletion(outcome="success", status_code=200),
        )

    snapshot = ledger.snapshot(include_query=True)
    assert [record["request_id"] for record in snapshot["recent"]] == [
        "retained-3",
        "retained-2",
    ]
    assert snapshot["counts"] == {"active": 0, "recent": 2, "total": 2}
    assert evicted_query not in str(snapshot)
    assert (
        ledger.snapshot(
            include_query=True,
            filters=SearchActivityFilters(request_id="retained-0"),
        )["recent"]
        == []
    )


def test_search_activity_handles_concurrent_start_and_finish() -> None:
    ledger = SearchActivityLedger(max_active=2, max_recent=24)
    participants = 16
    ready = threading.Barrier(participants)

    def record(index: int) -> None:
        request_id = f"concurrent-{index}"
        ready.wait()
        ticket = _start(ledger, request_id, search_type="combined")
        assert ledger.finish(
            ticket,
            completion=SearchActivityCompletion(
                outcome="partial_success" if index % 2 else "success",
                status_code=200,
                result_count=index,
            ),
        )

    threads = [
        threading.Thread(target=record, args=(index,)) for index in range(participants)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    snapshot = ledger.snapshot(include_query=True)
    assert snapshot["counts"] == {
        "active": 0,
        "recent": participants,
        "total": participants,
    }
    assert {record["request_id"] for record in snapshot["recent"]} == {
        f"concurrent-{index}" for index in range(participants)
    }


@pytest.mark.asyncio
async def test_cancelled_route_admission_cannot_create_a_phantom_activity_slot() -> (
    None
):
    """The route owns cancellation before its synchronous ledger wait starts.

    Proven able to fail: creating the activity ticket only from the result of
    ``run_sync(ledger.start)`` leaves the route with nothing to finish when
    asyncio cancellation lands as the worker gains capacity.  The record then
    stays active forever and the assertion below names that leaked slot.
    Restored, the pre-owned ticket wakes the worker and prevents the late
    admission without starting a service, model, or Qdrant client.
    """
    from ..server._routes_search import _search_route_response
    from ..server._state import search_activity_ledger

    ledger = search_activity_ledger()
    before = ledger.snapshot(include_query=True)
    before_ids = {
        str(record["request_id"])
        for records in (before["active"], before["recent"])
        for record in records
    }
    available_slots = DEFAULT_MAX_ACTIVE_SEARCHES - before["counts"]["active"]
    assert available_slots > 0, "prior activity must not occupy every ledger slot"
    marker = f"cancelled-admission-{time.time_ns()}"
    held = [
        ledger.start(
            SearchActivityStart(
                request_id=f"{marker}-{index}",
                query="held while cancellation reaches the admission worker",
                search_type="unknown",
                root=None,
                top_k=None,
            )
        )
        for index in range(available_slots)
    ]
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/search",
            "raw_path": b"/search",
            "query_string": b"",
            "headers": [(b"host", b"testserver")],
            "server": ("testserver", 80),
            "client": ("testclient", 50_000),
        }
    )
    task = asyncio.create_task(_search_route_response(request))
    try:
        deadline = time.monotonic() + 5.0
        waiters = cast("_ConditionWaiters", ledger._active_slot)
        while not waiters._waiters:
            if time.monotonic() >= deadline:
                raise AssertionError("the real route never reached activity admission")
            await asyncio.sleep(0.001)

        task.cancel()
        assert ledger.finish(
            held.pop(),
            completion=SearchActivityCompletion(outcome="success", status_code=200),
        )
        with pytest.raises(asyncio.CancelledError):
            await task

        for ticket in held:
            assert ledger.finish(
                ticket,
                completion=SearchActivityCompletion(outcome="success", status_code=200),
            )
        held.clear()
        after = ledger.snapshot(include_query=True)
        leaked = [
            record
            for record in after["active"]
            if str(record["request_id"]) not in before_ids
        ]
        assert leaked == [], "a cancelled admission must not occupy an active slot"
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        for ticket in held:
            ledger.finish(
                ticket,
                completion=SearchActivityCompletion(
                    outcome="cancelled", status_code=499
                ),
            )
        for record in ledger.snapshot(include_query=True)["active"]:
            if str(record["request_id"]) not in before_ids:
                ledger.finish(
                    SearchActivityTicket(request_id=str(record["request_id"])),
                    completion=SearchActivityCompletion(
                        outcome="cancelled", status_code=499
                    ),
                )
