"""CLI coverage for the ``server stop`` ``--json`` outcome envelopes.

Exercises the real Typer surface against isolated singleton paths; no
mocks, patches, or fakes. The happy stopped path against a real daemon is
covered at the integration tier in ``test_service_lifecycle.py``; here the
envelope helpers pin every status shape and the live CLI wiring covers the
outcomes that can be staged without a full service: ``already_stopped``
(both the default and ``--port`` variants), ``cleaned`` (a dead recorded
pid), and the ``identity_unconfirmed`` failure (a live recorded pid that is
not ours), which must exit 1 in both output modes.

The orphan reap answers to the same contract, so its two statuses are pinned
here alongside the rest: ``reaped`` as a success, and the
``orphan_reap_incomplete`` fault whose surviving pids cannot be staged live
because it needs a process that outlives a force-kill.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from ..cli import _log_file, app
from ..cli._service_lifecycle import (
    _fail_stop,
    _initiator_fields,
    _stop_success,
    _terminate_and_confirm,
)

pytestmark = [pytest.mark.unit]

runner = CliRunner()


def test_server_stop_help_renders_json_flag() -> None:
    result = runner.invoke(app, ["server", "stop", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output


class TestStopOutcomeHelpers:
    """The --json envelope contract for each stop outcome."""

    @pytest.mark.parametrize(
        "status", ["stopped", "already_stopped", "cleaned", "reclaimed", "reaped"]
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

    def test_orphan_reap_incomplete_failure_envelope(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # An orphan that refuses to die leaves the requested state unachieved,
        # so it is a fault and not a partial success - and the surviving pids
        # ride in the envelope, because "reaped some, one would not die" is the
        # outcome an operator has to act on. This shape cannot be staged live
        # (it needs a process that survives a force-kill), so the helper is
        # where it is pinned.
        import typer

        exc = _fail_stop(
            True,
            error="orphan_reap_incomplete",
            message="Orphan reap left daemons running",
            human_lines=("...",),
            reaped=1,
            survivors=[4242],
            port=8766,
        )
        assert isinstance(exc, typer.Exit)
        assert exc.exit_code == 1
        env = json.loads(capsys.readouterr().out)
        assert env["ok"] is False
        assert env["command"] == "service.stop"
        assert env["error"] == "orphan_reap_incomplete"
        assert env["data"] == {"reaped": 1, "survivors": [4242], "port": 8766}


class TestStopLiveOutcomes:
    """The stageable stop outcomes through the real CLI wiring."""

    @pytest.mark.usefixtures("isolated_singleton_dirs")
    def test_nothing_to_stop_is_already_stopped_json(self) -> None:
        # No service.json in the isolated status dir and no machine-lock
        # holder: the idempotent success, exit 0.
        result = runner.invoke(app, ["server", "stop", "--json"])
        assert result.exit_code == 0
        env = json.loads(result.stdout)
        assert env["ok"] is True
        assert env["data"]["status"] == "already_stopped"

    @pytest.mark.usefixtures("isolated_singleton_dirs")
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

    @pytest.mark.usefixtures("isolated_singleton_dirs")
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
        # `cleaned` removes stale discovery state without terminating anything,
        # so it carries no initiator attribution.
        assert "initiator_pid" not in env["data"]
        assert "initiator_cmd" not in env["data"]
        assert "initiator_cwd" not in env["data"]

    @pytest.mark.usefixtures("isolated_singleton_dirs")
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


class TestShutdownAttribution:
    """The initiator identity carried on terminating stops (pid, cmd, cwd)."""

    def test_initiator_fields_shape(self) -> None:
        fields = _initiator_fields()
        assert fields["initiator_pid"] == str(os.getpid())
        cmd = fields["initiator_cmd"]
        assert cmd
        assert "pytest" in cmd.lower() or "python" in cmd.lower()
        assert len(cmd) <= 300
        assert os.path.isdir(fields["initiator_cwd"])
        assert fields["initiator_cwd"] == os.getcwd()

    def test_stopped_envelope_carries_initiator_fields(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The terminating outcomes pass **_initiator_fields() into the envelope;
        # assert the fields land in `data` through the real helper.
        _stop_success(
            True,
            status="stopped",
            human_title="Service stopped",
            human_lines=("Process ID: 7",),
            pid=7,
            port=8766,
            **_initiator_fields(),
        )
        data = json.loads(capsys.readouterr().out)["data"]
        assert data["status"] == "stopped"
        assert data["initiator_pid"] == str(os.getpid())
        assert data["initiator_cmd"]
        assert data["initiator_cwd"] == os.getcwd()

    @pytest.mark.usefixtures("isolated_singleton_dirs")
    def test_terminate_writes_initiator_attribution_to_log(self) -> None:
        # Terminate a real non-python child (a python child would be confirmed
        # ours by the tokenless fallback, and CTRL_BREAK on a shared Windows
        # process group would kill the test run) and read the isolated log the
        # CLI-side shutdown line is written to.
        log_path = _log_file()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            child = subprocess.Popen(
                ["cmd.exe", "/c", "ping -n 60 127.0.0.1 >nul"],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            child = subprocess.Popen(["sleep", "60"])
        try:
            _terminate_and_confirm(child.pid)
        finally:
            child.kill()
            child.wait(timeout=10)
        content = log_path.read_text(encoding="utf-8")
        assert "reason=cli_terminate" in content
        assert f"pid={child.pid}" in content
        assert f"initiator_pid={os.getpid()}" in content
        assert "initiator_cmd=" in content
        assert f"initiator_cwd={os.getcwd()}" in content
