"""Bounded in-memory activity for searches served by this process."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, TypedDict

from .._search_state import SearchWaitCause, WaitObservation

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "DEFAULT_MAX_ACTIVE_SEARCHES",
    "DEFAULT_MAX_QUEUED_SEARCHES",
    "DEFAULT_MAX_RECENT_SEARCHES",
    "DEFAULT_SEARCH_ACTIVITY_ADMISSION_WAIT_SECONDS",
    "DEFAULT_SEARCH_ACTIVITY_ROWS",
    "MAX_SEARCH_ACTIVITY_QUERY_CHARS",
    "SearchActivityAdmissionError",
    "SearchActivityCompletion",
    "SearchActivityFilters",
    "SearchActivityLedger",
    "SearchActivityStart",
    "SearchActivityTicket",
]

DEFAULT_MAX_ACTIVE_SEARCHES = 256
DEFAULT_MAX_QUEUED_SEARCHES = 512
DEFAULT_MAX_RECENT_SEARCHES = 512
DEFAULT_SEARCH_ACTIVITY_ADMISSION_WAIT_SECONDS = 30.0
MAX_SEARCH_ACTIVITY_QUERY_CHARS = 10_000

#: Rows an unfiltered activity read returns when the caller names no limit.
#:
#: The retention bounds above are a memory ceiling, not a response size: all
#: 1280 records carrying queries of the length allowed above serialize to
#: several megabytes, built in one pass while every other route waits. An
#: operator list is bounded by default and widened on request, so the ceiling
#: is what the caller asked for rather than what the ledger happens to hold.
DEFAULT_SEARCH_ACTIVITY_ROWS = 200

type ActivityState = Literal["queued", "active", "terminal"]


class _SearchActivityFilters(TypedDict):
    state: str | None
    type: str | None
    root: str | None
    request_id: str | None
    since: float | None
    limit: int | None


class _SearchActivitySnapshot(TypedDict):
    queued: list[dict[str, object]]
    queued_count: int
    active: list[dict[str, object]]
    recent: list[dict[str, object]]
    counts: dict[str, int]
    all_counts: dict[str, int]
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


class SearchActivityAdmissionError(TimeoutError):
    """A bounded activity-ledger admission refusal with canonical evidence."""

    def __init__(
        self,
        *,
        request_id: str,
        reason: Literal["queue_full", "deadline_exceeded"],
        wait: WaitObservation,
        deadline: float | None,
    ) -> None:
        super().__init__(f"search activity admission refused: {reason}")
        self.request_id = request_id
        self.reason = reason
        self.wait = wait
        self.deadline = deadline


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
    admission_wait_bound_seconds: float
    admission_deadline: float | None
    state: ActivityState = "active"
    finished_at: float | None = None
    total_seconds: float | None = None
    status_code: int | None = None
    outcome: str | None = None
    result_count: int | None = None
    timings: tuple[tuple[str, float], ...] = ()
    waits: tuple[WaitObservation, ...] = ()
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
            "admission_deadline": self.admission_deadline,
            "finished_at": self.finished_at,
            "total_seconds": self.total_seconds,
            "status_code": self.status_code,
            "outcome": self.outcome,
            "result_count": self.result_count,
            "timings": dict(self.timings),
            "waits": [wait.as_dict() for wait in self.waits],
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
    admission_waits: tuple[WaitObservation, ...] = ()
    admission_deadline: float | None = None
    admission_refusal: Literal["queue_full", "deadline_exceeded"] | None = None


@dataclass(frozen=True, slots=True)
class SearchActivityStart:
    """The complete metadata and owned claim for one activity admission."""

    request_id: str
    query: str
    search_type: str
    root: str | None
    top_k: int | None
    ticket: SearchActivityTicket | None = None
    admission_wait_seconds: float = DEFAULT_SEARCH_ACTIVITY_ADMISSION_WAIT_SECONDS


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
        max_queued: int = DEFAULT_MAX_QUEUED_SEARCHES,
        max_recent: int = DEFAULT_MAX_RECENT_SEARCHES,
    ) -> None:
        if isinstance(max_active, bool) or max_active < 1:
            raise ValueError("max_active must be at least 1")
        if isinstance(max_recent, bool) or max_recent < 1:
            raise ValueError("max_recent must be at least 1")
        if isinstance(max_queued, bool) or max_queued < 1:
            raise ValueError("max_queued must be at least 1")
        self._max_active = max_active
        self._max_queued = max_queued
        self._max_recent = max_recent
        self._lock = threading.RLock()
        self._active: dict[str, _SearchActivity] = {}
        self._queued: dict[str, _SearchActivity] = {}
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
        wait_bound = _normalise_wait_bound(admission.admission_wait_seconds)
        admitted_at = time.time()
        admitted_monotonic = time.perf_counter()
        deadline = admitted_monotonic + wait_bound
        deadline_wall = admitted_at + wait_bound
        truncated_query = admission.query[:MAX_SEARCH_ACTIVITY_QUERY_CHARS]
        queued = _SearchActivity(
            request_id=admission.request_id,
            query=truncated_query,
            query_truncated=len(admission.query) > len(truncated_query),
            source=admission.search_type,
            root=admission.root,
            top_k=admission.top_k,
            started_at=admitted_at,
            started_monotonic=admitted_monotonic,
            admission_wait_bound_seconds=wait_bound,
            admission_deadline=deadline_wall,
            state="queued",
        )
        with self._active_slot:
            if (
                admission.request_id in self._active
                or self._contains_recent_locked(admission.request_id)
                or admission.request_id in self._queued
            ):
                raise ValueError(
                    f"request_id {admission.request_id!r} is already recorded"
                )
            if len(self._queued) >= self._max_queued:
                wait = _admission_wait(wait_bound=0.0, waited=0.0)
                activity_ticket.admission_waits = (wait,)
                activity_ticket.admission_refusal = "queue_full"
                self._record_refusal_locked(
                    queued,
                    ticket=activity_ticket,
                    reason="queue_full",
                    wait=wait,
                    deadline=None,
                )
                raise SearchActivityAdmissionError(
                    request_id=admission.request_id,
                    reason="queue_full",
                    wait=wait,
                    deadline=None,
                )
            activity_ticket.admission_deadline = deadline_wall
            self._queued[admission.request_id] = queued
            try:
                while (
                    len(self._active) >= self._max_active
                    and not activity_ticket.terminal
                ):
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0.0:
                        wait = _admission_wait(
                            wait_bound=wait_bound,
                            waited=wait_bound,
                        )
                        activity_ticket.admission_waits = (wait,)
                        activity_ticket.admission_refusal = "deadline_exceeded"
                        self._record_refusal_locked(
                            queued,
                            ticket=activity_ticket,
                            reason="deadline_exceeded",
                            wait=wait,
                            deadline=deadline_wall,
                        )
                        raise SearchActivityAdmissionError(
                            request_id=admission.request_id,
                            reason="deadline_exceeded",
                            wait=wait,
                            deadline=deadline_wall,
                        )
                    self._active_slot.wait(timeout=remaining)
                if activity_ticket.terminal:
                    return activity_ticket
                finished_monotonic = time.perf_counter()
                waited = min(
                    wait_bound,
                    max(0.0, finished_monotonic - admitted_monotonic),
                )
                activity_ticket.admission_waits = (
                    _admission_wait(wait_bound=wait_bound, waited=waited),
                )
                self._active[admission.request_id] = replace(
                    queued,
                    state="active",
                    waits=activity_ticket.admission_waits,
                )
                return activity_ticket
            finally:
                self._queued.pop(admission.request_id, None)

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
            queued = sorted(
                self._queued.values(),
                key=lambda record: (record.started_at, record.request_id),
                reverse=True,
            )
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
            all_counts = {
                "queued": len(queued),
                **counts,
                "total": len(queued) + counts["total"],
            }
        active_matches = _filter_records(
            active,
            selected_filters,
        )
        queued_matches = _filter_records(
            queued,
            selected_filters,
        )
        recent_matches = _filter_records(
            recent,
            selected_filters,
        )
        if selected_filters.limit is not None:
            queued_matches = queued_matches[: selected_filters.limit]
            remaining = max(0, selected_filters.limit - len(queued_matches))
            active_matches = active_matches[:remaining]
            remaining = max(0, remaining - len(active_matches))
            recent_matches = recent_matches[:remaining]
        return {
            "queued": [
                _serialise_queued(
                    record,
                    now=time.perf_counter(),
                    include_query=include_query,
                )
                for record in queued_matches
            ],
            "queued_count": len(queued),
            "active": [
                record.serialise(include_query=include_query)
                for record in active_matches
            ],
            "recent": [
                record.serialise(include_query=include_query)
                for record in recent_matches
            ],
            "counts": counts,
            "all_counts": all_counts,
            "returned": len(queued_matches) + len(active_matches) + len(recent_matches),
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

    def _record_refusal_locked(
        self,
        queued: _SearchActivity,
        *,
        ticket: SearchActivityTicket,
        reason: Literal["queue_full", "deadline_exceeded"],
        wait: WaitObservation,
        deadline: float | None,
    ) -> None:
        """Retain one refusal exactly once while the admission lock is held."""
        moment = time.time()
        monotonic = time.perf_counter()
        ticket.terminal = True
        ticket.admission_deadline = deadline
        self._append_recent_locked(
            replace(
                queued,
                state="terminal",
                admission_deadline=deadline,
                finished_at=moment,
                total_seconds=max(0.0, monotonic - queued.started_monotonic),
                outcome="capacity_limited",
                waits=(wait,),
                error_code=f"search_admission_{reason}",
            )
        )

    def _append_recent_locked(self, record: _SearchActivity) -> None:
        self._recent.append(record)
        while len(self._recent) > self._max_recent:
            self._recent.popleft()


def _bounded_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:MAX_SEARCH_ACTIVITY_QUERY_CHARS]


def _normalise_wait_bound(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("admission_wait_seconds must be a finite positive number")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0.0:
        raise ValueError("admission_wait_seconds must be a finite positive number")
    return numeric


def _serialise_queued(
    record: _SearchActivity,
    *,
    now: float,
    include_query: bool,
) -> dict[str, object]:
    waited = min(
        record.admission_wait_bound_seconds,
        max(0.0, now - record.started_monotonic),
    )
    wait = _admission_wait(
        wait_bound=record.admission_wait_bound_seconds,
        waited=waited,
    )
    return {**record.serialise(include_query=include_query), "waits": [wait.as_dict()]}


def _admission_wait(*, wait_bound: float, waited: float) -> WaitObservation:
    return WaitObservation(
        cause=SearchWaitCause.SEARCH_ADMISSION,
        waited_seconds=waited,
        configured_bound_seconds=wait_bound,
        remaining_bound_seconds=max(0.0, wait_bound - waited),
    )


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
    if normalised in {"queued", "active", "terminal"}:
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
