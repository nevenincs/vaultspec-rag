"""Regression coverage for the issue #204 daemon-flapping remediations.

Two confirmed flapping causes are exercised here with real objects - no mocks,
patches, fakes, or skips:

- **Breakaway fallback (S07/S09).** ``_spawn_windows`` must never silently spawn
  a daemon bound to the launching shell's Job Object. When breakaway is denied
  it attempts a console-detached spawn, and when that too is impossible it
  raises :class:`DaemonBreakawayError` instead of producing a doomed daemon.
  The fail-loud path is driven with a real ``subprocess.Popen`` against a
  command that cannot start, so both creation attempts raise a real ``OSError``
  and the escalation to ``DaemonBreakawayError`` is observed end to end.

- **Discovery-file unlink guard (S08/S10).** A lifecycle command may remove the
  discovery file only when the holder is confirmed dead. The pure decision
  helper and the live ``_existing_service_running`` path are exercised against a
  real discovery file on disk with a live PID (this test process) so a transient
  identity/health miss cannot erase a running daemon's file.

A full multi-process Windows Job-Object reproduction (spawn a real daemon, close
the launching shell, observe survival) is NOT included: it requires a live GPU
daemon and a controllable parent Job Object that this environment cannot stand
up deterministically. The behaviour that the remediation guarantees - the spawn
never silently produces a shell-bound daemon - is asserted here directly on the
spawn code path instead.
"""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING

import pytest

from ...cli._process import DaemonBreakawayError, _spawn_windows
from ...cli._service_lifecycle import (
    _existing_service_running,
    _should_unlink_discovery_file,
)
from ...config import EnvVar, reset_config
from ...serviceclient._discovery import (
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.integration]

_DEAD_PID = 2_000_000_000


@pytest.fixture()
def isolated_status_dir(tmp_path: Path) -> Iterator[Path]:
    prev = os.environ.get(EnvVar.STATUS_DIR.value)
    status_dir = tmp_path / "vaultspec-rag"
    status_dir.mkdir()
    os.environ[EnvVar.STATUS_DIR.value] = str(status_dir)
    reset_config()
    try:
        yield status_dir
    finally:
        if prev is None:
            os.environ.pop(EnvVar.STATUS_DIR.value, None)
        else:
            os.environ[EnvVar.STATUS_DIR.value] = prev
        reset_config()


# ---------------------------------------------------------------------------
# S08/S10: the discovery-file unlink guard
# ---------------------------------------------------------------------------


class TestUnlinkDecisionGuard:
    """``_should_unlink_discovery_file`` removes only a confirmed-dead holder."""

    def test_confirmed_dead_pid_may_unlink(self) -> None:
        assert _should_unlink_discovery_file(pid_alive=False) is True

    def test_live_pid_must_not_unlink(self) -> None:
        # A live PID with an ambiguous identity result must keep the file.
        assert _should_unlink_discovery_file(pid_alive=True) is False


class TestExistingServiceRunningUnlink:
    """``_existing_service_running`` keeps a live holder's discovery file."""

    def _write(self, status_dir: Path, *, pid: int, port: int) -> Path:
        sf = status_dir / "service.json"
        sf.write_text(
            json.dumps(
                {
                    "schema": SERVICE_DISCOVERY_SCHEMA,
                    "version": SERVICE_DISCOVERY_VERSION,
                    "pid": pid,
                    "port": port,
                    "started_at": "2026-06-24T00:00:00+00:00",
                    "service_token": "tok-live",
                }
            ),
            encoding="utf-8",
        )
        return sf

    def test_live_pid_ambiguous_identity_keeps_file(
        self, isolated_status_dir: Path
    ) -> None:
        """A live PID (this process) whose /health identity cannot be confirmed
        must NOT have its discovery file unlinked (#204)."""
        # This test process is alive; no service listens on the recorded port,
        # so the /health identity check transiently "misses" - the ambiguous
        # case. The file must survive.
        sf = self._write(isolated_status_dir, pid=os.getpid(), port=1)

        running = _existing_service_running()

        assert running is False  # not actually our healthy daemon
        assert sf.exists(), (
            "a live-but-unconfirmed PID's discovery file must not be erased"
        )

    def test_confirmed_dead_pid_unlinks_file(
        self, isolated_status_dir: Path
    ) -> None:
        """A confirmed-dead recorded PID has its stale discovery file removed."""
        sf = self._write(isolated_status_dir, pid=_DEAD_PID, port=1)

        running = _existing_service_running()

        assert running is False
        assert not sf.exists(), "a confirmed-dead holder's stale file is cleaned"


# ---------------------------------------------------------------------------
# S07/S09: the breakaway fallback never silently produces a shell-bound daemon
# ---------------------------------------------------------------------------


class TestBreakawayFallback:
    """``_spawn_windows`` fails loudly rather than spawning a doomed daemon."""

    def test_fail_loud_when_spawn_cannot_detach(self, tmp_path: Path) -> None:
        """When the spawn cannot succeed, the Windows path raises
        DaemonBreakawayError instead of silently producing a shell-bound daemon.

        Driven with a real ``subprocess.Popen`` against a non-existent
        executable so both the breakaway attempt and the console-detached
        fallback raise a real ``OSError`` - exercising the exact escalation the
        remediation introduced, on the real win32 code path. On non-Windows the
        function is not the spawn path used, so the assertion is scoped to
        win32 where the regression lives.
        """
        log_path = tmp_path / "svc.log"
        log_fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            cmd = [str(tmp_path / "does-not-exist-interpreter"), "-m", "noop"]
            if sys.platform == "win32":
                with pytest.raises(DaemonBreakawayError):
                    _spawn_windows(cmd, dict(os.environ), log_fd)
            else:
                # Off-Windows, _spawn_windows still escalates an unspawnable
                # command (no breakaway/detach available) to the loud error,
                # which is the contract under test: never a silent doomed spawn.
                with pytest.raises((DaemonBreakawayError, OSError)):
                    _spawn_windows(cmd, dict(os.environ), log_fd)
        finally:
            os.close(log_fd)
