"""Guard tests for ``server preflight``'s envelope, exit code, and fallback.

These are guard tests, not positive coverage. The load-bearing properties are:
a device-load reading that admits exits 0, one that refuses exits 1 (never the
reverse); a daemon that cannot answer the question is reported unavailable
rather than silently answered by a second, local probe; and every ``--json``
invocation writes exactly one envelope. Each is proven able to fail by the
mutation it names.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from collections.abc import Generator

    from typer.testing import Result

from .._gpu_admission import DeviceAdmission
from ..cli import _service_preflight, app
from ._http_stubs import QuietHandler
from ._import_probe import assert_fresh_import_excludes, import_probe_source

pytestmark = [pytest.mark.unit]

runner = CliRunner()


@contextlib.contextmanager
def _health_service(health: dict[str, Any] | None) -> Generator[int | None]:
    """Serve one ``/health`` body over real HTTP on a real port.

    The verb under test resolves a port, opens a socket, and parses a wire
    response, so that is what it is given. ``None`` means no service at all:
    nothing is bound and no port is passed.
    """
    if health is None:
        yield None
        return

    body = json.dumps(health).encode()

    class _Handler(QuietHandler):
        def do_GET(self) -> None:
            if self.path != "/health":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _invoke(port: int | None, *, json_mode: bool = True) -> Result:
    args = ["server", "preflight"]
    if json_mode:
        args.append("--json")
    if port is not None:
        args += ["--port", str(port)]
    return runner.invoke(app, args)


def _body(result: Result) -> dict[str, Any]:
    return json.loads(result.output)


_ADMITTED_BLOCK = {
    "free_mib": 14000,
    "total_mib": 16376,
    "floor_mib": 6400,
    "admitted": True,
    "reason": "",
}
_REFUSED_BLOCK = {
    "free_mib": 2000,
    "total_mib": 16376,
    "floor_mib": 6400,
    "admitted": False,
    "reason": "below_floor",
}
_TORCH_ABSENT_BLOCK = {
    "free_mib": None,
    "total_mib": None,
    "floor_mib": 6400,
    "admitted": False,
    "reason": "torch_absent",
}


def test_daemon_admitted_reading_exits_zero() -> None:
    """Mutation: flipped the exit mapping to ``1 if admitted else 0``.

    Observed this assertion fail on ``exit_code == 0``.
    """
    with _health_service({"device_load": _ADMITTED_BLOCK}) as port:
        result = _invoke(port)
    assert result.exit_code == 0, result.output
    body = _body(result)
    assert body["ok"] is True
    assert body["data"]["source"] == "service"
    assert body["data"]["admitted"] is True


def test_daemon_refused_reading_exits_one() -> None:
    """The load-bearing guard: a reading that refuses must exit non-zero, or a
    broker reads a contended card as clear to load.

    Mutation: flipped the exit mapping to ``0 if not admitted else 1``.
    Observed this assertion fail on ``exit_code == 1``.
    """
    with _health_service({"device_load": _REFUSED_BLOCK}) as port:
        result = _invoke(port)
    assert result.exit_code == 1, result.output
    body = _body(result)
    assert body["ok"] is False
    assert body["error"] == "below_floor"
    assert "6400 MiB floor" in body["message"]


def test_daemon_torch_absent_reading_exits_one() -> None:
    """A torch-free (or CUDA-less) daemon host is a refusal here, not a crash.

    Mutation: added ``REASON_TORCH_ABSENT`` to a set of reasons the exit
    mapping treats as admitted. Observed this assertion fail on
    ``exit_code == 1``.
    """
    with _health_service({"device_load": _TORCH_ABSENT_BLOCK}) as port:
        result = _invoke(port)
    assert result.exit_code == 1, result.output
    body = _body(result)
    assert body["ok"] is False
    assert body["error"] == "torch_absent"
    assert body["data"]["free_mib"] is None


def test_daemon_missing_device_load_block_never_falls_back_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live daemon owns this question; a CLI-local probe must never run
    alongside it, even when the daemon's own reading is unavailable.

    Mutation: made the missing-block branch call ``_local_admission()``
    instead of failing. Observed this assertion fail on ``not local_calls``,
    the local probe having actually run.
    """
    local_calls: list[DeviceAdmission] = []

    def _tracked_local_admission() -> DeviceAdmission:
        admission = DeviceAdmission(
            admitted=True, free_mib=9000, total_mib=16376, floor_mib=6400, reason=""
        )
        local_calls.append(admission)
        return admission

    monkeypatch.setattr(
        _service_preflight, "_local_admission", _tracked_local_admission
    )
    with _health_service({"status": "ready"}) as port:  # no "device_load" key
        result = _invoke(port)
    assert not local_calls, "the local probe ran despite a live daemon answering"
    assert result.exit_code == 1, result.output
    assert _body(result)["error"] == "device_load_unavailable"


def test_unreachable_daemon_never_falls_back_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``--port`` that names nothing listening is unavailable, not local.

    Mutation: same as above, applied to the connection-refused branch.
    Observed this assertion fail on ``not local_calls``.
    """
    local_calls: list[DeviceAdmission] = []

    def _tracked_local_admission() -> DeviceAdmission:
        admission = DeviceAdmission(
            admitted=True, free_mib=9000, total_mib=16376, floor_mib=6400, reason=""
        )
        local_calls.append(admission)
        return admission

    monkeypatch.setattr(
        _service_preflight, "_local_admission", _tracked_local_admission
    )
    # An explicit --port bypasses discovery entirely, so this exercises the
    # "resolved but unreachable" branch deterministically: nothing is bound to
    # this port, so the health probe reports connection-refused.
    result = _invoke(65535)
    assert not local_calls, "the local probe ran despite an explicit --port"
    assert result.exit_code == 1, result.output
    assert _body(result)["error"] == "device_load_unavailable"


def test_no_daemon_discovered_falls_back_to_the_local_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent any daemon, this CLI invocation is the would-be GPU consumer,
    so it takes the local reading itself.

    Mutation: made ``_default_service_port`` resolution short-circuit to a
    fixed local admission without ever calling the production accessor.
    Observed this assertion fail on ``body["data"]["source"] == "local"``
    when the accessor was bypassed and the wrong reading returned.
    """
    monkeypatch.setattr(_service_preflight, "_default_service_port", lambda: None)
    monkeypatch.setattr(
        _service_preflight,
        "_local_admission",
        lambda: DeviceAdmission(
            admitted=True, free_mib=9000, total_mib=16376, floor_mib=6400, reason=""
        ),
    )
    result = runner.invoke(app, ["server", "preflight", "--json"])
    assert result.exit_code == 0, result.output
    body = _body(result)
    assert body["data"]["source"] == "local"
    assert body["data"]["free_mib"] == 9000


def test_exactly_one_json_envelope_per_invocation() -> None:
    """The broker contract requires exactly one structured document on stdout.

    Asserted against stdout alone, deliberately: this CLI routes diagnostics to
    stderr so they survive ``--json`` without touching the result channel.

    Mutation: added a second ``_emit_json`` call ahead of the real one.
    Observed this assertion fail with ``len(lines) == 2``.
    """
    with _health_service({"device_load": _ADMITTED_BLOCK}) as port:
        result = _invoke(port)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, result.stdout
    json.loads(lines[0])


def test_human_mode_prints_the_reading_and_verdict() -> None:
    """Human output must show WHY a refusal happened, not just that it did."""
    with _health_service({"device_load": _REFUSED_BLOCK}) as port:
        result = _invoke(port, json_mode=False)
    assert result.exit_code == 1, result.output
    assert "2000 MiB" in result.output
    assert "6400 MiB" in result.output
    assert "refused" in result.output


class TestTorchFreedom:
    """The CLI service-control surface may not drag torch onto its own import."""

    def test_importing_the_verb_loads_no_torch(self) -> None:
        """Mutation: added a module-scope ``import torch`` to
        ``_service_preflight``. Observed the probe child fail, its stderr
        naming ``['torch', 'torch._C', ...]``.
        """
        assert_fresh_import_excludes(
            import_probe_source("vaultspec_rag.cli._service_preflight")
        )
