"""``server stop --port`` targeting tests (plan W04.P09).

No mocks, no GPU: the port-resolution path is exercised against real loopback
sockets. ``server stop --port`` resolves the running instance from its /health
identity rather than the status file, so a non-default-port service whose status
file is missing or divergent (research F7) is still stoppable. The terminate
path itself is covered end to end against a real daemon in the integration
suite; here the focus is the deterministic, side-effect-free resolution paths.
"""

from __future__ import annotations

import socket

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..cli._service_lifecycle import _service_pid_on_port, _stop_service_on_port

pytestmark = [pytest.mark.unit]

runner = CliRunner()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestServicePidOnPort:
    def test_free_port_resolves_to_none(self) -> None:
        assert _service_pid_on_port(_free_port()) is None


class TestStopServiceOnPort:
    def test_nothing_listening_reports_not_running(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A free port has no service to stop; the call must be a clean no-op that
        # never terminates anything.
        _stop_service_on_port(_free_port())
        out = capsys.readouterr().out.lower()
        assert "not running" in out


class TestStopCliPortOption:
    def test_stop_accepts_port_option_with_no_service(self) -> None:
        # The pre-fix defect was a hard `No such option '--port'`. The option
        # now exists, and stopping a free port exits 0 with "not running".
        port = _free_port()
        result = runner.invoke(app, ["server", "stop", "--port", str(port)])
        assert result.exit_code == 0, result.output
        assert "no such option" not in result.output.lower()
        assert "not running" in result.output.lower()
