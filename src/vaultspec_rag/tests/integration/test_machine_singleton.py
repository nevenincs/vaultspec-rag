"""Machine-scoped service-lock tests.

No mocks, no GPU: the lock is an OS advisory lock, so a "foreign holder" is a
real subprocess that actually holds the lock (not merely a pid written to the
file). A dead or empty lock file carries no OS lock, so acquiring over it
succeeds - the crash-safe property (the OS releases a dead holder's lock).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from ..._machine_lock import (
    acquire_machine_lock_lease,
    delete_machine_discovery,
    machine_discovery_path,
    publish_machine_discovery,
    release_machine_lock_lease,
)
from ...cli._process import (
    _port_is_listening,
    acquire_machine_lock,
    machine_lock_live_holder,
    release_machine_lock,
)
from ...config import EnvVar
from ._helpers import _get_ephemeral_port, _get_ephemeral_qdrant_port
from ._machine_lock_holder import spawn_foreign_machine_lock_holder

if TYPE_CHECKING:
    from pathlib import Path


class TestMachineLock:
    def test_acquire_release_then_reacquire(self, isolated_lock: Path) -> None:
        acquired, holder = acquire_machine_lock()
        assert acquired is True
        assert holder == os.getpid()
        assert isolated_lock.exists()
        release_machine_lock()
        # The file persists (its existence is not the authority); releasing
        # frees the OS lock, so the lock is immediately re-acquirable.
        reacquired, holder2 = acquire_machine_lock()
        assert reacquired is True
        assert holder2 == os.getpid()
        release_machine_lock()

    def test_second_acquire_refused_while_foreign_holder_alive(
        self, isolated_lock: Path
    ) -> None:
        storage = os.environ[EnvVar.QDRANT_STORAGE_DIR.value]
        foreign_holder = spawn_foreign_machine_lock_holder(storage)
        holder_pid = foreign_holder.holder_pid
        try:
            assert isolated_lock.exists()
            assert foreign_holder.launcher_pid != holder_pid
            acquired, holder = acquire_machine_lock()
            assert acquired is False
            assert holder == holder_pid
            # The advisory-lock probe agrees the holder is live.
            assert machine_lock_live_holder() == holder_pid
            # Reproduce the Windows launcher/holder split: awaiting the
            # launcher is not evidence that the actual lock holder exited.
            foreign_holder.terminate_launcher()
            assert machine_lock_live_holder() == holder_pid
        finally:
            evidence = foreign_holder.stop()
        assert evidence.lock_released is True
        assert evidence.launcher_alive_at_release is False
        assert machine_lock_live_holder() == 0

    def test_dead_holder_lock_is_acquirable(self, isolated_lock: Path) -> None:
        # A lock file left by a dead holder carries no OS lock (the OS released
        # it on death), so acquiring over it succeeds - no manual reclaim.
        isolated_lock.parent.mkdir(parents=True, exist_ok=True)
        isolated_lock.write_text(json.dumps({"pid": 2_000_000_000}), encoding="utf-8")
        acquired, holder = acquire_machine_lock()
        assert acquired is True
        assert holder == os.getpid()

    def test_empty_lock_file_is_not_a_deadlock(self, isolated_lock: Path) -> None:
        # An empty/corrupt lock file from a crash carries no OS lock either, so
        # it is acquirable - never a permanent machine-wide deadlock.
        isolated_lock.parent.mkdir(parents=True, exist_ok=True)
        isolated_lock.write_text("", encoding="utf-8")
        acquired, holder = acquire_machine_lock()
        assert acquired is True
        assert holder == os.getpid()

    def test_release_is_idempotent_and_only_releases_our_lock(
        self, isolated_lock: Path
    ) -> None:
        # Releasing when we hold nothing is a no-op; a foreign holder's lock is
        # never released by our release.
        release_machine_lock()  # holds nothing - no error
        storage = os.environ[EnvVar.QDRANT_STORAGE_DIR.value]
        foreign_holder = spawn_foreign_machine_lock_holder(storage)
        holder_pid = foreign_holder.holder_pid
        try:
            assert isolated_lock.exists()
            assert foreign_holder.launcher_pid != holder_pid
            release_machine_lock()  # we are not the holder
            assert machine_lock_live_holder() == holder_pid
        finally:
            evidence = foreign_holder.stop()
        assert evidence.lock_released is True
        assert evidence.launcher_alive_at_release is True
        assert machine_lock_live_holder() == 0

    def test_pointer_mutation_requires_retained_owner_lease(
        self, isolated_lock: Path
    ) -> None:
        lease, holder = acquire_machine_lock_lease()
        assert lease is not None
        assert holder == os.getpid()
        pointer = machine_discovery_path()
        assert pointer.parent == isolated_lock.parent
        original = {
            "schema_version": 1,
            "pid": lease.pid,
            "port": 18_701,
        }
        publish_machine_discovery(lease, original)
        assert json.loads(pointer.read_text(encoding="utf-8")) == original
        release_machine_lock_lease(lease)

        storage = os.environ[EnvVar.QDRANT_STORAGE_DIR.value]
        foreign_holder = spawn_foreign_machine_lock_holder(storage)
        try:
            refused_lease, refused_holder = acquire_machine_lock_lease()
            assert refused_lease is None
            assert refused_holder == foreign_holder.holder_pid

            replacement = {
                "schema_version": 1,
                "pid": lease.pid,
                "port": 18_702,
            }
            with pytest.raises(PermissionError, match="active machine-lock lease"):
                publish_machine_discovery(lease, replacement)
            with pytest.raises(PermissionError, match="active machine-lock lease"):
                delete_machine_discovery(lease)
            assert json.loads(pointer.read_text(encoding="utf-8")) == original
        finally:
            evidence = foreign_holder.stop()
        assert evidence.lock_released is True

        owner_lease, owner_pid = acquire_machine_lock_lease()
        assert owner_lease is not None
        assert owner_pid == os.getpid()
        try:
            with pytest.raises(ValueError, match="payload PID"):
                publish_machine_discovery(
                    owner_lease,
                    {"schema_version": 1, "pid": foreign_holder.holder_pid},
                )
            assert json.loads(pointer.read_text(encoding="utf-8")) == original

            replacement = {
                "schema_version": 1,
                "pid": owner_lease.pid,
                "port": 18_703,
            }
            publish_machine_discovery(owner_lease, replacement)
            assert json.loads(pointer.read_text(encoding="utf-8")) == replacement
            assert not tuple(pointer.parent.glob(f".{pointer.name}.*.tmp"))
            delete_machine_discovery(owner_lease)
            assert not pointer.exists()
        finally:
            release_machine_lock_lease(owner_lease)


class TestLosingDaemonBoundary:
    """A real HTTP daemon that loses the singleton race must start nothing.

    The daemon claims the machine singleton before it commits GPU memory,
    spawns Qdrant, binds its listener, publishes discovery, or starts the
    watcher and maintenance loops. A loser must therefore exit nonzero having
    touched none of them, so a speculative second start can never disturb the
    incumbent's resources.
    """

    def test_losing_daemon_exits_before_starting_any_component(
        self,
        isolated_lock: Path,
        tmp_path: Path,
    ) -> None:
        storage = os.environ[EnvVar.QDRANT_STORAGE_DIR.value]
        pointer = machine_discovery_path()
        status_dir = tmp_path / "loser-status"
        status_dir.mkdir()
        port = _get_ephemeral_port()

        incumbent = spawn_foreign_machine_lock_holder(storage)
        try:
            assert machine_lock_live_holder() == incumbent.holder_pid
            assert not pointer.exists()

            env = dict(os.environ)
            env[EnvVar.QDRANT_STORAGE_DIR.value] = storage
            env[EnvVar.STATUS_DIR.value] = str(status_dir)
            # Relocate the managed qdrant port too: on the shared default the
            # loser would fail on the operator's live qdrant before it ever
            # reached the singleton claim, proving nothing about the boundary.
            qdrant_port = _get_ephemeral_qdrant_port()
            env[EnvVar.QDRANT_PORT.value] = str(qdrant_port)

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "vaultspec_rag.server",
                    "--port",
                    str(port),
                ],
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
                check=False,
                cwd=str(tmp_path),
            )
            # The daemon redirects its own stdout and stderr into the managed
            # log, so that file - not the pipe - carries the refusal.
            logs = "\n".join(
                path.read_text(encoding="utf-8", errors="replace")
                for path in sorted(status_dir.rglob("*.log"))
            )
            output = f"{logs}\n{completed.stdout}\n{completed.stderr}"

            # The loser must fail loudly rather than idle or exit success.
            assert completed.returncode != 0, (
                f"losing daemon exited 0; output:\n{output[-3000:]}"
            )
            assert output.strip(), (
                "losing daemon produced no diagnostics at all; rc="
                f"{completed.returncode}; status dir contents="
                f"{sorted(item.name for item in status_dir.rglob('*'))}"
            )
            # It must name the incumbent rather than fail opaquely. On Windows
            # the loser reaches the singleton-claim refusal path and formats the
            # holder pid into its diagnostics; on POSIX it exits via the bounded-
            # shutdown backstop (still nonzero, and still binds/publishes nothing
            # per the assertions around this) without formatting the holder pid.
            # POSIX loser-diagnostics parity is a tracked follow-up.
            if sys.platform == "win32":
                assert str(incumbent.holder_pid) in output, (
                    f"refusal did not name the live holder; output:\n{output[-3000:]}"
                )
            # It must not have bound the listener it was asked for.
            assert not _port_is_listening(port), (
                f"losing daemon bound port {port} before refusing"
            )
            # It must not have published discovery over the incumbent's
            # machine-global pointer, nor left a status view of its own.
            assert not pointer.exists(), (
                "losing daemon published the machine discovery pointer"
            )
            assert not (status_dir / "service.json").exists(), (
                "losing daemon published a status view"
            )
            # The refusal must come from the singleton claim itself.
            assert "_claim_machine_singleton" in output, (
                f"refusal did not originate at the singleton claim;"
                f" output:\n{output[-3000:]}"
            )
            assert "already owns this machine" in output
            # Component startup is where the listener, the Qdrant child, the
            # watcher, and the maintenance loop are brought up. Its absence
            # from the failure trace is the boundary proof: the claim refused
            # before any of them was reached. Asserting on the frame rather
            # than on log keywords avoids matching the refusal message's own
            # prose, which names the resources it is protecting.
            assert "_start_components" not in output, (
                f"losing daemon reached component startup; output:\n{output[-3000:]}"
            )
            # No managed Qdrant child came up on the isolated port either.
            assert not _port_is_listening(qdrant_port), (
                f"losing daemon started a Qdrant child on {qdrant_port}"
            )

            # The incumbent still owns the singleton, untouched.
            assert machine_lock_live_holder() == incumbent.holder_pid
        finally:
            evidence = incumbent.stop()
        assert evidence.lock_released is True
        assert machine_lock_live_holder() == 0
        assert isolated_lock.exists()
