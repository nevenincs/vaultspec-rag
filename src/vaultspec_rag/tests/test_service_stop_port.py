"""``server stop --port`` targeting tests.

No mocks, no GPU: the port-resolution path is exercised against real loopback
sockets. ``server stop --port`` resolves the running instance from its /health
identity rather than the status file, so a non-default-port service whose status
file is missing or divergent is still stoppable. The terminate
path itself is covered end to end against a real daemon in the integration
suite; here the focus is the deterministic, side-effect-free resolution paths.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

import psutil
import pytest
from typer.testing import CliRunner

from .. import _process_probe as process_probe
from .._machine_lock import probe_machine_lock
from .._process_probe import pid_image_path, pid_start_time, pid_terminated
from ..cli import _process as service_process
from ..cli import _service_stop as service_stop
from ..cli import app
from ..cli._process import _is_our_service, _terminate_pid
from ..cli._service_status import _write_service_status
from ..cli._service_stop import (
    _orphan_daemon_pids,
    _service_pid_on_port,
    _stop_service_on_port,
)
from ..serviceclient._discovery import _merge_service_status, _status_file
from ._cli_helpers import (
    _CONTRACT_SERVICE_TOKEN,
    _serving,
    _status_contract_server,
)
from ._config_fixtures import reset_config
from ._ports import free_loopback_port

if TYPE_CHECKING:
    from collections.abc import Generator

#: Budget for one `server stop --orphans` subprocess. Currently measured at
#: 3.2-3.6s on a host with ~1700 processes - CLI startup, one process-table
#: sweep, and the second-long loopback identity probes - because the sweep now
#: reads a process's `ppid` only when its command line already matched. Reading
#: it for every process cost a full-system snapshot EACH on Windows and put a
#: single reap at 65-86s.
#:
#: The budget deliberately does NOT track that measurement down. It is a
#: ceiling, not a wait: a passing guard never spends it, so headroom is free,
#: while too little of it fails the guard on `TimeoutExpired` before a single
#: safety assertion runs - reporting a failure that says nothing about whether
#: the reap spares the singleton, which is the only thing these exist to check.
#: That is not hypothetical; it is why this was raised off 60s in the first
#: place. Lower it only to a figure a LOADED host can still meet.
_REAP_SUBPROCESS_BUDGET_SECONDS = 240.0

#: How long a witness daemon stays alive. It must outlive the WHOLE guard, not
#: just the reap: the guard sweeps the process table once in-process to
#: enumerate the witnesses and once more inside the out-of-process reap. When
#: each of those cost ~70s the witnesses expired MID-GUARD - every pair died of
#: old age, the reap reported `reaped: 0` because nothing was left to reap, and
#: the spare assertion passed over a singleton nothing had killed. Funding one
#: budget for the reap plus a second for the enumeration preceding it keeps the
#: reap the only thing that can end a witness, which is the premise every
#: safety assertion here rests on.
_WITNESS_LIFETIME_SECONDS = 2 * _REAP_SUBPROCESS_BUDGET_SECONDS


pytestmark = [pytest.mark.unit]

runner = CliRunner()


class TestServicePidOnPort:
    def test_free_port_resolves_to_none(self) -> None:
        assert _service_pid_on_port(free_loopback_port()) is None


class TestStopServiceOnPort:
    def test_nothing_listening_reports_not_running(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A free port has no service to stop; the call must be a clean no-op that
        # never terminates anything.
        _stop_service_on_port(free_loopback_port())
        out = capsys.readouterr().out.lower()
        assert "not running" in out


class TestStopCliPortOption:
    def test_stop_accepts_port_option_with_no_service(self) -> None:
        # The pre-fix defect was a hard `No such option '--port'`. The option
        # now exists, and stopping a free port exits 0 with "not running".
        port = free_loopback_port()
        result = runner.invoke(app, ["server", "stop", "--port", str(port)])
        assert result.exit_code == 0, result.output
        assert "no such option" not in result.output.lower()
        assert "not running" in result.output.lower()


@pytest.fixture
def isolated_stop_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path]:
    monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
    monkeypatch.setenv("VAULTSPEC_RAG_QDRANT_STORAGE_DIR", str(tmp_path / "storage"))
    reset_config()
    try:
        yield _status_file()
    finally:
        reset_config()


@contextlib.contextmanager
def _starting_process(
    arguments: list[str],
    *,
    hold_machine_lock: bool = False,
    foreign_command: bool = False,
    code_override: str | None = None,
) -> Generator[subprocess.Popen[str]]:
    """Keep a real process with the production launch witness alive, without models."""
    # Use the running interpreter image rather than its venv shim so the
    # recorded PID is the process executing the sleeper on both platforms.
    interpreter = pid_image_path(psutil.Process().pid)
    assert interpreter is not None
    module_launch = (
        arguments[:2] == ["-m", "vaultspec_rag.server"] and not foreign_command
    )
    fixture_root = tempfile.TemporaryDirectory(prefix="resident-witness-")
    module_root = _write_witness_module(Path(fixture_root.name))
    command = (
        arguments
        if module_launch
        else [
            "-c",
            code_override
            or (
                "import time; print('up', flush=True); "
                f"time.sleep({_WITNESS_LIFETIME_SECONDS})"
            ),
            *arguments,
        ]
    )
    env = _witness_environment(module_root, hold_machine_lock=hold_machine_lock)
    child = subprocess.Popen(
        [
            interpreter,
            *command,
        ],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
        creationflags=0x00000200 if sys.platform == "win32" else 0,
        start_new_session=sys.platform != "win32",
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "up"
        yield child
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)
        if child.stdout is not None:
            child.stdout.close()
        fixture_root.cleanup()


def _write_witness_module(root: Path) -> Path:
    """Create a harmless real module launch, sharing only the production lock owner."""
    package = root / "vaultspec_rag"
    package.mkdir(parents=True, exist_ok=True)
    real_package = Path(__file__).resolve().parents[1]
    (package / "__init__.py").write_text(
        f"__path__.append({str(real_package)!r})\n", encoding="utf-8"
    )
    (package / "server.py").write_text(
        "import os, time\n"
        "if os.environ.get('RESIDENT_WITNESS_HOLD_LOCK') == '1':\n"
        "    from vaultspec_rag._machine_lock import acquire_machine_lock_lease\n"
        "    lease, holder = acquire_machine_lock_lease()\n"
        "    assert lease is not None, holder\n"
        "print('up', flush=True)\n"
        f"time.sleep({_WITNESS_LIFETIME_SECONDS})\n",
        encoding="utf-8",
    )
    return root


def _witness_environment(
    root: Path, *, hold_machine_lock: bool = False
) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(root), *sys.path]),
        "RESIDENT_WITNESS_HOLD_LOCK": "1" if hold_machine_lock else "0",
    }


@pytest.fixture
def witness_module_path(tmp_path: Path) -> Path:
    return _write_witness_module(tmp_path / "witness")


def _port_stop(port: int | None) -> tuple[int, dict[str, object]]:
    arguments = ["server", "stop", "--json"]
    if port is not None:
        arguments += ["--port", str(port)]
    result = runner.invoke(app, arguments)
    payloads = [line for line in result.output.splitlines() if line.startswith("{")]
    assert len(payloads) == 1, result.output
    return result.exit_code, cast("dict[str, object]", json.loads(payloads[0]))


class TestDefaultServiceStopIdentity:
    @pytest.mark.parametrize("with_pointer", [True, False])
    def test_legacy_module_launch_stops_with_or_without_discovery(
        self, isolated_stop_status: Path, with_pointer: bool
    ) -> None:
        port = free_loopback_port()
        with _starting_process(
            ["-m", "vaultspec_rag.server", "--port", str(port)],
            hold_machine_lock=not with_pointer,
        ) as child:
            if with_pointer:
                _write_service_status(child.pid, port)
            exit_code, envelope = _port_stop(None)

            assert exit_code == 0, envelope
            assert cast("dict[str, object]", envelope["data"])["status"] == (
                "stopped" if with_pointer else "reclaimed"
            )
            assert pid_terminated(child.pid), "legacy resident was not stopped"
            assert not isolated_stop_status.exists()
            assert not probe_machine_lock().held

    @pytest.mark.parametrize("with_pointer", [True, False])
    def test_foreign_python_is_never_a_default_stop_target(
        self, isolated_stop_status: Path, with_pointer: bool
    ) -> None:
        """Mutation proved: legacy executable acceptance fails; restoration passes."""
        code = (
            "import time\n"
            "from vaultspec_rag._machine_lock import acquire_machine_lock_lease\n"
            "lease, holder = acquire_machine_lock_lease()\n"
            "assert lease is not None, holder\n"
            "print('up', flush=True)\n"
            f"time.sleep({_WITNESS_LIFETIME_SECONDS})\n"
        )
        with _starting_process(
            [], code_override=None if with_pointer else code
        ) as child:
            if with_pointer:
                _write_service_status(child.pid, free_loopback_port())
            before = isolated_stop_status.read_bytes() if with_pointer else None

            exit_code, envelope = _port_stop(None)

            assert exit_code == 1, "foreign Python was reported stopped"
            assert envelope["error"] == "identity_unconfirmed", envelope
            assert not pid_terminated(child.pid), "foreign Python was terminated"
            if with_pointer:
                assert isolated_stop_status.read_bytes() == before
            else:
                assert not isolated_stop_status.exists()
                assert probe_machine_lock().holder_pid == child.pid

    def test_an_orphan_scan_does_not_authorize_a_recycled_foreign_pid(
        self, isolated_stop_status: Path
    ) -> None:
        """Mutation proved: trusting a stale argv scan fails; restoration passes."""
        del isolated_stop_status
        with _starting_process([]) as child:
            reaped, survivors, denied = service_stop._reap_unprotected(
                {child.pid: 0}, set(), free_loopback_port()
            )

            assert reaped == [], "stale scan authorized a foreign process"
            assert survivors == [child.pid]
            assert not denied
            assert not pid_terminated(child.pid)


class TestStartingServicePortStop:
    @pytest.mark.parametrize("with_launch_token", [False, True])
    @pytest.mark.parametrize("port_form", ["separate", "equals"])
    def test_matching_startup_identity_stops_before_the_listener_opens(
        self, isolated_stop_status: Path, with_launch_token: bool, port_form: str
    ) -> None:
        port = free_loopback_port()
        arguments = ["-m", "vaultspec_rag.server", "--port", str(port)]
        if port_form == "equals":
            arguments = ["-m", "vaultspec_rag.server", f"--port={port}"]
        if with_launch_token:
            arguments += ["--launch-token", "recorded-launch"]
        with _starting_process(arguments) as child:
            _write_service_status(child.pid, port)
            fields: dict[str, object] = {"phase": "warming"}
            if with_launch_token:
                fields["launch_token"] = "recorded-launch"
            _merge_service_status(fields)
            assert _service_pid_on_port(port) is None

            exit_code, envelope = _port_stop(port)

            assert exit_code == 0, envelope
            data = cast("dict[str, object]", envelope["data"])
            assert data["status"] == "stopped", envelope
            assert data["pid"] == child.pid
            assert pid_terminated(child.pid), "matching starting daemon was not stopped"
            assert not isolated_stop_status.exists()

    def test_other_port_does_not_target_the_recorded_starting_daemon(
        self, isolated_stop_status: Path
    ) -> None:
        """Mutation proved: accepting another port fails; restoration passes."""
        port = free_loopback_port()
        other_port = free_loopback_port()
        assert other_port != port
        with _starting_process(
            ["-m", "vaultspec_rag.server", "--port", str(port)]
        ) as child:
            _write_service_status(child.pid, port)
            before = isolated_stop_status.read_bytes()

            exit_code, envelope = _port_stop(other_port)

            assert exit_code == 0, "another port's discovery was adopted"
            assert (
                cast("dict[str, object]", envelope["data"])["status"]
                == "already_stopped"
            )
            assert not pid_terminated(child.pid), "other-port daemon was targeted"
            assert isolated_stop_status.read_bytes() == before

    @pytest.mark.parametrize(
        "kind",
        [
            "foreign_python",
            "wrong_port",
            "wrong_token",
            "stdio",
            "argv_text",
            "trailing_marker",
            "duplicate_port",
            "duplicate_nonce",
        ],
    )
    def test_unconfirmed_live_pid_is_refused_and_discovery_retained(
        self, isolated_stop_status: Path, kind: str
    ) -> None:
        """Mutation proved: bypassing launch checks fails; restoration passes."""
        port = free_loopback_port()
        arguments = [
            "-m",
            "vaultspec_rag.server",
            "--port",
            str(port),
            "--launch-token",
            "recorded-launch",
        ]
        if kind == "foreign_python":
            arguments = []
        elif kind == "wrong_port":
            arguments[3] = str(port + 1)
        elif kind == "wrong_token":
            arguments[-1] = "different-launch"
        elif kind == "stdio":
            arguments = ["-m", "vaultspec_rag.server"]
        elif kind == "argv_text":
            arguments = ["-m vaultspec_rag.server --port " + str(port)]
        elif kind == "duplicate_port":
            arguments += ["--port", str(port + 1)]
        elif kind == "duplicate_nonce":
            arguments += ["--launch-token", "different-launch"]
        with _starting_process(
            arguments, foreign_command=kind == "trailing_marker"
        ) as child:
            _write_service_status(child.pid, port)
            _merge_service_status(
                {"phase": "warming", "launch_token": "recorded-launch"}
            )
            before = isolated_stop_status.read_bytes()

            exit_code, envelope = _port_stop(port)

            assert exit_code == 1, "unconfirmed PID was reported stopped"
            assert envelope["error"] == "identity_unconfirmed", envelope
            assert not pid_terminated(child.pid), "unconfirmed process was terminated"
            assert isolated_stop_status.read_bytes() == before, (
                "live discovery was erased"
            )

    def test_dead_matching_pointer_is_cleaned_without_a_termination(
        self, isolated_stop_status: Path
    ) -> None:
        port = free_loopback_port()
        with _starting_process([]) as child:
            pid = child.pid
        assert pid_terminated(pid)
        _write_service_status(pid, port)

        exit_code, envelope = _port_stop(port)

        assert exit_code == 0, envelope
        assert cast("dict[str, object]", envelope["data"])["status"] == "cleaned"
        assert not isolated_stop_status.exists()

    def test_unknown_process_birth_does_not_authorize_termination(
        self, isolated_stop_status: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutation proved: ignoring an unknown OS birth fails; restoration passes."""
        port = free_loopback_port()
        with _starting_process(
            ["-m", "vaultspec_rag.server", "--port", str(port)]
        ) as child:
            _write_service_status(child.pid, port)
            before = isolated_stop_status.read_bytes()

            def unknown_birth(_pid: int, *, timeout: float | None = None) -> float:
                del timeout
                return 0.0

            monkeypatch.setattr(service_stop, "pid_start_time", unknown_birth)

            exit_code, envelope = _port_stop(port)

            assert exit_code == 1
            assert envelope["error"] == "identity_unconfirmed", (
                "unknown OS birth was accepted"
            )
            assert not pid_terminated(child.pid)
            assert isolated_stop_status.read_bytes() == before

    def test_machine_holder_is_stopped_before_status_publication(
        self, isolated_stop_status: Path
    ) -> None:
        port = free_loopback_port()
        with _starting_process(
            ["-m", "vaultspec_rag.server", "--port", str(port)],
            hold_machine_lock=True,
        ) as child:
            assert probe_machine_lock().holder_pid == child.pid
            assert not isolated_stop_status.exists()
            assert _service_pid_on_port(port) is None

            exit_code, envelope = _port_stop(port)

            assert exit_code == 0, envelope
            assert cast("dict[str, object]", envelope["data"])["status"] == "stopped"
            assert pid_terminated(child.pid), "starting machine holder was not stopped"
            assert not probe_machine_lock().held

    @pytest.mark.parametrize("stale_record", ["dead_launcher", "other_port"])
    def test_machine_holder_is_resolved_past_stale_discovery(
        self, isolated_stop_status: Path, stale_record: str
    ) -> None:
        port = free_loopback_port()
        _write_service_status(
            99_999_999, port if stale_record == "dead_launcher" else port + 1
        )
        before = isolated_stop_status.read_bytes()
        with _starting_process(
            ["-m", "vaultspec_rag.server", "--port", str(port)],
            hold_machine_lock=True,
        ) as child:
            exit_code, envelope = _port_stop(port)

            assert exit_code == 0, envelope
            assert cast("dict[str, object]", envelope["data"])["status"] == "stopped", (
                "stale discovery hid the starting owner"
            )
            assert pid_terminated(child.pid)
            assert not probe_machine_lock().held
            assert isolated_stop_status.read_bytes() == before

    @pytest.mark.parametrize(
        "target_mode", ["warming", "serving", "default", "reclaim"]
    )
    def test_pid_reuse_during_identity_inspection_does_not_authorize_a_stop(
        self,
        isolated_stop_status: Path,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        target_mode: str,
    ) -> None:
        """Mutation proved: dropping the birth bracket fails; restoration passes."""
        health: dict[str, object] = {"pid": None}
        with contextlib.ExitStack() as stack:
            port = (
                stack.enter_context(
                    _serving(_status_contract_server(tmp_path, health=health))
                )
                if target_mode == "serving"
                else free_loopback_port()
            )
            child = stack.enter_context(
                _starting_process(
                    ["-m", "vaultspec_rag.server", "--port", str(port)],
                    hold_machine_lock=target_mode == "reclaim",
                )
            )
            health["pid"] = child.pid
            if target_mode != "reclaim":
                _write_service_status(child.pid, port)
            before = (
                isolated_stop_status.read_bytes() if target_mode != "reclaim" else None
            )
            original_birth = pid_start_time(child.pid)
            reads = 0

            def observed_birth(_pid: int, *, timeout: float | None = None) -> float:
                del timeout
                nonlocal reads
                reads += 1
                return original_birth if reads == 1 else original_birth + 60.0

            monkeypatch.setattr(service_stop, "pid_start_time", observed_birth)
            monkeypatch.setattr(process_probe, "pid_start_time", observed_birth)

            exit_code, envelope = _port_stop(
                None if target_mode in {"default", "reclaim"} else port
            )

            assert exit_code == 1
            assert envelope["error"] == "identity_unconfirmed", (
                "reused PID crossed identity inspection"
            )
            assert not pid_terminated(child.pid)
            if target_mode != "reclaim":
                assert isolated_stop_status.read_bytes() == before
            else:
                assert not isolated_stop_status.exists()
                assert probe_machine_lock().holder_pid == child.pid

    @pytest.mark.parametrize("with_pid", [True, False])
    def test_foreign_python_health_without_a_token_is_refused(
        self, isolated_stop_status: Path, with_pid: bool
    ) -> None:
        """Mutation proved: using executable identity for tokenless health fails."""
        port = free_loopback_port()
        reported_pid_expression = "os.getpid()" if with_pid else "None"
        code = (
            "import os, json\n"
            "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
            "class Handler(BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        self.send_response(200); self.end_headers()\n"
            f"        payload = {{'pid': {reported_pid_expression}}}\n"
            "        payload['status'] = 'ready'\n"
            "        self.wfile.write(json.dumps(payload).encode())\n"
            "    def log_message(self, *args): pass\n"
            f"server = HTTPServer(('127.0.0.1', {port}), Handler)\n"
            "print('up', flush=True)\nserver.serve_forever()\n"
        )
        with _starting_process([], code_override=code) as child:
            if with_pid:
                _write_service_status(child.pid, port)
            before = isolated_stop_status.read_bytes() if with_pid else None

            exit_code, envelope = _port_stop(port)

            assert exit_code == 1, "tokenless foreign listener was reported stopped"
            expected_error = (
                "identity_unconfirmed" if with_pid else "port_holder_unconfirmed"
            )
            assert envelope["error"] == expected_error
            assert not pid_terminated(child.pid)
            if with_pid:
                assert isolated_stop_status.read_bytes() == before
            else:
                assert not isolated_stop_status.exists()

    def test_machine_holder_on_another_port_is_preserved(
        self, isolated_stop_status: Path
    ) -> None:
        """Mutation proved: ignoring the requested port fails; restoration passes."""
        port = free_loopback_port()
        with _starting_process(
            ["-m", "vaultspec_rag.server", "--port", str(port)],
            hold_machine_lock=True,
        ) as child:
            exit_code, envelope = _port_stop(port + 1)

            assert exit_code == 1, "another-port machine holder was adopted"
            assert envelope["error"] == "identity_unconfirmed"
            assert not pid_terminated(child.pid), (
                "another-port machine holder was stopped"
            )
            assert probe_machine_lock().holder_pid == child.pid
            assert not isolated_stop_status.exists()

    def test_unnamed_machine_holder_is_not_reported_stopped(
        self, isolated_stop_status: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutation proved: treating the unnamed held lock as absent fails."""
        from .. import _machine_lock as machine_lock

        def unnamed_holder() -> machine_lock.MachineLockProbe:
            return machine_lock.MachineLockProbe(held=True, holder_pid=0)

        monkeypatch.setattr(machine_lock, "probe_machine_lock", unnamed_holder)
        exit_code, envelope = _port_stop(free_loopback_port())

        assert exit_code == 1, "held unknown owner was reported stopped"
        assert envelope["error"] == "machine_holder_unnamed"
        assert not isolated_stop_status.exists()


def test_termination_refuses_a_different_process_birth(
    isolated_stop_status: Path,
) -> None:
    """Mutation proved: removing the birth fence fails; restoration passes."""
    with _starting_process([]) as child:
        witnessed = pid_start_time(child.pid)
        assert witnessed > 0.0

        result = _terminate_pid(
            child.pid,
            timeout=2.0,
            console_group_signal=False,
            expected_start_time=witnessed - 60.0,
        )

        assert result.alive, "different process incarnation was reported stopped"
        assert not pid_terminated(child.pid), (
            "recycled process incarnation was signalled"
        )
    assert not isolated_stop_status.exists()


def test_strict_launch_witness_refuses_an_unreadable_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation proved: accepting unknown argv fails; restoration passes."""
    port = free_loopback_port()
    with _starting_process(
        ["-m", "vaultspec_rag.server", "--port", str(port)]
    ) as child:

        def unknown_argv(
            _pid: int, *, timeout: float | None = None
        ) -> list[str] | None:
            del timeout
            return None

        monkeypatch.setattr(service_process, "pid_argv", unknown_argv)
        assert not _is_our_service(child.pid, port=port, require_launch_witness=True), (
            "unknown argv authorized the startup stop"
        )


@pytest.mark.parametrize("reported_pid", ["same", "different", "missing", "boolean"])
def test_health_token_identity_is_bound_to_its_serving_pid(
    isolated_stop_status: Path, reported_pid: str, tmp_path: Path
) -> None:
    """Mutation proved: dropping health PID binding fails; restoration passes."""
    with _starting_process([]) as child:
        health_pid: object = child.pid
        if reported_pid == "different":
            health_pid = psutil.Process().pid
        elif reported_pid == "missing":
            health_pid = None
        elif reported_pid == "boolean":
            health_pid = True
        with _serving(
            _status_contract_server(tmp_path, health={"pid": health_pid})
        ) as port:
            confirmed = _is_our_service(
                child.pid, port=port, expected_token=_CONTRACT_SERVICE_TOKEN
            )

            assert confirmed is (reported_pid == "same"), (
                "health token adopted a different PID"
            )
            assert not pid_terminated(child.pid)
    assert not isolated_stop_status.exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["python", "-c", "pass", "-m", "vaultspec_rag.server", "--port", "8766"],
        ["python", "foreign.py", "-m", "vaultspec_rag.server", "--port", "8766"],
        ["python", "-m", "foreign", "-m", "vaultspec_rag.server", "--port", "8766"],
        ["python", "--", "-m", "vaultspec_rag.server", "--port", "8766"],
    ],
)
def test_launch_marker_in_foreign_application_data_is_not_a_server(
    arguments: list[str],
) -> None:
    """Mutation proved: subsequence launch matching fails; restoration passes."""
    assert not process_probe.is_server_launch(arguments), (
        "foreign application data became a server launch"
    )
    assert process_probe.server_launch_port(arguments) is None


@pytest.mark.parametrize(
    "arguments, expected",
    [
        (
            ["python", "-I", "-X", "utf8", "-m", "vaultspec_rag.server", "--port=8766"],
            8766,
        ),
        (
            ["python", "-m", "vaultspec_rag.server", "--port", "8766", "--port=8767"],
            None,
        ),
        (["python", "-m", "vaultspec_rag.server", "--", "--port", "8766"], None),
        (["python", "-X", "--port=8766", "-m", "vaultspec_rag.server"], None),
    ],
)
def test_launch_port_comes_from_unambiguous_application_arguments(
    arguments: list[str], expected: int | None
) -> None:
    """Mutation proved: scanning interpreter or duplicate options fails."""
    assert process_probe.server_launch_port(arguments) == expected, (
        "ambiguous or interpreter data selected the launch port"
    )


def _spawn_witness_daemon(port: int, module_root: Path) -> subprocess.Popen[bytes]:
    """Spawn a harmless fixture through the actual resident module execution mode.

    The isolated module sleeps without loading models. Spawned in its own process
    group / session (as the real detached daemon is) so the reap's group-scoped
    termination signal cannot cascade back to this test process.
    """
    argv = [
        sys.executable,
        "-m",
        "vaultspec_rag.server",
        "--port",
        str(port),
    ]
    if sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP (0x00000200): isolate the CTRL_BREAK group.
        return subprocess.Popen(
            argv, creationflags=0x00000200, env=_witness_environment(module_root)
        )
    return subprocess.Popen(
        argv, start_new_session=True, env=_witness_environment(module_root)
    )


# A Windows venv launcher shim re-execs the real interpreter, so each spawned
# `-m vaultspec_rag.server` witness enumerates as a launcher+worker PAIR; on
# POSIX the module process is a single enumerable process with no such child. The
# reap must spare the singleton and reap the orphan under BOTH process models,
# so the expected witness count per daemon is platform-conditional.
_PROCS_PER_DAEMON = 2 if sys.platform == "win32" else 1


def _descendants(launchers: list[int]) -> set[int]:
    """Return every live launcher in *launchers* plus its spawned children."""
    live: set[int] = set()
    for pid in launchers:
        try:
            process = psutil.Process(pid)
            live.add(pid)
            live.update(child.pid for child in process.children(recursive=True))
        except psutil.Error:
            continue
    return live


def _wait_for_matched(port: int, launchers: list[int], count: int) -> dict[int, int]:
    """Wait until at least *count* witness processes enumerate for *port*.

    The production enumerator is what the count is taken from - it is the thing
    whose visibility of the witnesses this wait exists to establish - but it is
    asked only once the witnesses are known to be up. It reads the command line
    of EVERY process on the machine, so polling on it spends a full-table sweep
    per tick, and a spawn slowed by a loaded host is then paid for at roughly a
    second and a half a look. That put the ceiling of this wait alone near the
    suite's whole per-test timeout while the answer it waits for is a fact
    about two child processes.

    So the tick runs on the launchers' own descendants, which costs a handle
    per known pid and nothing per stranger, and the sweep is reached only when
    there is something for it to find.
    """
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline and len(_descendants(launchers)) < count:
        time.sleep(0.05)

    matched: dict[int, int] = {}
    # A process can be spawned a moment before its command line is readable,
    # so the authoritative sweep still gets its own (small) retry budget.
    for _ in range(10):
        matched = _orphan_daemon_pids(port)
        if len(matched) >= count:
            return matched
        time.sleep(0.1)
    msg = f"only {len(matched)} of {count} witness processes enumerated on {port}"
    raise AssertionError(msg)


def _kill_witnesses(procs: list[subprocess.Popen[bytes]]) -> None:
    """Kill every witness launcher and the worker child its shim spawned.

    Killing a launcher leaves its worker running, so the stragglers have to be
    collected before the launchers die. Reading them off the launchers costs a
    handle each; sweeping the process table for them costs a command-line read
    of every process on the machine, once per port, purely to rediscover pids
    descended from processes this test spawned itself.

    A witness that neither route reaches still expires on its own: the sleeper
    is spawned with a bounded lifetime, which is the backstop this relies on.
    """
    stragglers: set[int] = set()
    for proc in procs:
        stragglers.update(_descendants([proc.pid]) - {proc.pid})
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    for pid in stragglers:
        with contextlib.suppress(Exception):
            psutil.Process(pid).kill()


def _pair_of(launcher_pid: int, matched: dict[int, int]) -> set[int]:
    """Return a launcher pid plus its matched worker children (the daemon pair)."""
    return {launcher_pid} | {
        pid for pid, ppid in matched.items() if ppid == launcher_pid
    }


def _await_all_terminated(pids: set[int]) -> None:
    for _ in range(100):
        if all(pid_terminated(pid) for pid in pids):
            return
        time.sleep(0.1)


def _reap_via_subprocess(port: int) -> dict[str, object]:
    """Run ``server stop --orphans`` as a SEPARATE process and return its envelope.

    The reap must run out-of-process: the witness daemons here are children of
    the test process, so an in-process reap would let ``os.getpid()`` protect
    them as its own children - a confound absent in production, where the reap is
    a separate CLI process that is not the daemons' parent. Out-of-process, the
    singleton is spared only by the pointer/lineage anchors, exactly as in
    production, so the safety assertion binds.
    """
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "vaultspec_rag",
            "server",
            "stop",
            "--orphans",
            "--port",
            str(port),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=_REAP_SUBPROCESS_BUDGET_SECONDS,
        check=False,
    )
    for line in reversed(completed.stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{"):
            return cast("dict[str, object]", json.loads(stripped))
    msg = f"reap subprocess emitted no JSON envelope: {completed.stdout!r}"
    raise AssertionError(msg)


def _reaped_pids(envelope: dict[str, object]) -> set[int]:
    """Return the pids the reap claims to have terminated, per its envelope."""
    data = envelope.get("data")
    if not isinstance(data, dict):
        msg = f"reap envelope carried no data mapping: {envelope!r}"
        raise AssertionError(msg)
    raw = cast("dict[str, object]", data).get("reaped_pids")
    if not isinstance(raw, list):
        msg = f"reap envelope carried no reaped_pids list: {envelope!r}"
        raise AssertionError(msg)
    return {int(cast("int", pid)) for pid in cast("list[object]", raw)}


def _spawn_lock_holding_daemon(port: int, module_root: Path) -> subprocess.Popen[bytes]:
    """Spawn a witness that HOLDS the machine lock, publishing no pointer.

    Models the singleton in the no-pointer recovery scenario the reap must
    tolerate: the resident daemon holds the machine-lock lease (so it is the
    reap's ``probe_machine_lock`` anchor) but wrote no service-status
    pointer, so the lock anchor is the ONLY thing sparing it. The lease-acquire
    runs in the worker the shim spawns, so the worker's pid is recorded in the
    lock file and the actual module launch keeps the whole pair enumerable.
    """
    argv = [
        sys.executable,
        "-m",
        "vaultspec_rag.server",
        "--port",
        str(port),
    ]
    if sys.platform == "win32":
        return subprocess.Popen(
            argv,
            creationflags=0x00000200,
            env=_witness_environment(module_root, hold_machine_lock=True),
        )
    return subprocess.Popen(
        argv,
        start_new_session=True,
        env=_witness_environment(module_root, hold_machine_lock=True),
    )


def _wait_for_lock_holder(candidates: set[int]) -> int:
    """Wait until the machine lock is held by a pid in *candidates*; return it."""
    for _ in range(100):
        holder = probe_machine_lock().holder_pid
        if holder in candidates:
            return holder
        time.sleep(0.1)
    msg = f"no candidate in {candidates} acquired the machine lock"
    raise AssertionError(msg)


class TestOrphanReapSafety:
    """``server stop --orphans`` must spare the singleton pair and foreign daemons.

    A venv shim makes each witness spawn a launcher+worker PAIR, so the invariant
    is proven against real pairs on isolated dirs and a unique port: the whole
    singleton pair (pointer plus shim) is spared, the whole orphan pair is reaped,
    and a daemon on a different port is never enumerated.
    """

    def test_reap_spares_singleton_pair_and_reaps_the_orphan_pair(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        witness_module_path: Path,
    ) -> None:
        monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
        monkeypatch.setenv(
            "VAULTSPEC_RAG_QDRANT_STORAGE_DIR", str(tmp_path / "qdrant" / "storage")
        )
        reset_config()

        port = free_loopback_port()
        foreign_port = free_loopback_port()
        procs: list[subprocess.Popen[bytes]] = []
        try:
            singleton = _spawn_witness_daemon(port, witness_module_path)
            orphan = _spawn_witness_daemon(port, witness_module_path)
            foreign = _spawn_witness_daemon(foreign_port, witness_module_path)
            procs = [singleton, orphan, foreign]

            # Each witness spawn is a shim launcher + worker pair; wait for both.
            matched = _wait_for_matched(
                port, [singleton.pid, orphan.pid], count=2 * _PROCS_PER_DAEMON
            )
            singleton_pair = _pair_of(singleton.pid, matched)
            orphan_pair = _pair_of(orphan.pid, matched)

            # The singleton launcher is the recorded discovery-pointer pid.
            _write_service_status(singleton.pid, port)
            envelope = _reap_via_subprocess(port)
            assert envelope["ok"] is True, envelope

            # Attribute the deaths to the REAP before reading liveness. A
            # witness that outran its own lifetime is terminated too, so a
            # gone-pid assertion alone once passed over a guard in which the
            # reap had killed nothing at all - it reported `reaped: 0` while
            # every pair, the out-of-scope foreign daemon included, had expired.
            # Requiring the reap to NAME the pids it ended, and to name nothing
            # outside the orphan pair, is what makes the sparing assertions below
            # evidence about the reaper rather than about the clock.
            claimed = _reaped_pids(envelope)
            assert claimed and claimed <= orphan_pair, (
                f"the reap must name the orphans it ended and nothing else: "
                f"reaped {claimed}, orphan pair {orphan_pair}"
            )

            _await_all_terminated(orphan_pair)
            assert all(pid_terminated(pid) for pid in orphan_pair), (
                f"the whole orphan pair {orphan_pair} must be reaped"
            )
            assert all(not pid_terminated(pid) for pid in singleton_pair), (
                f"the singleton pair {singleton_pair} (pointer plus shim) "
                "must be spared"
            )
            assert not pid_terminated(foreign.pid), (
                "a daemon launched for a different port must be spared"
            )
        finally:
            reset_config()
            _kill_witnesses(procs)

    def test_reap_spares_singleton_pair_when_worker_is_the_pointer(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        witness_module_path: Path,
    ) -> None:
        # Production publishes the WORKER (the child that runs the lifespan) as
        # the pointer, not the launcher, exercising the protect-parent branch so
        # the singleton's shim launcher is spared when its worker is anchored.
        monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
        monkeypatch.setenv(
            "VAULTSPEC_RAG_QDRANT_STORAGE_DIR", str(tmp_path / "qdrant" / "storage")
        )
        reset_config()

        port = free_loopback_port()
        procs: list[subprocess.Popen[bytes]] = []
        try:
            singleton = _spawn_witness_daemon(port, witness_module_path)
            orphan = _spawn_witness_daemon(port, witness_module_path)
            procs = [singleton, orphan]
            matched = _wait_for_matched(
                port, [singleton.pid, orphan.pid], count=2 * _PROCS_PER_DAEMON
            )
            singleton_pair = _pair_of(singleton.pid, matched)
            orphan_pair = _pair_of(orphan.pid, matched)
            workers = singleton_pair - {singleton.pid}
            if sys.platform == "win32":
                # The shim spawns a distinct worker child; anchoring on it
                # exercises the protect-parent branch that spares the launcher.
                assert workers, "singleton launcher must have a matched worker child"
            # On POSIX the single process IS the lifespan-running worker.
            worker_pid = next(iter(workers)) if workers else singleton.pid

            # Anchor on the WORKER, as the production daemon does.
            _write_service_status(worker_pid, port)
            envelope = _reap_via_subprocess(port)
            assert envelope["ok"] is True, envelope

            _await_all_terminated(orphan_pair)
            assert all(pid_terminated(pid) for pid in orphan_pair), (
                f"the whole orphan pair {orphan_pair} must be reaped"
            )
            assert all(not pid_terminated(pid) for pid in singleton_pair), (
                f"the singleton pair {singleton_pair} (worker + shim launcher) "
                "must be spared"
            )
        finally:
            reset_config()
            _kill_witnesses(procs)

    def test_reap_spares_the_lock_holding_singleton_without_a_pointer(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        witness_module_path: Path,
    ) -> None:
        # The no-pointer recovery scenario the ADR targets: the singleton holds
        # the machine lock but published NO service-status pointer, so the lock
        # anchor is the only thing sparing it. Proves probe_machine_lock
        # feeds the reap's anchor set, distinct from the pointer-anchored cases.
        monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
        monkeypatch.setenv(
            "VAULTSPEC_RAG_QDRANT_STORAGE_DIR", str(tmp_path / "qdrant" / "storage")
        )
        reset_config()

        port = free_loopback_port()
        procs: list[subprocess.Popen[bytes]] = []
        try:
            singleton = _spawn_lock_holding_daemon(port, witness_module_path)
            orphan = _spawn_witness_daemon(port, witness_module_path)
            procs = [singleton, orphan]
            matched = _wait_for_matched(
                port, [singleton.pid, orphan.pid], count=2 * _PROCS_PER_DAEMON
            )
            singleton_pair = _pair_of(singleton.pid, matched)
            orphan_pair = _pair_of(orphan.pid, matched)

            # The lease holder is the singleton's worker; wait until it holds.
            holder = _wait_for_lock_holder(singleton_pair)
            assert holder in singleton_pair, (holder, singleton_pair)

            # No pointer written - only the machine-lock anchor protects.
            envelope = _reap_via_subprocess(port)
            assert envelope["ok"] is True, envelope

            _await_all_terminated(orphan_pair)
            assert all(pid_terminated(pid) for pid in orphan_pair), (
                f"the whole orphan pair {orphan_pair} must be reaped"
            )
            assert all(not pid_terminated(pid) for pid in singleton_pair), (
                f"the lock-holding singleton pair {singleton_pair} must be "
                "spared by the machine-lock anchor alone"
            )
        finally:
            reset_config()
            _kill_witnesses(procs)
