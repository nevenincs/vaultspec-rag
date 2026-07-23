"""CLI coverage for status commands and service state computation."""

from __future__ import annotations

import json
import os
import typing

import pytest

from ._cli_helpers import (
    EnvVar,
    _hold_local_index_lock,
    _label_values,
    _plain_lines,
    _write_service_status,
    app,
    reset_base_config,
    reset_rag_config,
    runner,
)

if typing.TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestStatusCommand:
    """Tests for the project index status command."""

    @staticmethod
    def _workspace(tmp_path: Path) -> Path:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        return tmp_path

    def test_status_human_output_uses_operator_labels(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._status import _render_status_text

        _render_status_text(
            {
                "cuda": False,
                "gpu_name": "",
                "vram_mb": 0,
                "storage_path": tmp_path / ".vault" / "data" / "search-data",
                "vault_documents": 12,
                "codebase_chunks": 34,
            },
            target=tmp_path,
            service_port=8766,
        )

        output = capsys.readouterr().out
        lines = _plain_lines(output)
        labels = _label_values(output)
        assert lines[0] == "Project index"
        assert labels["Project"] == str(tmp_path)
        assert labels["Index data"] == str(tmp_path / ".vault" / "data" / "search-data")
        assert labels["Compute"] == "CPU only (no supported GPU detected)"
        assert labels["Vault documents"] == "12"
        assert labels["Source code sections"] == "34"
        assert labels["Server"] == "running"
        assert labels["Address"] == "http://127.0.0.1:8766"
        assert lines[lines.index("Server details:") + 1] == (
            "vaultspec-rag server status --port 8766"
        )
        assert "Next action:" not in output

    def test_status_empty_index_output_is_actionable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._status import _render_status_text

        _render_status_text(
            {
                "cuda": False,
                "gpu_name": "",
                "vram_mb": 0,
                "storage_path": tmp_path / ".vault" / "data" / "search-data",
                "vault_documents": 0,
                "codebase_chunks": 0,
            },
            target=tmp_path,
            service_port=8766,
        )

        lines = _plain_lines(capsys.readouterr().out)
        next_action_index = lines.index("Next action:")
        assert lines[next_action_index + 1] == "vaultspec-rag index --type all"
        assert all("Health:" not in line for line in lines)

    def test_status_partial_index_output_names_missing_index(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._status import _render_status_text

        _render_status_text(
            {
                "cuda": False,
                "gpu_name": "",
                "vram_mb": 0,
                "storage_path": tmp_path / ".vault" / "data" / "search-data",
                "vault_documents": 3,
                "codebase_chunks": 0,
            },
            target=tmp_path,
        )

        lines = _plain_lines(capsys.readouterr().out)
        next_action_index = lines.index("Next action:")
        assert lines[next_action_index + 1] == "vaultspec-rag index --type code"

    def test_status_prefers_running_service_index_state(self, tmp_path: Path) -> None:
        import http.server
        import threading
        import urllib.parse

        root = self._workspace(tmp_path)
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        requests: list[str] = []

        class ServiceStateHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                requests.append(self.path)
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                assert parsed.path == "/service-state"
                assert query["project_root"] == [str(root)]
                response = {
                    "ok": True,
                    "index": {
                        "cuda": False,
                        "gpu_name": "",
                        "vram_mb": 0,
                        "storage_path": "http://127.0.0.1:8765",
                        "vault_documents": 7,
                        "codebase_chunks": 9,
                        "target_dir": str(root),
                    },
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), ServiceStateHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        os.environ[EnvVar.QDRANT_STORAGE_DIR] = str(tmp_path / "qdrant" / "storage")
        reset_base_config()
        reset_rag_config()
        try:
            _write_service_status(pid=os.getpid(), port=server.server_port)
            result = runner.invoke(app, ["--target", str(root), "status"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
            os.environ.pop(EnvVar.STATUS_DIR, None)
            os.environ.pop(EnvVar.QDRANT_STORAGE_DIR, None)
            reset_base_config()
            reset_rag_config()

        assert result.exit_code == 0, result.output
        assert requests == [
            "/service-state?project_root=" + urllib.parse.quote(str(root))
        ]
        labels = _label_values(result.output)
        lines = _plain_lines(result.output)
        assert lines[0] == "Project index"
        assert labels["Project"] == str(root)
        assert labels["Index data"] == "running service storage"
        assert labels["Vault documents"] == "7"
        assert labels["Source code sections"] == "9"
        assert labels["Server"] == "running"
        assert labels["Address"] == f"http://127.0.0.1:{server.server_port}"
        assert lines[lines.index("Server details:") + 1] == (
            f"vaultspec-rag server status --port {server.server_port}"
        )

    def test_status_lock_error_uses_operator_language(self, tmp_path: Path) -> None:
        root = self._workspace(tmp_path)
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        os.environ[EnvVar.QDRANT_STORAGE_DIR] = str(tmp_path / "qdrant" / "storage")
        reset_base_config()
        reset_rag_config()
        lock = _hold_local_index_lock(root)
        try:
            result = runner.invoke(app, ["--target", str(root), "status"])
        finally:
            lock.release()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            os.environ.pop(EnvVar.QDRANT_STORAGE_DIR, None)
            reset_base_config()
            reset_rag_config()

        assert result.exit_code == 1, result.output
        assert "Cannot read index status because the local index is busy" in (
            result.output
        )
        assert "vaultspec-rag server status" in result.output
        for leaked in (
            "Qdrant",
            "Local-file-backed",
            "parallel-safe",
            "exclusive.lock",
            "another process holds the lock",
        ):
            assert leaked not in result.output


class TestServiceLifecycleHelpers:
    """_port_is_listening + _heartbeat_age_seconds helpers."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_port_is_listening_true_for_open_socket(self):
        """A socket bound and listening locally is reported as listening."""
        import socket

        from ..cli import _port_is_listening

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            assert _port_is_listening(port) is True
        finally:
            sock.close()

    def test_port_is_listening_false_for_closed_port(self):
        """An unbound ephemeral port returns False without raising."""
        import socket

        from ..cli import _port_is_listening

        # Bind to find a free port, then close so it's unbound.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        assert _port_is_listening(port) is False

    def test_heartbeat_age_missing_field(self):
        """No last_heartbeat → None (caller treats as 'no data')."""
        from ..cli import _heartbeat_age_seconds

        assert _heartbeat_age_seconds({"pid": 1, "port": 2}) is None

    def test_heartbeat_age_malformed_timestamp(self):
        """Unparseable timestamp → None, no exception."""
        from ..cli import _heartbeat_age_seconds

        assert _heartbeat_age_seconds({"last_heartbeat": "not-a-date"}) is None

    def test_heartbeat_age_fresh(self):
        """Just-written heartbeat → near-zero seconds."""
        from datetime import UTC, datetime

        from ..cli import _heartbeat_age_seconds

        ts = datetime.now(UTC).isoformat(timespec="seconds")
        age = _heartbeat_age_seconds({"last_heartbeat": ts})
        assert age is not None
        assert 0 <= age < 5

    def test_heartbeat_age_stale(self):
        """Old heartbeat → seconds matching the synthesized delta."""
        from datetime import UTC, datetime, timedelta

        from ..cli import _heartbeat_age_seconds

        old = (datetime.now(UTC) - timedelta(seconds=120)).isoformat(
            timespec="seconds",
        )
        age = _heartbeat_age_seconds({"last_heartbeat": old})
        assert age is not None
        assert 115 < age < 125

    def test_heartbeat_age_naive_timestamp_assumed_utc(self):
        """Pre-3.13-style naive ISO timestamps must not crash."""
        from datetime import UTC, datetime, timedelta

        from ..cli import _heartbeat_age_seconds

        old = (
            (datetime.now(UTC) - timedelta(seconds=10))
            .replace(
                tzinfo=None,
            )
            .isoformat(timespec="seconds")
        )
        age = _heartbeat_age_seconds({"last_heartbeat": old})
        assert age is not None
        assert 8 < age < 15

    def test_service_status_stale_heartbeat_exits_4(self, tmp_path: Path):
        """File present + PID alive + heartbeat stale → exit 4."""
        from datetime import UTC, datetime, timedelta

        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=os.getpid(), port=1)  # port 1 unbound
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            # 5 minutes old: well past the 60s staleness threshold.
            data["last_heartbeat"] = (
                datetime.now(UTC) - timedelta(seconds=300)
            ).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status"])
            assert result.exit_code == 4
            # Port 1 likely yields "crashed (port silent)" first because
            # port-not-listening is checked before heartbeat staleness in
            # the State derivation. Either message is acceptable; the
            # contract being tested is the non-zero exit code.
            assert "crashed" in result.output.lower()
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_service_status_next_action_starts_stopped_service(self, tmp_path: Path):
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            result = runner.invoke(
                app,
                ["server", "status", "--port", "1", "--json"],
            )
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

        assert result.exit_code == 3
        payload = json.loads(result.output)
        next_action = payload["data"]["operational"]["next_action"]
        assert next_action == "vaultspec-rag server start --port 1"
        assert "logs" not in next_action


#: Deliberately not the machine default service port. These tests intercept the
#: health probe, and an interception that silently stopped binding would fall
#: through to a real call - which on a developer machine running the resident
#: daemon on the default port would answer with a genuine token and let the
#: assertion pass for the wrong reason. Nothing listens here, so an inert patch
#: produces the unreachable sentinel and the tests fail as they should.
_UNSERVED_PORT = 9


class TestServiceTokenIdentity:
    """Per-process service_token round-trip.

    Daemon writes a uuid4 token into service.json + returns it from
    /health. The CLI compares both - mismatch reports a recycled-PID
    or unrelated-HTTP-server scenario instead of trusting a stale
    truth-lying executable-name check.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_token_match_returns_true(self, monkeypatch: pytest.MonkeyPatch):
        from .. import cli
        from ..cli import _process

        def _probe_abc(_port: int) -> dict[str, object]:
            return {"service_token": "abc"}

        def _alive(_pid: int) -> bool:
            return True

        monkeypatch.setattr(_process, "_try_http_health", _probe_abc)
        monkeypatch.setattr(cli, "_is_pid_alive", _alive)
        assert cli._is_our_service(123, port=_UNSERVED_PORT, expected_token="abc")

    def test_token_mismatch_returns_false(self, monkeypatch: pytest.MonkeyPatch):
        from .. import cli
        from ..cli import _process

        def _probe_abc(_port: int) -> dict[str, object]:
            return {"service_token": "abc"}

        def _alive(_pid: int) -> bool:
            return True

        monkeypatch.setattr(_process, "_try_http_health", _probe_abc)
        monkeypatch.setattr(cli, "_is_pid_alive", _alive)
        # Token mismatch is authoritative - return False regardless of
        # whether the executable-name check would have passed.
        assert not cli._is_our_service(123, port=_UNSERVED_PORT, expected_token="xyz")

    def test_token_absent_in_response_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """Pre-upgrade daemon (no token in response) → exe-name fallback."""
        from .. import cli
        from ..cli import _process

        def _probe_empty(_port: int) -> dict[str, object]:
            return {}

        def _alive(_pid: int) -> bool:
            return True

        monkeypatch.setattr(_process, "_try_http_health", _probe_empty)
        monkeypatch.setattr(cli, "_is_pid_alive", _alive)
        # On Windows the exe-name check inspects the running pytest
        # process (always "python") so this hits the True branch.
        # No-swallow rule: the fallback must debug-log.
        with caplog.at_level("DEBUG", logger="vaultspec_rag.cli"):
            result = cli._is_our_service(
                os.getpid(),
                port=_UNSERVED_PORT,
                expected_token="abc",
            )
        # Result True or False is platform-dependent; the contract
        # under test is the debug log line.
        assert any(
            "service_token absent" in r.getMessage()
            for r in caplog.records
            if r.name == "vaultspec_rag.cli"
        ), "token-absent fallback must debug-log per the no-swallow rule"
        # Sanity: a result was returned (didn't raise).
        assert isinstance(result, bool)

    def test_no_token_in_status_skips_token_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No expected_token (pre-upgrade service.json) → exe-name only."""
        from .. import cli
        from ..cli import _process

        probe_called: dict[str, int] = {"n": 0}

        def _probe(_port: int) -> dict[str, str]:
            probe_called["n"] += 1
            return {"service_token": "irrelevant"}

        def _alive_stub(_pid: int) -> bool:
            return True

        monkeypatch.setattr(_process, "_try_http_health", _probe)
        monkeypatch.setattr(cli, "_is_pid_alive", _alive_stub)
        # No expected_token → don't probe.
        cli._is_our_service(os.getpid(), port=_UNSERVED_PORT, expected_token=None)
        assert probe_called["n"] == 0

    def test_health_probe_failure_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Network failure on /health → exe-name fallback, no exception."""
        from .. import cli
        from ..cli import _process

        def _probe_none(_port: int) -> None:
            return None

        def _alive_stub2(_pid: int) -> bool:
            return True

        monkeypatch.setattr(_process, "_try_http_health", _probe_none)
        monkeypatch.setattr(cli, "_is_pid_alive", _alive_stub2)
        # Should fall back without raising.
        result = cli._is_our_service(
            os.getpid(),
            port=_UNSERVED_PORT,
            expected_token="abc",
        )
        assert isinstance(result, bool)


class TestWarmingStatusState:
    """The daemon-stamped ``phase`` field turns the warmup window into a
    distinct ``warming`` state (exit 5) instead of "stopped"/"crashed".

    Pure-function coverage: the state computers and the phase reader are
    exercised directly (a live-and-ours pid cannot be faked without mocks).
    """

    def test_service_phase_reads_the_field(self):
        from ..cli._service_status import _service_phase

        assert _service_phase({"phase": "warming"}) == "warming"
        assert _service_phase({"phase": "running"}) == "running"

    def test_service_phase_absent_or_invalid_is_none(self):
        from ..cli._service_status import _service_phase

        assert _service_phase(None) is None
        assert _service_phase({}) is None
        assert _service_phase({"phase": ""}) is None
        assert _service_phase({"phase": 7}) is None

    def test_compute_state_warming_beats_port_and_heartbeat_signals(self):
        from ..cli._service_lifecycle import _compute_state

        state, label, exit_code = _compute_state(
            True, True, False, True, phase="warming"
        )
        assert state == "warming"
        assert "warming" in label
        assert exit_code == 5

    def test_compute_state_absent_phase_keeps_crashed_semantics(self):
        from ..cli._service_lifecycle import _compute_state

        state, _label, exit_code = _compute_state(True, True, False, True)
        assert state == "crashed_port_silent"
        assert exit_code == 4

    def test_compute_state_dead_pid_wins_over_warming(self):
        from ..cli._service_lifecycle import _compute_state

        state, _label, exit_code = _compute_state(
            False, False, False, True, phase="warming"
        )
        assert state == "crashed_pid_dead"
        assert exit_code == 4

    def test_explicit_port_state_warming_needs_a_live_owned_pid(self):
        from ..cli._service_lifecycle import _explicit_port_state

        warming = _explicit_port_state(
            False, None, phase="warming", pid_alive=True, pid_is_ours=True
        )
        assert warming[0] == "warming"
        assert warming[2] == 5
        dead = _explicit_port_state(
            False, None, phase="warming", pid_alive=False, pid_is_ours=False
        )
        assert dead[0] == "stopped"
        assert dead[2] == 3
        reused = _explicit_port_state(
            False, None, phase="warming", pid_alive=True, pid_is_ours=False
        )
        assert reused[0] == "stopped"
        assert reused[2] == 3

    def test_explicit_port_state_absent_phase_is_unchanged(self):
        from ..cli._service_lifecycle import _explicit_port_state

        assert _explicit_port_state(False, None)[0] == "stopped"
        assert _explicit_port_state(True, None)[0] == "unreachable"
        assert _explicit_port_state(True, {"status": "ready"})[0] == "running"

    def test_next_action_for_warming_says_retry(self):
        from ..cli._service_lifecycle import _status_next_action

        action = _status_next_action("warming", None, {})
        assert "server status" in action
        assert "retry" in action

    def test_daemon_phase_stamp_publishes_before_parent_and_survives_merge(
        self,
        tmp_path: Path,
    ):
        import json

        import vaultspec_rag.server as server_state

        from .._machine_lock import (
            acquire_machine_lock_lease,
            release_machine_lock_lease,
        )
        from ..server._lifecycle import _DiscoveryPublisher
        from ..server._lifespan import _stamp_service_phase

        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        os.environ[EnvVar.QDRANT_STORAGE_DIR] = str(tmp_path / "qdrant" / "storage")
        reset_base_config()
        reset_rag_config()
        previous_port = server_state._service_port
        previous_token = server_state._SERVICE_TOKEN
        server_state._service_port = 8766
        server_state._SERVICE_TOKEN = "phase-stamp-test-token"
        lease, holder = acquire_machine_lock_lease()
        assert lease is not None
        assert holder == os.getpid()
        publisher = _DiscoveryPublisher(lease)
        try:
            _stamp_service_phase(publisher, "warming")
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            assert data["phase"] == "warming"
            assert data["pid"] == os.getpid()
            assert data["port"] == 8766

            _write_service_status(pid=4242, port=8766)
            data = json.loads(sf.read_text(encoding="utf-8"))
            assert data["phase"] == "warming"
            assert data["pid"] == os.getpid()

            _stamp_service_phase(publisher, "running")
            data = json.loads(sf.read_text(encoding="utf-8"))
            assert data["phase"] == "running"
        finally:
            publisher.quiesce()
            publisher.cleanup()
            release_machine_lock_lease(lease)
            server_state._service_port = previous_port
            server_state._SERVICE_TOKEN = previous_token
            os.environ.pop(EnvVar.STATUS_DIR, None)
            os.environ.pop(EnvVar.QDRANT_STORAGE_DIR, None)
            reset_base_config()
            reset_rag_config()


class TestDegradedDiscoveryStatus:
    """A live singleton holder is never rendered as a stopped service.

    Exercised against a real held machine lock and a real on-disk pointer, with
    both managed singleton paths relocated under the test's own temp root.
    """

    @staticmethod
    def _isolate(tmp_path: Path) -> None:
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "status")
        os.environ[EnvVar.QDRANT_STORAGE_DIR] = str(
            tmp_path / "qdrant-server" / "storage"
        )
        (tmp_path / "status").mkdir(parents=True, exist_ok=True)
        reset_base_config()
        reset_rag_config()

    @staticmethod
    def _restore() -> None:
        from .._machine_lock import release_machine_lock

        release_machine_lock()
        os.environ.pop(EnvVar.STATUS_DIR, None)
        os.environ.pop(EnvVar.QDRANT_STORAGE_DIR, None)
        reset_base_config()
        reset_rag_config()

    def test_unheld_singleton_still_reports_stopped(self, tmp_path: Path) -> None:
        """The stopped contract is unchanged when nothing holds the singleton."""
        self._isolate(tmp_path)
        try:
            result = runner.invoke(app, ["server", "status", "--json"])
            assert result.exit_code == 3
            payload = json.loads(result.stdout)
            assert payload["data"]["state"] == "stopped"
        finally:
            self._restore()

    def test_live_holder_without_a_pointer_reports_degraded(
        self, tmp_path: Path
    ) -> None:
        """A holder that never published must not read as stopped.

        This is the case that previously rendered as an absent service: the
        status directory holds no record, so the machine singleton is the only
        evidence, and something owns it.
        """
        from .._machine_lock import acquire_machine_lock

        self._isolate(tmp_path)
        try:
            acquired, _holder = acquire_machine_lock()
            assert acquired

            result = runner.invoke(app, ["server", "status", "--json"])
            assert result.exit_code == 4, result.stdout
            payload = json.loads(result.stdout)
            data = payload["data"]
            assert data["state"] == "degraded_discovery"
            assert data["discovery"]["reason"] == "pointer_missing"
            assert data["discovery"]["holder_pid"] == os.getpid()
            # The evidence, not just a bare verdict, reaches the operator.
            assert str(os.getpid()) in data["discovery"]["evidence"]
        finally:
            self._restore()

    def test_degraded_discovery_is_visible_in_human_output(
        self, tmp_path: Path
    ) -> None:
        """The human summary names the condition rather than saying stopped."""
        from .._machine_lock import acquire_machine_lock

        self._isolate(tmp_path)
        try:
            acquired, _holder = acquire_machine_lock()
            assert acquired

            result = runner.invoke(app, ["server", "status"])
            assert result.exit_code == 4, result.stdout
            lowered = result.stdout.lower()
            assert "holds the machine singleton" in lowered
            assert "stopped" not in lowered
        finally:
            self._restore()

    def test_doctor_agrees_with_status_on_a_live_holder(self, tmp_path: Path) -> None:
        """Doctor and status must not disagree about a live holder."""
        from .._machine_lock import acquire_machine_lock

        self._isolate(tmp_path)
        try:
            acquired, _holder = acquire_machine_lock()
            assert acquired

            doctor = runner.invoke(app, ["server", "doctor", "--json"])
            # Doctor also probes installed dependencies, which can fail for
            # reasons unrelated to discovery. Surface that directly rather than
            # letting it resurface as an opaque parse error on the next line.
            assert doctor.stdout.strip(), (
                f"doctor emitted nothing; exception={doctor.exception!r}"
            )
            payload = json.loads(doctor.stdout)
            service = payload["data"]["service"]
            assert service["present"] is True
            assert service["live"] is False
            assert service["state"] == "degraded_discovery"
            assert "holds the machine singleton" in str(service["label"]).lower()
            # A daemon that is present but not live must not read ready.
            assert payload["data"]["status"] == "needs_restart"
        finally:
            self._restore()
