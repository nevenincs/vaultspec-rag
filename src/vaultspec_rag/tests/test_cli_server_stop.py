"""CLI coverage for the ``server stop`` ``--json`` outcome envelopes.

Exercises the real Typer surface against isolated singleton paths; no
mocks, patches, or fakes. The happy stopped path against a real daemon is
covered at the integration tier in ``test_service_lifecycle.py``; here the
envelope helpers pin every status shape and the live CLI wiring covers the
outcomes that can be staged without a full service: ``already_stopped``
(both the default and ``--port`` variants), ``cleaned`` (a dead recorded
pid), and the ``identity_unconfirmed`` failure (a live recorded pid that is
not ours), which must exit 1 in both output modes.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..cli._service_lifecycle import _fail_stop, _stop_success
from ..config import EnvVar, reset_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

runner = CliRunner()


def test_server_stop_help_renders_json_flag() -> None:
    result = runner.invoke(app, ["server", "stop", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output


@pytest.fixture
def _isolated_singleton(  # pyright: ignore[reportUnusedFunction]
    tmp_path: Path,
) -> Iterator[None]:
    """Isolate the managed-singleton paths so stop touches only tmp.

    Sets both the status dir AND the qdrant storage dir (the machine lock
    lives beside the latter), per the managed-singleton-paths isolation rule,
    so the test never touches the operator's real service or lock.
    """
    status_key = EnvVar.STATUS_DIR.value
    storage_key = EnvVar.QDRANT_STORAGE_DIR.value
    prior = {
        status_key: os.environ.get(status_key),
        storage_key: os.environ.get(storage_key),
    }
    os.environ[EnvVar.STATUS_DIR.value] = str(tmp_path / "status")
    os.environ[EnvVar.QDRANT_STORAGE_DIR.value] = str(tmp_path / "qdrant" / "storage")
    reset_config()
    try:
        yield
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


class TestStopOutcomeHelpers:
    """The --json envelope contract for each stop outcome."""

    @pytest.mark.parametrize(
        "status", ["stopped", "already_stopped", "cleaned", "reclaimed"]
    )
    def test_success_envelope_shape(
        self, status: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _stop_success(
            True,
            status=status,
            human_title="Service stopped",
            human_lines=("Process ID: 7",),
            pid=7,
        )
        env = json.loads(capsys.readouterr().out)
        assert env["ok"] is True
        assert env["command"] == "service.stop"
        assert env["data"] == {"status": status, "pid": 7}

    def test_success_human_mode_emits_no_json(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _stop_success(
            False,
            status="stopped",
            human_title="Service stopped",
            human_lines=("Process ID: 7",),
            pid=7,
        )
        out = capsys.readouterr().out
        assert "Service stopped" in out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)

    def test_failure_envelope_shape_and_exit(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import typer

        exc = _fail_stop(
            True,
            error="identity_unconfirmed",
            message="Service stop skipped",
            human_lines=("...",),
            pid=4242,
        )
        assert isinstance(exc, typer.Exit)
        assert exc.exit_code == 1
        env = json.loads(capsys.readouterr().out)
        assert env["ok"] is False
        assert env["command"] == "service.stop"
        assert env["error"] == "identity_unconfirmed"
        assert env["data"] == {"pid": 4242}


class TestStopLiveOutcomes:
    """The stageable stop outcomes through the real CLI wiring."""

    @pytest.mark.usefixtures("_isolated_singleton")
    def test_nothing_to_stop_is_already_stopped_json(self) -> None:
        # No service.json in the isolated status dir and no machine-lock
        # holder: the idempotent success, exit 0.
        result = runner.invoke(app, ["server", "stop", "--json"])
        assert result.exit_code == 0
        env = json.loads(result.stdout)
        assert env["ok"] is True
        assert env["data"]["status"] == "already_stopped"

    @pytest.mark.usefixtures("_isolated_singleton")
    def test_silent_port_is_already_stopped_json(self) -> None:
        # Nothing answers on a fresh ephemeral port: the --port variant's
        # idempotent success.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        result = runner.invoke(app, ["server", "stop", "--json", "--port", str(port)])
        assert result.exit_code == 0
        env = json.loads(result.stdout)
        assert env["ok"] is True
        assert env["data"]["status"] == "already_stopped"
        assert env["data"]["port"] == port

    @pytest.mark.usefixtures("_isolated_singleton")
    def test_dead_recorded_pid_is_cleaned_json(self) -> None:
        # A discovery file recording a confirmed-dead pid is stale state the
        # stop removes: status `cleaned`, exit 0.
        from ..cli import _write_service_status

        probe = subprocess.run(
            [sys.executable, "-c", "import os; print(os.getpid())"],
            capture_output=True,
            text=True,
            check=True,
        )
        dead_pid = int(probe.stdout.strip())
        _write_service_status(dead_pid, 8766)
        result = runner.invoke(app, ["server", "stop", "--json"])
        assert result.exit_code == 0
        env = json.loads(result.stdout)
        assert env["ok"] is True
        assert env["data"]["status"] == "cleaned"
        assert env["data"]["pid"] == dead_pid

    @pytest.mark.usefixtures("_isolated_singleton")
    def test_live_unconfirmed_pid_is_identity_unconfirmed(self) -> None:
        # A live recorded pid whose identity cannot be confirmed as ours is
        # left running - the one genuine failure, exit 1 in BOTH modes. The
        # child must NOT be a python process: the discovery file carries no
        # token, so identity falls back to the executable-name check, which
        # would confirm a python child as ours (and the resulting terminate
        # sends CTRL_BREAK to the shared process group on Windows, killing
        # the test run itself).
        from ..cli import _write_service_status

        if sys.platform == "win32":
            child_args = ["cmd.exe", "/c", "ping -n 60 127.0.0.1 >nul"]
        else:
            child_args = ["sleep", "60"]
        child = subprocess.Popen(child_args)
        try:
            _write_service_status(child.pid, 8766)
            result = runner.invoke(app, ["server", "stop", "--json"])
            assert result.exit_code == 1
            env = json.loads(result.stdout)
            assert env["ok"] is False
            assert env["error"] == "identity_unconfirmed"
            assert env["data"]["pid"] == child.pid

            # Human mode carries the same exit-code contract.
            _write_service_status(child.pid, 8766)
            human = runner.invoke(app, ["server", "stop"])
            assert human.exit_code == 1
            assert "Service stop skipped" in human.stdout
        finally:
            child.kill()
            child.wait(timeout=10)
