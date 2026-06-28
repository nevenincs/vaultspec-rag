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
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..cli._process import _service_child_env
from ..cli._service_lifecycle import (
    _existing_service_running,
    _fail_start,
    _start_success,
)
from ..config import EnvVar, reset_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

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


@pytest.fixture
def _isolated_singleton(  # pyright: ignore[reportUnusedFunction]
    tmp_path: Path,
) -> Iterator[None]:
    """Isolate the managed-singleton paths so start/lock touch only tmp.

    Sets both the status dir AND the qdrant storage dir (the machine lock lives
    beside the latter), per the managed-singleton-paths isolation rule, so the
    test never touches the operator's real service or lock.
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


class TestStartOutcomeHelpers:
    """The --json envelope contract for each start outcome (ADR D2)."""

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
        assert env["error"] == "machine_owned"
        assert env["data"] == {"holder_pid": 4242}


class TestStartReorderAndGuards:
    """The reorder (idempotent first) and the genuine guard outcomes, live."""

    @pytest.mark.usefixtures("_isolated_singleton")
    def test_no_recorded_service_is_not_running(self) -> None:
        # The isolated status dir has no service.json, so detection is None
        # (the idempotent check falls through to the guards).
        assert _existing_service_running() is None

    @pytest.mark.usefixtures("_isolated_singleton")
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

    @pytest.mark.usefixtures("_isolated_singleton")
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
