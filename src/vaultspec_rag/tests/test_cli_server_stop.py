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

from ..cli import TerminationResult, _log_file, app
from ..cli import _service_stop as _service_stop_module
from ..cli._service_stop import (
    _fail_still_running,
    _fail_stop,
    _initiator_fields,
    _stop_success,
    _terminate_and_confirm,
    still_running_remediation_for,
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


class TestStopThatDidNotStop:
    """A stop that leaves the service running is a failure, not a success.

    The regression: ``_terminate_pid`` wrapped every ``os.kill`` in a blanket
    ``suppress(OSError)`` and returned ``None``, so a ``PermissionError`` from a
    daemon launched at a privilege the terminal could not signal was
    indistinguishable from a successful kill. ``_terminate_and_confirm`` never
    confirmed, ``service_stop`` deleted the discovery file and printed "Service
    stopped" with exit 0, and the next ``server start`` failed on a port held by
    a service the operator had just been told was stopped - with no discovery
    record left to retry against.

    Like ``orphan_reap_incomplete`` above, the denied-kill shape cannot be
    staged live (it needs a process this test run has no permission to signal,
    and manufacturing one requires elevation), so the envelope is pinned at the
    helper and the call-site contract is pinned structurally.
    """

    def test_permission_denied_envelope(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import typer

        exc = _fail_still_running(
            True,
            pid=4242,
            result=TerminationResult(alive=True, signal_denied=True),
            port=8766,
        )
        assert isinstance(exc, typer.Exit)
        assert exc.exit_code == 1
        env = json.loads(capsys.readouterr().out)
        assert env["ok"] is False
        assert env["command"] == "service.stop"
        # A refused kill and a stubborn one need different operator actions, so
        # they are different error codes rather than one "stop failed".
        assert env["error"] == "terminate_permission_denied"
        assert env["data"] == {"pid": 4242, "signal_denied": True, "port": 8766}

    def test_timeout_envelope_is_a_distinct_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exc = _fail_still_running(
            True, pid=4242, result=TerminationResult(alive=True, signal_denied=False)
        )
        assert exc.exit_code == 1
        env = json.loads(capsys.readouterr().out)
        assert env["error"] == "terminate_timeout"
        assert env["data"] == {"pid": 4242, "signal_denied": False}

    def test_human_mode_exits_one_and_names_the_remedy(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exc = _fail_still_running(
            False, pid=4242, result=TerminationResult(alive=True, signal_denied=True)
        )
        assert exc.exit_code == 1
        out = capsys.readouterr().out
        # Human mode must not leak an envelope, and must say the record was
        # kept: an operator who reads "stopped" and finds no record has no
        # pid to retry against.
        assert '"ok"' not in out
        assert "still running" in out.lower()
        assert "left in place" in out.lower()
        # A refused kill is not waited out; only a privilege change fixes it.
        assert "elevated" in out.lower()

    @pytest.mark.usefixtures("isolated_singleton_dirs")
    def test_terminate_pid_reports_a_child_it_really_killed(self) -> None:
        # The success direction against a real process: a child this test may
        # signal must come back alive=False with no denial recorded.
        from ..cli import _is_pid_alive, _terminate_pid

        if sys.platform == "win32":
            child = subprocess.Popen(
                ["cmd.exe", "/c", "ping -n 60 127.0.0.1 >nul"],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            child = subprocess.Popen(["sleep", "60"])
        try:
            result = _terminate_pid(child.pid, timeout=15.0)
            assert result.alive is False, "a killed child must not report alive"
            assert result.signal_denied is False, (
                "a child this process may signal must record no denial"
            )
            assert not _is_pid_alive(child.pid)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)

    def test_dead_pid_is_not_reported_as_a_permission_denial(self) -> None:
        # "Already gone" and "not allowed to touch it" both used to vanish into
        # the same suppress(). They mean opposite things: one resolves as
        # success, the other is the fault this class exists for.
        #
        # Which except-branch carries "gone" is platform-specific, so this
        # asserts the OUTCOME rather than the branch: POSIX raises
        # ProcessLookupError, while Windows os.kill goes through
        # TerminateProcess and raises a bare OSError (WinError 87,
        # ERROR_INVALID_PARAMETER). Only the generic branch is reachable here,
        # and that is the branch a mutation must break to falsify this.
        import signal as signal_module

        from .._process_probe import send_signal

        assert send_signal(99999999, signal_module.SIGTERM) is False, (
            "an absent pid is gone, not a privilege problem"
        )

    def test_no_call_site_discards_the_termination_outcome(self) -> None:
        # The structural guard on the actual regression. The old code called
        # _terminate_and_confirm as a bare statement and threw the outcome
        # away; every caller must now branch on it, so a bare-expression call
        # is the defect returning and fails here rather than in production.
        import ast
        from pathlib import Path

        source = Path(_service_stop_module.__file__).read_text(encoding="utf-8")
        discarded = [
            node.lineno
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_terminate_and_confirm"
        ]
        assert not discarded, (
            f"_terminate_and_confirm outcome discarded at line(s) {discarded}; "
            "every call site must branch on result.alive"
        )

    @pytest.mark.parametrize(
        ("platform", "expected"),
        [
            ("win32", "elevated (administrator) terminal"),
            ("linux", "user that started the service"),
            ("darwin", "user that started the service"),
        ],
    )
    def test_remediation_is_correct_on_every_platform(
        self, platform: str, expected: str
    ) -> None:
        # Both branches are statable on either kind of host, so neither goes
        # unverified just because CI runs on one of them. A Windows operator
        # needs elevation; a POSIX one needs the owning user or sudo, and
        # telling either the other one's remedy sends them nowhere.
        lines = still_running_remediation_for(platform)
        assert lines, "a refused stop must always name a next action"
        assert expected in " ".join(lines).lower()

    def test_an_ordinary_process_gets_no_unreachable_owner_claim(self) -> None:
        # The detail asserts something strong - "another account, or session
        # 0" - so a false positive would misdiagnose every ordinary refused
        # kill and send the operator chasing a privilege boundary that is not
        # there. A process this one can plainly open must produce nothing.
        import os

        from ..cli._service_stop import _unreachable_owner_detail

        assert _unreachable_owner_detail(os.getpid()) == ""

    def test_remediation_never_offers_the_originating_console(self) -> None:
        # Permission to signal is carried by the access token, not by the
        # console, so "re-run from the terminal the service was started in"
        # names a place that cannot change the outcome - and is flatly
        # unreachable when the daemon runs under another account or in
        # session 0. Restoring that clause is the regression this catches.
        for platform in ("win32", "linux", "darwin"):
            text = " ".join(still_running_remediation_for(platform)).lower()
            assert "terminal the service was started in" not in text
            assert "shell the service was started in" not in text
