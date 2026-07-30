"""Bounded in-memory activity for searches served by this process."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "DEFAULT_MAX_ACTIVE_SEARCHES",
    "DEFAULT_MAX_RECENT_SEARCHES",
    "DEFAULT_SEARCH_ACTIVITY_ROWS",
    "MAX_SEARCH_ACTIVITY_QUERY_CHARS",
    "SearchActivityCompletion",
    "SearchActivityFilters",
    "SearchActivityLedger",
    "SearchActivityStart",
    "SearchActivityTicket",
]

DEFAULT_MAX_ACTIVE_SEARCHES = 256
DEFAULT_MAX_RECENT_SEARCHES = 512
MAX_SEARCH_ACTIVITY_QUERY_CHARS = 10_000

#: Rows an unfiltered activity read returns when the caller names no limit.
#:
#: The retention bounds above are a memory ceiling, not a response size: all
#: 768 records carrying queries of the length allowed above serialize to
#: several megabytes, built in one pass while every other route waits. An
#: operator list is bounded by default and widened on request, so the ceiling
#: is what the caller asked for rather than what the ledger happens to hold.
DEFAULT_SEARCH_ACTIVITY_ROWS = 200

type ActivityState = Literal["active", "terminal"]


class _SearchActivityFilters(TypedDict):
    state: str | None
    type: str | None
    root: str | None
    request_id: str | None
    since: float | None
    limit: int | None


class _SearchActivitySnapshot(TypedDict):
    active: list[dict[str, object]]
    recent: list[dict[str, object]]
    counts: dict[str, int]
    returned: int
    filters: _SearchActivityFilters


@dataclass(frozen=True, slots=True)
class SearchActivityCompletion:
    """One terminal outcome supplied by the search route."""

    outcome: str
    status_code: int
    result_count: int | None = None
    timings: Mapping[str, object] | None = None
    availability_cause: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class SearchActivityFilters:
    """Optional constraints for a bounded activity projection."""

    state: str | None = None
    search_type: str | None = None
    root: str | None = None
    request_id: str | None = None
    since: float | None = None
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class _SearchActivity:
    """One immutable served-search lifecycle record held by the ledger."""

    request_id: str
    query: str
    query_truncated: bool
    source: str
    root: str | None
    top_k: int | None
    started_at: float
    started_monotonic: float
    state: ActivityState = "active"
    finished_at: float | None = None
    total_seconds: float | None = None
    status_code: int | None = None
    outcome: str | None = None
    result_count: int | None = None
    timings: tuple[tuple[str, float], ...] = ()
    availability_cause: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def serialise(self, *, include_query: bool) -> dict[str, object]:
        """Return the route-safe representation with optional query text."""
        result: dict[str, object] = {
            "request_id": self.request_id,
            "state": self.state,
            "source": self.source,
            "type": self.source,
            "root": self.root,
            "top_k": self.top_k,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_seconds": self.total_seconds,
            "status_code": self.status_code,
            "outcome": self.outcome,
            "result_count": self.result_count,
            "timings": dict(self.timings),
            "availability_cause": self.availability_cause,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "query_truncated": self.query_truncated,
        }
        if include_query:
            result["query"] = self.query
        else:
            result["query_redacted"] = True
        return result


@dataclass(slots=True)
class SearchActivityTicket:
    """One route-owned claim on a future terminal activity record.

    The route creates this before its bounded admission wait so cancellation
    keeps ownership even if the worker has not returned. It deliberately
    carries only a request id; full query text lives in the ledger's bounded
    active and recent projections, never in a waiting request coroutine.
    """

    request_id: str
    terminal: bool = False


@dataclass(frozen=True, slots=True)
class SearchActivityStart:
    """The complete metadata and owned claim for one activity admission."""

    request_id: str
    query: str
    search_type: str
    root: str | None
    top_k: int | None
    ticket: SearchActivityTicket | None = None


class SearchActivityLedger:
    """Own active and recently terminal search activity with finite retention.

    Query text remains only in these process-local records. Callers choose whether
    serialization may include it, so the token-gated route is the only production
    surface that exposes the text.
    """

    def __init__(
        self,
        *,
        max_active: int = DEFAULT_MAX_ACTIVE_SEARCHES,
        max_recent: int = DEFAULT_MAX_RECENT_SEARCHES,
    ) -> None:
        if isinstance(max_active, bool) or max_active < 1:
            raise ValueError("max_active must be at least 1")
        if isinstance(max_recent, bool) or max_recent < 1:
            raise ValueError("max_recent must be at least 1")
        self._max_active = max_active
        self._max_recent = max_recent
        self._lock = threading.RLock()
        self._active: dict[str, _SearchActivity] = {}
        self._recent: deque[_SearchActivity] = deque()
        self._active_slot = threading.Condition(self._lock)

    def start(self, admission: SearchActivityStart) -> SearchActivityTicket:
        """Start one served search and return its terminal-record ticket.

        Activity capacity is backpressure, not a rejected request.  A caller
        waits until a detailed active record can be admitted, so a route never
        retains query text outside the finite ledger while it waits. Route
        owners may create their ticket before dispatching this synchronous
        wait: that lets a cancelled coroutine terminalize or abandon its
        claim even if the worker gains a slot after the coroutine has gone.
        """
        activity_ticket = admission.ticket or SearchActivityTicket(
            request_id=admission.request_id
        )
        if activity_ticket.request_id != admission.request_id:
            raise ValueError(
                "activity ticket request_id must match admission request_id"
            )
        with self._active_slot:
            while (
                len(self._active) >= self._max_active and not activity_ticket.terminal
            ):
                self._active_slot.wait()
            if activity_ticket.terminal:
                return activity_ticket
            if admission.request_id in self._active or self._contains_recent_locked(
                admission.request_id
            ):
                raise ValueError(
                    f"request_id {admission.request_id!r} is already recorded"
                )
            moment = time.time()
            monotonic = time.perf_counter()
            truncated_query = admission.query[:MAX_SEARCH_ACTIVITY_QUERY_CHARS]
            self._active[admission.request_id] = _SearchActivity(
                request_id=admission.request_id,
                query=truncated_query,
                query_truncated=len(admission.query) > len(truncated_query),
                source=admission.search_type,
                root=admission.root,
                top_k=admission.top_k,
                started_at=moment,
                started_monotonic=monotonic,
            )
            return activity_ticket

    def finish(
        self,
        ticket: SearchActivityTicket,
        *,
        completion: SearchActivityCompletion,
    ) -> bool:
        """Write one terminal record; the first terminal outcome wins.

        ``ticket`` is route-owned rather than reconstructed from a request id.
        It can only refer to a record that was admitted to the finite active
        ledger, so the terminal ring has the same complete review data.
        """
        moment = time.time()
        monotonic = time.perf_counter()
        with self._active_slot:
            if ticket.terminal:
                return False
            ticket.terminal = True
            active = self._active.pop(ticket.request_id, None)
            if active is None:
                # A cancellation can terminalize the route's owned ticket
                # while its synchronous admission worker is still waiting.
                # Wake that worker so it observes ``terminal`` and cannot
                # create a record after the route has already left.
                self._active_slot.notify_all()
                return False
            terminal = replace(
                active,
                state="terminal",
                finished_at=moment,
                total_seconds=max(0.0, monotonic - active.started_monotonic),
                status_code=completion.status_code,
                outcome=completion.outcome,
                result_count=completion.result_count,
                timings=_normalise_timings(completion.timings),
                availability_cause=completion.availability_cause,
                error_code=completion.error_code,
                error_message=_bounded_text(completion.error_message),
            )
            self._append_recent_locked(terminal)
            self._active_slot.notify()
            return True

    def update_request(
        self,
        ticket: SearchActivityTicket,
        *,
        query: str,
        search_type: str,
        root: str | None,
        top_k: int | None,
    ) -> bool:
        """Replace provisional request metadata once route validation settles it."""
        truncated_query = query[:MAX_SEARCH_ACTIVITY_QUERY_CHARS]
        with self._lock:
            if ticket.terminal:
                return False
            active = self._active.get(ticket.request_id)
            if active is None:
                return False
            self._active[ticket.request_id] = replace(
                active,
                query=truncated_query,
                query_truncated=len(query) > len(truncated_query),
                source=search_type,
                root=root,
                top_k=top_k,
            )
            return True

    def snapshot(
        self,
        *,
        include_query: bool,
        filters: SearchActivityFilters | None = None,
    ) -> _SearchActivitySnapshot:
        """Serialize a bounded, newest-first projection of live activity."""
        selected_filters = _normalise_filters(filters or SearchActivityFilters())
        with self._lock:
            active = sorted(
                self._active.values(),
                key=lambda record: (record.started_at, record.request_id),
                reverse=True,
            )
            recent = list(reversed(self._recent))
            counts = {
                "active": len(active),
                "recent": len(recent),
                "total": len(active) + len(recent),
            }
        active_matches = _filter_records(
            active,
            selected_filters,
        )
        recent_matches = _filter_records(
            recent,
            selected_filters,
        )
        if selected_filters.limit is not None:
            active_matches = active_matches[: selected_filters.limit]
            remaining = max(0, selected_filters.limit - len(active_matches))
            recent_matches = recent_matches[:remaining]
        return {
            "active": [
                record.serialise(include_query=include_query)
                for record in active_matches
            ],
            "recent": [
                record.serialise(include_query=include_query)
                for record in recent_matches
            ],
            "counts": counts,
            "returned": len(active_matches) + len(recent_matches),
            "filters": {
                "state": selected_filters.state,
                "type": selected_filters.search_type,
                "root": selected_filters.root,
                "request_id": selected_filters.request_id,
                "since": selected_filters.since,
                "limit": selected_filters.limit,
            },
        }

    def _contains_recent_locked(self, request_id: str) -> bool:
        return any(record.request_id == request_id for record in self._recent)

    def _append_recent_locked(self, record: _SearchActivity) -> None:
        self._recent.append(record)
        while len(self._recent) > self._max_recent:
            self._recent.popleft()


def _bounded_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:MAX_SEARCH_ACTIVITY_QUERY_CHARS]


def _normalise_timings(
    timings: Mapping[str, object] | None,
) -> tuple[tuple[str, float], ...]:
    if timings is None:
        return ()
    cleaned: list[tuple[str, float]] = []
    for key, value in timings.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        numeric = float(value)
        if math.isfinite(numeric) and numeric >= 0.0:
            cleaned.append((str(key), numeric))
    return tuple(sorted(cleaned))


def _normalise_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalised = value.strip()
    return normalised or None


def _normalise_state(value: str | None) -> str | None:
    normalised = _normalise_filter(value)
    if normalised in {"active", "terminal"}:
        return normalised
    return None


def _normalise_since(value: object | None) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) and numeric >= 0.0 else None


def _normalise_limit(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(0, value)


def _normalise_filters(filters: SearchActivityFilters) -> SearchActivityFilters:
    """Normalize one route-provided filter object before taking the lock."""
    return SearchActivityFilters(
        state=_normalise_state(filters.state),
        search_type=_normalise_filter(filters.search_type),
        root=_normalise_filter(filters.root),
        request_id=_normalise_filter(filters.request_id),
        since=_normalise_since(filters.since),
        limit=_normalise_limit(filters.limit),
    )


def _filter_records(
    records: list[_SearchActivity],
    filters: SearchActivityFilters,
) -> list[_SearchActivity]:
    return [
        record
        for record in records
        if (filters.state is None or record.state == filters.state)
        and (filters.search_type is None or record.source == filters.search_type)
        and (filters.root is None or record.root == filters.root)
        and (filters.request_id is None or record.request_id == filters.request_id)
        and (filters.since is None or record.started_at >= filters.since)
    ]
