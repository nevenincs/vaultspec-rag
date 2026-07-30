"""Service-status header for the interactive jobs interface.

The jobs view answers "what is the service doing"; this answers "what is the
service". Four operator questions sit above the job list - how much room the
index is taking, who is connected, how many of the service's seats are
occupied, and whether the service is well - and each is answered from a field
the service already publishes. Nothing here computes a metric: health, storage
footprint, slot accounting and watcher state are service-domain facts, and this
module is the adapter that reads and renders them.

Where each answer comes from:

* Space occupied - ``GET /storage/survey`` ``totals.total_bytes``, the whole
  backend footprint across every namespace, not just this project's.
* Seats consumed - ``GET /metrics`` ``vaultspec_rag_encode_pool_*``, the
  machine-wide single-slot admission gate for encode-bearing index jobs, plus
  the index-dispatch pool beside it; and ``GET /projects``, whose loaded
  count against ``max_projects`` is the project-slot seat.
* Service status - ``GET /health`` ``status``, ``degraded_reasons``,
  ``qdrant.alive`` and ``uptime_s``, plus ``GET /watcher`` for what is being
  watched.
* Clients connected - **the service publishes no connection or client
  accounting.** There is no per-connection counter anywhere in the service
  domain; the registry counts leases (concurrent in-flight requests holding a
  project slot), which is a different fact and is reported under its own name.
  The ``clients`` field reads the ``clients_connected`` key a future health
  payload would carry, so it renders as absent today and lights up with no
  change here once the service grows one. Do not derive it client-side.

Two of these surfaces degrade by construction, and both must read as absent
rather than as zero: a pool gauge is omitted from ``/metrics`` entirely until
its limiter has been built (an idle service has never constructed the encode
limiter), and a service older than a field simply does not send it.

Integration contract
--------------------

``fetch_service_status(port)`` performs blocking HTTP and must be called from a
worker thread, never from the event loop. It never raises: an unreachable,
sick, or older service comes back as a :class:`ServiceStatusHeader` with the
fields it could not learn left ``None``.

``ServiceStatusBar`` is a ``Static`` that renders one such result. Mount it in
``compose`` above the job table, hand it results with :meth:`show`, and it
repaints itself on every resize:

.. code-block:: python

    def compose(self) -> ComposeResult:
        yield ServiceStatusBar(id="servicestatus")
        yield Static(id="summary")
        ...

    @work(thread=True, exclusive=True, group=_STATUS_GROUP)
    def refresh_service_status(self) -> None:
        result = fetch_service_status(self._port)
        self.call_from_thread(
            self.query_one("#servicestatus", ServiceStatusBar).show, result
        )

The status surface changes far more slowly than the job list, so it wants a
poll interval of its own rather than a ride on the jobs tick - and it wants a
worker group of its own, because an exclusive worker cancels every worker
sharing its group and the jobs poll would otherwise discard its answer.
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from rich.cells import cell_len
from rich.text import Text
from textual.widgets import Static

from .._loopback_http import LOOPBACK_OPENER
from .._units import human_bytes
from ..concurrency import LIMITER_STAT_FIELDS
from ..jobs import count, flag, mapping, measurement
from ..serviceclient._compat import classify_service_version
from ..serviceclient._transport import (
    DEFAULT_ADMIN_TIMEOUT_SECONDS,
    _try_http_admin,
    _try_http_health,
    read_service_response,
)
from ._cli_format import compact_duration
from ._jobs_tui_palette import semantic_tones, tone_style

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from textual.app import App

__all__ = [
    "SeatPool",
    "ServiceStatusBar",
    "ServiceStatusHeader",
    "fetch_service_status",
    "render_status_header",
]

#: What a field the service did not report renders as. An absent measurement
#: and a measurement of zero are different facts, and the header is read at a
#: glance: "seats 0/1" says the gate is free, "seats —" says nobody asked.
_ABSENT = "—"

#: Segment divider. The only literal width in the layout, and it is content
#: rather than a column: every segment is measured, none is padded to a size.
_SEPARATOR = "  ·  "

_METRIC_PREFIX = "vaultspec_rag_"
_POOL_INFIX = "_pool_"
#: Pool order as an operator reads it: the scarce machine-wide encode gate
#: first, then the dispatch pools behind it.
_POOL_ORDER = ("encode", "index", "search")

# Verdict -> (semantic tone, bold), resolved through the palette so this
# bar and the jobs header can never disagree about what a colour means.
_STATUS_TONES: dict[str, tuple[str, bool]] = {
    "ready": ("good", True),
    "degraded": ("attention", True),
    "error": ("bad", True),
}


@dataclass(frozen=True, slots=True)
class SeatPool:
    """One capacity limiter's occupancy, as ``/metrics`` reports it.

    Attributes:
        name: The limiter's name (``encode``, ``index``, ``search``).
        used: Tokens currently borrowed, or ``None`` when not reported.
        total: The limiter's capacity, or ``None`` when not reported.
        waiting: Callers queued behind a full limiter, or ``None``.
    """

    name: str
    used: int | None = None
    total: int | None = None
    waiting: int | None = None


@dataclass(frozen=True, slots=True)
class ServiceStatusHeader:
    """Everything the header can say, with every field optional.

    A field is ``None`` when the service did not report it - because it is
    older, because it is degraded, or because it could not be reached at all.
    No field is ever defaulted to zero.

    Attributes:
        reachable: Whether anything answered on the port.
        version: The release the running daemon reports for compatibility
            checking, or ``None`` when it predates version reporting. Never
            filled from the local package: the two differ exactly when the
            difference matters.
        status: The health verdict (``ready``, ``degraded``, ``error``).
        degraded_reasons: The structured reasons behind a degraded verdict.
        qdrant_alive: Whether the vector backend is live.
        uptime_seconds: Service uptime.
        store_bytes: Whole-backend storage footprint across all namespaces.
        namespaces: How many namespaces that footprint spans.
        projects_loaded: Project slots currently resident.
        projects_cap: The registry's configured slot cap.
        leases_held: Concurrent in-flight requests holding a project lease.
        clients: Connected clients. Never populated - see the module
            docstring; the service publishes no connection accounting.
        watching: How many roots the file watcher is following.
        seats: Per-limiter occupancy, in operator-facing order.
        error: A transport-level message when one is worth showing.
    """

    reachable: bool = False
    version: str | None = None
    status: str | None = None
    degraded_reasons: tuple[str, ...] = ()
    qdrant_alive: bool | None = None
    uptime_seconds: float | None = None
    store_bytes: int | None = None
    namespaces: int | None = None
    projects_loaded: int | None = None
    projects_cap: int | None = None
    leases_held: int | None = None
    clients: int | None = None
    watching: int | None = None
    seats: tuple[SeatPool, ...] = ()
    error: str | None = None

    def seat_pool(self, name: str) -> SeatPool | None:
        """Return the named limiter's occupancy, or ``None`` if unreported."""
        for pool in self.seats:
            if pool.name == name:
                return pool
        return None


def _ok_payload(raw: object) -> dict[str, object]:
    """Narrow an admin result, discarding a structured failure envelope.

    ``_try_http_admin`` reports a refusal or a timeout as a mapping carrying
    ``ok: False``. Reading fields off that would report every absent value
    twice over; an errored call reports nothing instead.
    """
    payload = mapping(raw)
    if payload.get("ok") is False:
        return {}
    return payload


def _parse_seat_pools(text: str) -> tuple[SeatPool, ...]:
    """Read the limiter gauges out of the Prometheus exposition text.

    A limiter that has never been built publishes no lines at all, so an idle
    service reports fewer pools than a busy one. Pools appear here only when
    the service named them.
    """
    collected: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        metric, _, value = stripped.partition(" ")
        if not metric.startswith(_METRIC_PREFIX):
            continue
        pool, infix, stat = metric[len(_METRIC_PREFIX) :].partition(_POOL_INFIX)
        if not infix or stat not in LIMITER_STAT_FIELDS or not pool:
            continue
        try:
            parsed = int(float(value))
        except ValueError:
            continue
        collected.setdefault(pool, {})[stat] = parsed
    ordered = [name for name in _POOL_ORDER if name in collected]
    ordered.extend(sorted(name for name in collected if name not in _POOL_ORDER))
    return tuple(
        SeatPool(
            name=name,
            used=collected[name].get("borrowed_tokens"),
            total=collected[name].get("total_tokens"),
            waiting=collected[name].get("waiting"),
        )
        for name in ordered
    )


def _fetch_metrics_text(port: int, token: str, timeout: float | None) -> str:
    """Read ``GET /metrics`` as text, or return an empty body on any failure.

    ``/metrics`` is the only publisher of the seat gauges and it answers in
    Prometheus text, so it has no entry in the transport's admin routing table
    and no JSON parse behind it. The seam for folding it in is
    ``serviceclient._transport._GET_ROOT_ROUTES``; until a mapping exists
    there, this is the one place that speaks to the route.
    """
    request = urllib.request.Request(f"http://127.0.0.1:{port}/metrics", method="GET")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with LOOPBACK_OPENER.open(
            request, timeout=timeout or DEFAULT_ADMIN_TIMEOUT_SECONDS
        ) as response:
            return read_service_response(response).decode("utf-8", "replace")
    except Exception:
        # Every failure here - refused, gated, timed out, truncated - means
        # the same thing to the header: the seat gauges are unreported. The
        # breadth is deliberate; a status header must never take the screen
        # down with it.
        return ""


def _survey_totals(port: int, timeout: float | None) -> dict[str, Any]:
    """Read the whole-backend storage totals off the survey route.

    ``limit=1`` bounds the namespace list the route ships back; ``totals`` is
    computed over the whole survey regardless, so the footprint is the
    backend's rather than the first namespace's.
    """
    survey = _ok_payload(
        _try_http_admin("get_storage_survey", {"limit": 1}, port, timeout=timeout)
    )
    return mapping(survey.get("totals"))


def _project_slots(
    port: int, timeout: float | None
) -> tuple[int | None, int | None, int | None]:
    """Read resident project slots, the slot cap, and held leases."""
    payload = _ok_payload(_try_http_admin("list_projects", {}, port, timeout=timeout))
    raw_projects = payload.get("projects")
    if not isinstance(raw_projects, list):
        return None, count(payload.get("max_projects")), None
    raw_entries = cast("list[object]", raw_projects)
    entries = [mapping(entry) for entry in raw_entries]
    leases = [count(entry.get("ref_count")) for entry in entries]
    held = sum(lease for lease in leases if lease is not None) if leases else 0
    return len(entries), count(payload.get("max_projects")), held


def _watching_count(port: int, timeout: float | None) -> int | None:
    """Read how many roots the watcher is following."""
    payload = _ok_payload(
        _try_http_admin("get_watcher_state", {}, port, timeout=timeout)
    )
    watching = payload.get("watching")
    if not isinstance(watching, list):
        return None
    roots = cast("list[object]", watching)
    return len(roots)


def fetch_service_status(
    port: int | None, *, timeout: float | None = None
) -> ServiceStatusHeader:
    """Gather the header's facts from the service on *port*.

    Blocking HTTP throughout - call it from a worker thread. Never raises:
    an unreachable service, a sick one, and one older than a field all come
    back as a result whose unlearnable fields are ``None``.

    Args:
        port: The service port, or ``None`` when none is resolved.
        timeout: Per-call bound for the gated routes. The health probe keeps
            its own tighter bound so an absent service is reported fast.

    Returns:
        The gathered facts. ``reachable`` is ``False`` when nothing answered.
    """
    if port is None:
        return ServiceStatusHeader(error="no service port")
    health = _try_http_health(port)
    if health is None:
        return ServiceStatusHeader(error="service not reachable")
    http_code = count(health.get("http_code"))
    if http_code is not None:
        # The service answered, badly. That is not the same as absent, and an
        # operator has to be able to tell them apart.
        return ServiceStatusHeader(
            reachable=True,
            status="error",
            error=f"service answered HTTP {http_code}",
        )

    token = health.get("service_token")
    qdrant = mapping(health.get("qdrant"))
    raw_reasons = health.get("degraded_reasons")
    listed_reasons = (
        cast("list[object]", raw_reasons) if isinstance(raw_reasons, list) else []
    )
    reasons = tuple(str(reason) for reason in listed_reasons) if listed_reasons else ()
    totals = _survey_totals(port, timeout)
    loaded, cap, leases = _project_slots(port, timeout)
    seats = _parse_seat_pools(
        _fetch_metrics_text(port, token if isinstance(token, str) else "", timeout)
    )
    status = health.get("status")
    return ServiceStatusHeader(
        reachable=True,
        # Read through the same classifier the compatibility check uses, so
        # the header and the version gate can never disagree about what the
        # daemon reported. ``None`` is a daemon that predates the field.
        version=classify_service_version(health).service_version,
        status=str(status) if isinstance(status, str) else None,
        degraded_reasons=reasons,
        qdrant_alive=flag(qdrant.get("alive")),
        uptime_seconds=measurement(health.get("uptime_s")),
        store_bytes=count(totals.get("total_bytes")),
        namespaces=count(totals.get("namespaces")),
        projects_loaded=loaded,
        projects_cap=cap,
        leases_held=leases,
        clients=count(health.get("clients_connected")),
        watching=_watching_count(port, timeout),
        seats=seats,
        error=None,
    )


def _pair(used: int | None, total: int | None) -> str:
    """Render an occupancy as ``used/total``, degrading part by part."""
    if used is None and total is None:
        return _ABSENT
    left = _ABSENT if used is None else str(used)
    right = _ABSENT if total is None else str(total)
    return f"{left}/{right}"


def _count(value: int | None) -> str:
    """Render a bare count, or the absence marker."""
    return _ABSENT if value is None else str(value)


def _status_segment(
    status: ServiceStatusHeader, tones: Mapping[str, str]
) -> tuple[str, str, str]:
    """Render the health verdict, carrying the degraded-reason count."""
    if not status.reachable:
        return "service", "unreachable", tone_style(tones, "bad", bold=True)
    verdict = status.status or _ABSENT
    tone, bold = _STATUS_TONES.get(verdict, ("", True))
    if status.degraded_reasons:
        verdict = f"{verdict} ({len(status.degraded_reasons)})"
    return "service", verdict, tone_style(tones, tone, bold=bold)


def _seat_segment(
    status: ServiceStatusHeader, tones: Mapping[str, str]
) -> tuple[str, str, str]:
    """Render the machine-wide encode admission gate as the seat count."""
    pool = status.seat_pool("encode")
    if pool is None:
        return "seats", _ABSENT, "dim"
    value = _pair(pool.used, pool.total)
    if pool.waiting:
        value = f"{value} +{pool.waiting} waiting"
    saturated = (
        pool.used is not None and pool.total is not None and pool.used >= pool.total
    )
    return (
        "seats",
        value,
        tone_style(tones, "attention", bold=True) if saturated or pool.waiting else "",
    )


def _pool_segment(pool: SeatPool, tones: Mapping[str, str]) -> tuple[str, str, str]:
    """Render one named dispatch pool, including callers waiting at its gate."""
    value = _pair(pool.used, pool.total)
    if pool.waiting:
        value = f"{value} +{pool.waiting} waiting"
    saturated = (
        pool.used is not None and pool.total is not None and pool.used >= pool.total
    )
    return (
        pool.name,
        value,
        tone_style(tones, "attention", bold=True) if saturated or pool.waiting else "",
    )


def _segments(
    status: ServiceStatusHeader, tones: Mapping[str, str]
) -> Iterator[tuple[str, str, str]]:
    """Yield the header's segments in the order they are shed under pressure.

    Least droppable first: an operator who has room for one thing wants the
    verdict, and one who has room for two wants the footprint beside it.
    """
    yield _status_segment(status, tones)
    if not status.reachable:
        if status.error:
            yield "", status.error, tone_style(tones, "bad")
        return
    yield (
        "store",
        (_ABSENT if status.store_bytes is None else human_bytes(status.store_bytes)),
        "",
    )
    yield _seat_segment(status, tones)
    yield "clients", _count(status.clients), "dim" if status.clients is None else ""
    yield "in flight", _count(status.leases_held), ""
    yield "projects", _pair(status.projects_loaded, status.projects_cap), ""
    if status.qdrant_alive is None:
        yield "qdrant", _ABSENT, "dim"
    else:
        yield (
            "qdrant",
            ("live" if status.qdrant_alive else "down"),
            "" if status.qdrant_alive else tone_style(tones, "bad", bold=True),
        )
    index_pool = status.seat_pool("index")
    if index_pool is not None:
        yield _pool_segment(index_pool, tones)
    search_pool = status.seat_pool("search")
    if search_pool is not None:
        yield _pool_segment(search_pool, tones)
    yield "watching", _count(status.watching), ""
    yield "up", compact_duration(status.uptime_seconds), "dim"


def render_status_header(
    status: ServiceStatusHeader | None,
    width: int,
    *,
    tones: Mapping[str, str] | None = None,
) -> Text:
    """Render the header to at most *width* cells.

    Segments are measured and admitted while they fit; nothing is padded to a
    size, so the same composition fills an 80-column shell and a 300-column
    one and sheds its rightmost fields as the terminal narrows. A
    non-positive *width* - a widget asked to paint before its first layout
    pass - is read as "unknown" and every segment is admitted.

    Args:
        status: The gathered facts, or ``None`` before the first fetch lands.
        width: Cells available on the line.

    Returns:
        The rendered line. Never empty: the leading segment is admitted
        whether or not it fits, because a header that vanishes under pressure
        reads as a service that stopped answering.
    """
    if status is None:
        return Text("service …", style="dim")
    resolved = tones if tones is not None else semantic_tones("")
    line = Text()
    used = 0
    for label, value, style in _segments(status, resolved):
        piece = f"{label} {value}".strip()
        cost = cell_len(piece) + (cell_len(_SEPARATOR) if line else 0)
        if line and width > 0 and used + cost > width:
            break
        if line:
            line.append(_SEPARATOR, style="dim")
        line.append(piece, style=style)
        used += cost
    return line


class ServiceStatusBar(Static):
    """One-line service header, repainted on every resize.

    Holds the last result it was given and re-renders it against the width the
    terminal currently reports, so a resize re-divides the line without
    waiting for the next fetch.
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__("", name=name, id=id, classes=classes, disabled=disabled)
        self._status: ServiceStatusHeader | None = None

    def show(self, status: ServiceStatusHeader) -> None:
        """Take a fetched result and repaint. Call from the event loop."""
        self._status = status
        self.repaint_status()

    def repaint_status(self) -> None:
        """Re-render the held result at the width now reported.

        The content region, not the outer size: any padding the app's
        stylesheet gives this bar comes out of the line's room, and measuring
        against the outer width would admit a segment the padding then clips.
        """
        app = cast("App[object]", self.app)
        width = self.content_size.width or self.size.width or app.size.width
        self.update(
            render_status_header(self._status, width, tones=semantic_tones(app.theme))
        )

    def on_mount(self) -> None:
        self.repaint_status()

    def on_resize(self) -> None:
        self.repaint_status()
