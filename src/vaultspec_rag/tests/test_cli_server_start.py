"""CLI coverage for the server-first ``server start`` local-only surface.

Exercises the real Typer surface and the real daemon-env translation; no
mocks, patches, or fakes. The missing-binary loud-failure path on a default
start is covered at the integration tier in ``test_qdrant_server_mode.py``
(it needs an environment with no resolvable binary, which cannot be staged
without disturbing the live service this suite shares).
"""

from __future__ import annotations

import json
import os
import socket

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..cli._process import _service_child_env
from ..cli._service_start import (
    _existing_service_running,
    _fail_start,
    _start_success,
)
from ..config._types import EnvVar
from ..serviceclient._compat import local_package_version
from ._http_stubs import QuietHandler

pytestmark = [pytest.mark.unit]

runner = CliRunner()


def test_local_only_true_translates_to_daemon_env() -> None:
    env = _service_child_env(local_only=True)
    assert env[EnvVar.LOCAL_ONLY.value] == "1"


def test_local_only_false_translates_to_daemon_env() -> None:
    env = _service_child_env(local_only=False)
    assert env[EnvVar.LOCAL_ONLY.value] == "0"


def test_local_only_unset_preserves_operator_env() -> None:
    key = EnvVar.LOCAL_ONLY.value
    previous = os.environ.get(key)
    os.environ[key] = "1"
    try:
        env = _service_child_env(local_only=None)
        # None leaves the flag unwritten, so an operator-set value survives.
        assert env[key] == "1"
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def test_default_start_does_not_force_a_backend() -> None:
    # No flags: neither the server-mode nor the local-only knob is written,
    # so the daemon resolves the server-first default through its config.
    env = _service_child_env()
    assert EnvVar.LOCAL_ONLY.value not in env
    assert EnvVar.QDRANT_SERVER.value not in env


def test_server_start_help_renders_local_only_flag() -> None:
    result = runner.invoke(app, ["server", "start", "--help"])
    assert result.exit_code == 0
    assert "--local-only" in result.output


def test_server_start_help_renders_json_flag() -> None:
    result = runner.invoke(app, ["server", "start", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output


# --- rag-broker-affordances: idempotent JSON start ------------------------


class TestStartOutcomeHelpers:
    """The --json envelope contract for each start outcome."""

    def test_success_envelope_shape(self, capsys: pytest.CaptureFixture[str]) -> None:
        _start_success(
            True,
            status="already_running",
            human_title="Service already running",
            human_lines=("Process ID: 7", "Address: http://127.0.0.1:8766"),
            pid=7,
            port=8766,
        )
        env = json.loads(capsys.readouterr().out)
        assert env["ok"] is True
        assert env["command"] == "service.start"
        assert env["data"] == {"status": "already_running", "pid": 7, "port": 8766}

    def test_success_human_mode_emits_no_json(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _start_success(
            False,
            status="started",
            human_title="Service started",
            human_lines=("Process ID: 7",),
            pid=7,
            port=8766,
        )
        out = capsys.readouterr().out
        assert "Service started" in out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)

    def test_failure_envelope_shape_and_exit(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import typer

        exc = _fail_start(
            True,
            error="machine_owned",
            message="Service start failed",
            human_lines=("...",),
            holder_pid=4242,
        )
        assert isinstance(exc, typer.Exit)
        assert exc.exit_code == 1
        env = json.loads(capsys.readouterr().out)
        assert env["ok"] is False
        # The command name is asserted because the two lifecycle leaves now
        # share one emitter: without this, invoking the stop helper where the
        # start one belongs yields command "service.stop" and this test still
        # passes. The stop-side twin asserts its own name for the same reason.
        assert env["command"] == "service.start"
        assert env["error"] == "machine_owned"
        assert env["data"] == {"holder_pid": 4242}


class TestStartReorderAndGuards:
    """The reorder (idempotent first) and the genuine guard outcomes, live."""

    @pytest.mark.usefixtures("isolated_singleton_dirs")
    def test_no_recorded_service_is_not_running(self) -> None:
        # The isolated status dir has no service.json, so detection is None
        # (the idempotent check falls through to the guards).
        assert _existing_service_running() is None

    @pytest.mark.usefixtures("isolated_singleton_dirs")
    def test_a_serving_but_degraded_daemon_is_not_plain_already_running(
        self,
    ) -> None:
        # A daemon that answers /health with a non-ready status (models not
        # loaded, qdrant down) is still the idempotent success, but the
        # envelope must carry the health status instead of implying it can
        # serve (#237). A real HTTP responder stands in for the daemon's
        # health surface; the recorded pid is this live process.
        import http.server
        import threading

        # The release must match this client's or the start verb refuses to
        # attach at all, which is a different outcome than the degraded-health
        # one under test here.
        payload = json.dumps(
            {
                "status": "degraded",
                "service_token": "tok-live",
                "package_version": local_package_version(),
            }
        ).encode("utf-8")

        class _HealthHandler(QuietHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            from ..cli._service_status import _write_service_status
            from ..serviceclient._discovery import _status_file

            _write_service_status(os.getpid(), port)
            sf = _status_file()
            doc = json.loads(sf.read_text(encoding="utf-8"))
            doc["service_token"] = "tok-live"
            sf.write_text(json.dumps(doc), encoding="utf-8")

            candidate = _existing_service_running()
            assert candidate is not None
            assert (candidate.pid, candidate.port, candidate.health_status) == (
                os.getpid(),
                port,
                "degraded",
            )
            assert candidate.version.is_compatible

            result = runner.invoke(app, ["server", "start", "--json"])
            assert result.exit_code == 0
            env = json.loads(result.stdout)
            assert env["ok"] is True
            assert env["data"]["status"] == "already_running"
            assert env["data"]["health"] == "degraded"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    @pytest.mark.usefixtures("isolated_singleton_dirs")
    def test_a_warming_daemon_is_already_starting_not_a_fault(self) -> None:
        # A live owned daemon that stamped ``warming`` (machine lock held,
        # port not yet serving) is a start already in progress: exit 0 with
        # ``already_starting`` and the warming phase, never ``machine_owned``
        # exit 1 and never a plain ``already_running`` (#237). Port 1 is
        # silent, so nothing can round-trip a health token and the recorded pid
        # is judged by inspecting the process - which is why it names a live
        # stand-in carrying the daemon's witness rather than this interpreter.
        from ..cli._service_status import _write_service_status
        from ..serviceclient._discovery import _status_file
        from ._cli_helpers import process_the_identity_check_recognises

        with process_the_identity_check_recognises() as daemon_pid:
            _write_service_status(daemon_pid, 1)
            sf = _status_file()
            doc = json.loads(sf.read_text(encoding="utf-8"))
            doc["phase"] = "warming"
            sf.write_text(json.dumps(doc), encoding="utf-8")

            result = runner.invoke(app, ["server", "start", "--json"])

        assert result.exit_code == 0
        env = json.loads(result.stdout)
        assert env["ok"] is True
        assert env["data"]["status"] == "already_starting"
        assert env["data"]["phase"] == "warming"
        assert env["data"]["pid"] == daemon_pid

    @pytest.mark.usefixtures("isolated_singleton_dirs")
    def test_a_foreign_port_holder_is_port_in_use_json(self) -> None:
        # Bind a real socket so the port-bindable guard trips: no recorded
        # service (idempotent None), the port is taken by something that is NOT
        # our service -> the genuine port_in_use failure, stated as JSON.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            result = runner.invoke(
                app, ["server", "start", "--json", "--port", str(port)]
            )
            assert result.exit_code == 1
            env = json.loads(result.stdout)
            assert env["ok"] is False
            assert env["error"] == "port_in_use"
            assert env["data"]["port"] == port
        finally:
            sock.close()

    @pytest.mark.usefixtures("isolated_singleton_dirs")
    def test_a_machine_lock_holder_is_machine_owned_json(self) -> None:
        # Hold the real machine lock in THIS process, then a start on a free
        # port falls through the idempotent check and the port guard to the
        # machine guard -> machine_owned (with our pid), stated as JSON.
        from .._machine_lock import acquire_machine_lock, release_machine_lock

        acquired, _ = acquire_machine_lock()
        assert acquired, "the isolated machine lock should be free to acquire"
        try:
            # A free port so the port guard passes and we reach the machine guard.
            free = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            free.bind(("127.0.0.1", 0))
            port = free.getsockname()[1]
            free.close()
            result = runner.invoke(
                app, ["server", "start", "--json", "--port", str(port)]
            )
            assert result.exit_code == 1
            env = json.loads(result.stdout)
            assert env["ok"] is False
            assert env["error"] == "machine_owned"
            assert env["data"]["holder_pid"] == os.getpid()
        finally:
            release_machine_lock()
