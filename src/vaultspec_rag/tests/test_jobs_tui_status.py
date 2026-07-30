"""Tests for the jobs interface's service-status header.

Every payload here is copied from a live service's own answers, and every
assertion runs against rendered output rather than against a model attribute:
the header exists to be read at a glance, and a field that was computed but
never painted answers nothing.

The service under test is a real loopback ``http.server`` gating its
administrative routes on the bearer token exactly as the daemon does, so the
transport's token-recovery path is exercised rather than assumed.
"""

from __future__ import annotations

import http.server
import json
import threading
import typing

import pytest
from textual.app import App, ComposeResult

from ..cli._jobs_tui_status import (
    SeatPool,
    ServiceStatusBar,
    ServiceStatusHeader,
    fetch_service_status,
    render_status_header,
)
from ._http_stubs import QuietHandler

pytestmark = [pytest.mark.unit]

_SHUTDOWN_TIMEOUT = 5.0
_TOKEN = "08a6716c4f7442f1b4beddb007d646bd"

# The daemon's own answers, trimmed to the keys the header reads. Trimming is
# what an older service does too, so the shapes stay honest either way.
_HEALTH: dict[str, object] = {
    "status": "ready",
    "qdrant": {
        "mode": "server",
        "url": "http://127.0.0.1:8765",
        "alive": True,
        "port": 8765,
        "version": "1.18.2",
    },
    "pid": 58400,
    "cuda": True,
    "models_loaded": True,
    "project_count": 1,
    "uptime_s": 8384.4,
    "degraded_reasons": [],
    "schema_version": 2,
    "package_version": "0.3.11",
    "service_token": _TOKEN,
}

_PROJECTS: dict[str, object] = {
    "projects": [
        {
            "root": "/repos/example-worktrees/main",
            "last_access": 430419.3930949,
            "ref_count": 1,
            "idle_seconds": 588.1502224999713,
        }
    ],
    "max_projects": 16,
    "idle_ttl_seconds": 1800.0,
}

_SURVEY: dict[str, object] = {
    "namespaces": [
        {
            "prefix": "rea7120f40662_",
            "root": "/repos/example-worktrees/main",
            "status": "live",
            "points": 8225,
            "footprint_bytes": 1055084331,
        }
    ],
    "returned": 1,
    "total": 5,
    "limit": 1,
    "computed_at": "2026-07-27T17:17:33.970659+00:00",
    "source": "cache",
    "totals": {
        "total_bytes": 3220583349,
        "namespaces": 5,
        "points": 25740,
        "vault_points": 21231,
        "code_points": 4509,
        "document_points": 0,
        "by_status_bytes": {"live": 3220583349},
    },
}

_WATCHER: dict[str, object] = {
    "watch_enabled": True,
    "debounce_ms": 2000,
    "cooldown_s": 30.0,
    "watching": [],
}

# Prometheus text with every pool built. The encode gate is the machine-wide
# single admission slot.
_METRICS_ALL_POOLS = """\
# TYPE vaultspec_rag_search_total counter
vaultspec_rag_search_total 4
# TYPE vaultspec_rag_gpu_memory_allocated_bytes gauge
vaultspec_rag_gpu_memory_allocated_bytes 3699651584.0
# TYPE vaultspec_rag_search_pool_total_tokens gauge
vaultspec_rag_search_pool_total_tokens 16
# TYPE vaultspec_rag_search_pool_borrowed_tokens gauge
vaultspec_rag_search_pool_borrowed_tokens 0
# TYPE vaultspec_rag_search_pool_waiting gauge
vaultspec_rag_search_pool_waiting 0
# TYPE vaultspec_rag_index_pool_total_tokens gauge
vaultspec_rag_index_pool_total_tokens 4
# TYPE vaultspec_rag_index_pool_borrowed_tokens gauge
vaultspec_rag_index_pool_borrowed_tokens 1
# TYPE vaultspec_rag_index_pool_waiting gauge
vaultspec_rag_index_pool_waiting 0
# TYPE vaultspec_rag_encode_pool_total_tokens gauge
vaultspec_rag_encode_pool_total_tokens 1
# TYPE vaultspec_rag_encode_pool_borrowed_tokens gauge
vaultspec_rag_encode_pool_borrowed_tokens 0
# TYPE vaultspec_rag_encode_pool_waiting gauge
vaultspec_rag_encode_pool_waiting 0
"""

# What an idle service actually publishes: the encode and index limiters have
# never been built, so their gauges are absent entirely.
_METRICS_SEARCH_ONLY = """\
# TYPE vaultspec_rag_search_pool_total_tokens gauge
vaultspec_rag_search_pool_total_tokens 16
# TYPE vaultspec_rag_search_pool_borrowed_tokens gauge
vaultspec_rag_search_pool_borrowed_tokens 0
# TYPE vaultspec_rag_search_pool_waiting gauge
vaultspec_rag_search_pool_waiting 0
"""


def _status_answers(
    health: dict[str, object] | None,
    projects: dict[str, object] | None,
    survey: dict[str, object] | None,
    watcher: dict[str, object] | None,
    metrics: str | None,
) -> dict[str, object | None]:
    """Return one service's route payloads, including its public health view."""
    return {
        "/health": health,
        "/projects": projects,
        "/storage/survey": survey,
        "/watcher": watcher,
        "/metrics": metrics,
    }


class _StatusService:
    """A real loopback service answering the header's four routes.

    Routes other than ``/health`` are token-gated the way the daemon gates
    them, so a test drives the transport's real 401-then-retry recovery.
    """

    def __init__(
        self,
        answers: dict[str, object | None],
        *,
        health_status: int = 200,
    ) -> None:
        health = answers["/health"]
        metrics = answers["/metrics"]
        routes: dict[str, object | None] = {
            path: payload if isinstance(payload, dict) else None
            for path, payload in answers.items()
            if path in {"/projects", "/storage/survey", "/watcher"}
        }

        class _Handler(QuietHandler):
            def _send(self, code: int, body: bytes, content_type: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, payload: object) -> None:
                self._send(
                    code, json.dumps(payload).encode("utf-8"), "application/json"
                )

            def _authorised(self) -> bool:
                header = self.headers.get("Authorization") or ""
                return header == f"Bearer {_TOKEN}"

            def _health(self) -> None:
                if isinstance(health, dict):
                    self._json(health_status, typing.cast("dict[str, object]", health))
                    return
                self._json(health_status, {"ok": False})

            def _metrics(self) -> None:
                if isinstance(metrics, str):
                    self._send(
                        200,
                        metrics.encode("utf-8"),
                        "text/plain; version=0.0.4",
                    )
                    return
                self._json(404, {"ok": False, "error": "not_found"})

            def _route(self, path: str) -> None:
                payload = routes.get(path)
                if payload is not None:
                    self._json(200, payload)
                    return
                self._json(404, {"ok": False, "error": "not_found"})

            def do_GET(self) -> None:
                path = self.path.partition("?")[0]
                if path == "/health":
                    self._health()
                elif not self._authorised():
                    self._json(401, {"ok": False, "error": "unauthorized"})
                elif path == "/metrics":
                    self._metrics()
                else:
                    self._route(path)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=_SHUTDOWN_TIMEOUT)


def _service(
    *,
    health: dict[str, object] | None = _HEALTH,
    projects: dict[str, object] | None = _PROJECTS,
    survey: dict[str, object] | None = _SURVEY,
    watcher: dict[str, object] | None = _WATCHER,
    metrics: str | None = _METRICS_ALL_POOLS,
) -> _StatusService:
    """Stand up a fully-reporting service, minus whatever is overridden."""
    return _StatusService(
        _status_answers(health, projects, survey, watcher, metrics),
    )


@pytest.fixture
def full_service() -> typing.Iterator[_StatusService]:
    server = _service()
    try:
        yield server
    finally:
        server.close()


def _closed_port() -> int:
    """Return a port nothing is listening on."""
    server = _StatusService(_status_answers(None, None, None, None, None))
    port = server.port
    server.close()
    return port


def _painted(status: ServiceStatusHeader, width: int = 240) -> str:
    """Render the header and return the text an operator would read."""
    return render_status_header(status, width).plain


class _HeaderApp(App[None]):
    """The smallest host for the header widget."""

    def __init__(self, status: ServiceStatusHeader) -> None:
        super().__init__()
        self._status = status

    def compose(self) -> ComposeResult:
        yield ServiceStatusBar(id="servicestatus")

    def on_mount(self) -> None:
        self.query_one("#servicestatus", ServiceStatusBar).show(self._status)


def _screen_text(app: _HeaderApp) -> str:
    """Return what the interface actually painted, as text."""
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


class TestTheOperatorsFourQuestions:
    """Each ask, answered from a field the service publishes."""

    def test_the_full_payload_answers_space_seats_and_status(
        self, full_service: _StatusService
    ) -> None:
        painted = _painted(fetch_service_status(full_service.port))

        assert "service ready" in painted, "the health verdict must be readable"
        # The whole backend's footprint, not this project's namespace.
        assert "store 3.0 GiB" in painted
        # The single machine-wide encode admission slot.
        assert "seats 0/1" in painted
        assert "projects 1/16" in painted
        assert "qdrant live" in painted
        assert "watching 0" in painted
        assert "up 2h19m" in painted

    def test_in_flight_leases_are_reported_under_their_own_name(
        self, full_service: _StatusService
    ) -> None:
        painted = _painted(fetch_service_status(full_service.port))

        # ``ref_count`` counts concurrent requests holding a project lease.
        # Calling that "clients" would be a fabrication, so it is named for
        # what it is.
        assert "in flight 1" in painted

    def test_search_pool_occupancy_and_waiting_are_painted(self) -> None:
        status = ServiceStatusHeader(
            reachable=True,
            status="ready",
            seats=(SeatPool(name="search", used=16, total=16, waiting=3),),
        )

        painted = _painted(status)

        assert "search 16/16 +3 waiting" in painted, (
            "served-search pressure must not be parsed and then discarded"
        )

    def test_connected_clients_read_as_absent_on_a_full_payload(
        self, full_service: _StatusService
    ) -> None:
        status = fetch_service_status(full_service.port)
        painted = _painted(status)

        # The service publishes no connection accounting at all. A header that
        # showed a zero here would assert nobody is connected, which is a claim
        # nothing in the payload supports.
        assert status.clients is None
        assert "clients —" in painted
        assert "clients 0" not in painted

    def test_a_degraded_service_carries_its_reason_count(self) -> None:
        degraded = dict(_HEALTH)
        degraded["status"] = "degraded"
        degraded["degraded_reasons"] = [
            "the configured vector service is not live",
            "1 indexing job(s) are stalled",
        ]
        server = _service(health=degraded)
        try:
            painted = _painted(fetch_service_status(server.port))
        finally:
            server.close()

        assert "service degraded (2)" in painted


class TestDegradation:
    """An older, sicker, or absent service must still render."""

    def test_a_payload_missing_every_optional_field_reads_as_absent(self) -> None:
        server = _StatusService(
            _status_answers(
                {"status": "ready", "service_token": _TOKEN},
                None,
                None,
                None,
                None,
            )
        )
        try:
            status = fetch_service_status(server.port)
            painted = _painted(status)
        finally:
            server.close()

        assert "service ready" in painted, "what it did report must still show"
        # Every unreported measure reads as absent. A zero here would say the
        # store is empty and the gate is free, neither of which is known.
        assert "store —" in painted
        assert "seats —" in painted
        assert "projects —" in painted
        assert "in flight —" in painted
        assert "watching —" in painted
        assert "up —" in painted
        assert "store 0" not in painted
        assert "seats 0" not in painted

    def test_an_unexercised_limiter_is_absent_rather_than_empty(self) -> None:
        # An idle service has never built the encode limiter, so ``/metrics``
        # omits its gauges entirely - the shape the live service answered with.
        server = _service(metrics=_METRICS_SEARCH_ONLY)
        try:
            status = fetch_service_status(server.port)
            painted = _painted(status)
        finally:
            server.close()

        assert status.seat_pool("encode") is None
        assert "seats —" in painted
        assert "seats 0/1" not in painted
        # The pool the service did report is still read.
        assert status.seat_pool("search") == status.seats[0]

    def test_an_unreachable_service_says_so(self) -> None:
        status = fetch_service_status(_closed_port())
        painted = _painted(status)

        assert status.reachable is False
        assert "service unreachable" in painted
        # Nothing was learned, so nothing may be claimed - not even a zero.
        assert "store" not in painted
        assert "seats" not in painted

    def test_an_absent_port_is_not_an_unreachable_service(self) -> None:
        painted = _painted(fetch_service_status(None))

        assert "service unreachable" in painted
        assert "no service port" in painted

    def test_a_sick_service_is_distinguished_from_an_absent_one(self) -> None:
        server = _StatusService(
            _status_answers(None, None, None, None, None),
            health_status=500,
        )
        try:
            status = fetch_service_status(server.port)
            painted = _painted(status)
        finally:
            server.close()

        assert status.reachable is True
        assert "service error" in painted
        assert "unreachable" not in painted

    def test_the_fetch_never_raises_on_a_hostile_payload(self) -> None:
        server = _StatusService(
            _status_answers(
                {"status": 7, "uptime_s": "soon", "service_token": _TOKEN},
                {"projects": "not a list", "max_projects": None},
                {"totals": []},
                {"watching": 3},
                "vaultspec_rag_encode_pool_total_tokens not-a-number\n",
            )
        )
        try:
            painted = _painted(fetch_service_status(server.port))
        finally:
            server.close()

        assert "store —" in painted
        assert "seats —" in painted
        assert "watching —" in painted


class TestWidth:
    """The line is divided by measurement, never by a fixed cell count."""

    def test_a_narrow_terminal_sheds_the_rightmost_fields(
        self, full_service: _StatusService
    ) -> None:
        status = fetch_service_status(full_service.port)

        narrow = _painted(status, width=40)
        wide = _painted(status, width=240)

        assert len(narrow) <= 40
        assert "service ready" in narrow, "the verdict survives every width"
        assert "store 3.0 GiB" in narrow, "the footprint is the next to survive"
        assert "up 2h19m" not in narrow, "the tail must be shed"
        assert "up 2h19m" in wide, "and must return when there is room"
        assert len(wide) > len(narrow)

    def test_the_header_is_never_empty_however_narrow(
        self, full_service: _StatusService
    ) -> None:
        status = fetch_service_status(full_service.port)

        # A header that vanished under pressure would read as a service that
        # stopped answering.
        assert "service ready" in _painted(status, width=4)

    def test_an_unknown_width_admits_every_field(
        self, full_service: _StatusService
    ) -> None:
        # A widget painting before its first layout pass reports zero width.
        status = fetch_service_status(full_service.port)

        assert "up 2h19m" in _painted(status, width=0)

    def test_nothing_fetched_yet_reads_as_pending(self) -> None:
        assert render_status_header(None, 200).plain == "service …"


class TestTheMountedWidget:
    """What the interface actually paints, driven through Textual."""

    @pytest.mark.asyncio
    async def test_the_mounted_header_paints_every_answer(
        self, full_service: _StatusService
    ) -> None:
        status = fetch_service_status(full_service.port)
        app = _HeaderApp(status)
        async with app.run_test(size=(240, 24)):
            painted = _screen_text(app)

        assert "service ready" in painted
        assert "store 3.0 GiB" in painted
        assert "seats 0/1" in painted
        assert "clients —" in painted
        assert "projects 1/16" in painted

    @pytest.mark.asyncio
    async def test_the_mounted_header_sheds_fields_on_a_narrow_screen(
        self, full_service: _StatusService
    ) -> None:
        status = fetch_service_status(full_service.port)
        narrow = _HeaderApp(status)
        async with narrow.run_test(size=(46, 24)):
            painted_narrow = _screen_text(narrow)
        wide = _HeaderApp(status)
        async with wide.run_test(size=(240, 24)):
            painted_wide = _screen_text(wide)

        assert "service ready" in painted_narrow
        assert "projects 1/16" not in painted_narrow
        assert "projects 1/16" in painted_wide

    @pytest.mark.asyncio
    async def test_a_resize_re_divides_without_a_new_fetch(
        self, full_service: _StatusService
    ) -> None:
        status = fetch_service_status(full_service.port)
        app = _HeaderApp(status)
        async with app.run_test(size=(46, 24)) as pilot:
            assert "projects 1/16" not in _screen_text(app)
            await pilot.resize_terminal(240, 24)
            await pilot.pause()
            painted = _screen_text(app)

        assert "projects 1/16" in painted
