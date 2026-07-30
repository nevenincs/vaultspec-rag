"""CPU-only adapter guards for the canonical service quiesce vocabulary."""

from __future__ import annotations

import contextlib
import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ..service_quiesce import (
    QUIESCE_ENVELOPE_FIELDS,
    QuiesceSnapshot,
    QuiesceState,
)

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = [pytest.mark.unit]

_QUIESCED_BLOCK = {
    "state": "quiesced",
    "admission_epoch": 7,
    "admissions_open": False,
    "active_compute_tickets": 0,
    "drain_complete": True,
    "vram_released": True,
    "safe_to_borrow_gpu": True,
    "pause_requested_at": 100.0,
    "drain_acknowledged_at": 101.0,
    "quiesced_at": 102.0,
    "warming_started_at": None,
    "failure_reason": None,
}


def test_the_envelope_field_set_is_derived_from_the_snapshot() -> None:
    """The published vocabulary must be what the controller actually renders.

    ``QUIESCE_ENVELOPE_FIELDS`` is derived from the dataclass, while
    ``as_envelope`` builds a dict literal; nothing but this makes the two agree.
    Adapters reject a block whose key set differs from the constant, so a field
    added to one and not the other would not fail here first - it would show up
    as every surface reporting the daemon unavailable.

    Mutation proof: renaming ``vram_released`` in ``as_envelope`` alone fails
    this on the key-set comparison below, not on an import or a lookup.
    """
    snapshot = QuiesceSnapshot(
        state=QuiesceState.RUNNING,
        admission_epoch=0,
        admissions_open=True,
        active_compute_tickets=0,
        drain_complete=False,
        vram_released=False,
        safe_to_borrow_gpu=False,
        pause_requested_at=None,
        drain_acknowledged_at=None,
        quiesced_at=None,
        warming_started_at=None,
        failure_reason=None,
    )
    assert set(snapshot.as_envelope()) == set(QUIESCE_ENVELOPE_FIELDS)


def test_the_adapter_fixture_block_matches_the_canonical_vocabulary() -> None:
    """The fixture below stands in for a real daemon response.

    A fixture carrying a stale key set would keep the adapter guards passing
    against a block no service sends, which is the failure mode those guards
    exist to catch.
    """
    assert set(_QUIESCED_BLOCK) == set(QUIESCE_ENVELOPE_FIELDS)


def _run_mcp_service_state_probe(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Drive the MCP service-state tool through discovery and a real socket."""
    probe = r"""
import asyncio
import http.server
import json
import os
import sys
import threading
from pathlib import Path

base = Path(sys.argv[1])
status_dir = base / "status"
status_dir.mkdir()
workspace = base / "workspace"
(workspace / ".vault").mkdir(parents=True)
(workspace / ".vaultspec").mkdir()
os.environ["VAULTSPEC_RAG_STATUS_DIR"] = str(status_dir)
os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"] = str(base / "qdrant")

from vaultspec_rag.config._settings import reset_config

reset_config()

# Handed in rather than restated: a second copy of the block here would go
# stale against the controller's vocabulary without failing the pin that
# guards the one above it.
quiesce = json.loads(sys.argv[2])
service_state = {
    "index": {"status": "ready"},
    "projects": {"projects": []},
    "watcher": {"watching": []},
    "qdrant": {"alive": True},
    "quiesce": quiesce,
    "schema_version": 1,
}
body = json.dumps(service_state).encode("utf-8")


class ServiceStateResponder(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0] != "/service-state":
            self.send_response(404)
            self.end_headers()
            return
        token = self.headers.get("Authorization")
        assert token == "Bearer quiesce-adapter-token", token
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ServiceStateResponder)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    from vaultspec_rag.config._paths import SERVICE_STATUS_FILENAME
    from vaultspec_rag.serviceclient._compat import (
        SERVICE_VERSION_FIELD,
        local_package_version,
    )
    from vaultspec_rag.serviceclient._discovery import (
        SERVICE_DISCOVERY_SCHEMA,
        SERVICE_DISCOVERY_VERSION,
    )

    (status_dir / SERVICE_STATUS_FILENAME).write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "port": server.server_address[1],
                "schema": SERVICE_DISCOVERY_SCHEMA,
                "version": SERVICE_DISCOVERY_VERSION,
                SERVICE_VERSION_FIELD: local_package_version(),
                "service_token": "quiesce-adapter-token",
            }
        ),
        encoding="utf-8",
    )

    from vaultspec_rag.mcp._tools import get_index_status

    result = asyncio.run(get_index_status(project_root=str(workspace)))
    assert result == service_state, result
    forbidden = {"torch", "sentence_transformers", "transformers", "qdrant_client"}
    assert not forbidden.intersection(name.split(".", 1)[0] for name in sys.modules)
    print(json.dumps(result))
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd() / "src")
    return subprocess.run(
        [sys.executable, "-c", probe, str(tmp_path), json.dumps(_QUIESCED_BLOCK)],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def test_mcp_service_state_keeps_the_canonical_quiesce_block_verbatim(
    tmp_path: Path,
) -> None:
    """MCP observes a bare service-state document without lifecycle inference.

    Mutation: wrap the successful service-state result in a new envelope.
    Exact equality fails, proving the adapter cannot hide, rename, or recreate
    the controller-owned quiesce block.
    """
    completed = _run_mcp_service_state_probe(tmp_path)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["quiesce"] == _QUIESCED_BLOCK
    assert set(result["quiesce"]) == set(_QUIESCED_BLOCK)


def _jobs_payload(quiesce: object | None) -> dict[str, object]:
    """Return one real jobs-route payload, optionally carrying quiesce truth."""
    payload: dict[str, object] = {
        "jobs": [],
        "total": 0,
        "returned": 0,
        "summary": {},
        "gpu": {},
        "pressure": {},
    }
    if quiesce is not None:
        payload["quiesce"] = quiesce
    return payload


@contextlib.contextmanager
def _jobs_tui_responder(payload: dict[str, object]) -> Generator[int]:
    """Serve the jobs and observability exchanges over a real loopback socket."""
    service = payload
    observability: dict[str, dict[str, object]] = {
        "/health": {"status": "ready"},
        "/projects": {"projects": [], "max_projects": 1},
        "/watcher": {"watching": []},
        "/search-activity": {
            "active": [],
            "recent": [],
            "counts": {"active": 0, "recent": 0, "total": 0},
            "returned": 0,
            "filters": {},
        },
        "/logs/json": {"source": "all", "limit": 200, "groups": [], "filters": {}},
        "/storage/survey": {"totals": {}},
    }

    class JobsTuiResponder(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            empty_response: dict[str, object] = {}
            body: dict[str, object] = (
                service if path == "/jobs" else observability.get(path, empty_response)
            )
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            del format, args
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), JobsTuiResponder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


async def _paint_quiesce_jobs_tui(payload: dict[str, object]) -> tuple[object, str]:
    """Run the actual Textual jobs surface over the production admin transport."""
    from ..cli._jobs_tui import ServerWatchApp
    from ..serviceclient._transport import _try_http_admin

    with _jobs_tui_responder(payload) as port:

        def fetch() -> dict[str, object] | None:
            return _try_http_admin("get_jobs", {}, port)

        app = ServerWatchApp(
            fetch=fetch,
            port=port,
            interval=3600.0,
            watch_mode="jobs",
        )
        async with app.run_test(size=(220, 50), notifications=True) as pilot:
            for _ in range(100):
                await pilot.pause()
                if app._last_refresh is not None:
                    break
            assert app._last_refresh is not None
            painted = "\n".join(
                strip.text.replace("\u2800", " ")
                for strip in app.screen._compositor.render_strips()
            )
            return app._quiesce, painted


@pytest.mark.asyncio
async def test_jobs_tui_renders_the_reported_quiesce_controller_evidence() -> None:
    """TUI presents controller state without translating it into permission.

    Mutation: remove the quiesce payload capture in ``_apply_result``. The
    direct transport still succeeds, but the retained canonical block and all
    three operator-visible controller facts disappear.
    """
    quiesce, painted = await _paint_quiesce_jobs_tui(_jobs_payload(_QUIESCED_BLOCK))

    assert quiesce == _QUIESCED_BLOCK
    assert "quiesce quiesced" in painted
    assert "vram released" in painted
    assert "borrower safety safe" in painted


@pytest.mark.asyncio
@pytest.mark.parametrize("quiesce", [None, {"state": "quiesced"}])
async def test_jobs_tui_treats_missing_or_invalid_quiesce_as_unavailable(
    quiesce: object | None,
) -> None:
    """No incomplete service observation may be rendered as borrower safety."""
    retained, painted = await _paint_quiesce_jobs_tui(_jobs_payload(quiesce))

    assert retained is None
    assert "quiesce unavailable" in painted
    assert "borrower safety safe" not in painted
