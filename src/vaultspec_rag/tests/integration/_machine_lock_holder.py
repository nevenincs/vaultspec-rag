"""Real foreign-process machine-lock lifecycle helpers.

The launcher and lock holder are deliberately separate interpreter processes.
That mirrors Windows launchers which may report a different ``Popen.pid`` from
the interpreter that owns the OS lock.  Cleanup signals the holder through a
test-owned control file and positively observes OS-lock release before allowing
the launcher or fixture-owned lock file to be removed.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue

from ..._machine_lock import machine_lock_live_holder

_STARTUP_TIMEOUT = 10.0
_SHUTDOWN_TIMEOUT = 10.0

_HOLDER = """
import os
import sys
import time
from pathlib import Path

os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"] = sys.argv[1]
from vaultspec_rag.config._settings import reset_config  # absolute-import-ok
reset_config()
from vaultspec_rag._machine_lock import acquire_machine_lock  # absolute-import-ok
acquired, _ = acquire_machine_lock()
print("ACQUIRED:" + str(os.getpid()) if acquired else "FAILED", flush=True)
stop = Path(sys.argv[2])
while not stop.exists():
    time.sleep(0.01)
"""

_LAUNCHER = """
import subprocess
import sys
import time
from pathlib import Path

holder = subprocess.Popen(
    [sys.executable, "-c", sys.argv[4], sys.argv[1], sys.argv[2]],
    stdout=subprocess.PIPE,
    text=True,
)
line = holder.stdout.readline() if holder.stdout is not None else ""
print(line.strip(), flush=True)
holder.wait()
launcher_stop = Path(sys.argv[3])
while not launcher_stop.exists():
    time.sleep(0.01)
"""


@dataclass(frozen=True, slots=True)
class HolderReleaseEvidence:
    """Observed ordering from one foreign-holder shutdown."""

    launcher_pid: int
    holder_pid: int
    lock_released: bool
    launcher_alive_at_release: bool


@dataclass(slots=True)
class ForeignMachineLockHolder:
    """A real launcher plus a distinct child which owns the machine lock."""

    launcher: subprocess.Popen[str]
    holder_pid: int
    holder_stop: Path
    launcher_stop: Path

    @property
    def launcher_pid(self) -> int:
        """Return the process id exposed by ``Popen`` for the launcher."""
        return self.launcher.pid

    def terminate_launcher(self) -> None:
        """Terminate only the launcher, leaving the holder to prove PID split."""
        if self.launcher.poll() is None:
            self.launcher.kill()
            self.launcher.wait(timeout=5.0)

    def stop(self, *, timeout: float = 10.0) -> HolderReleaseEvidence:
        """Stop the actual holder and observe lock release before launcher exit.

        The control file is unique to this test-owned holder, so this never
        signals an operator or machine-global process.  The bounded loop does
        not use elapsed time as proof: success requires the real OS-lock probe
        to report free.
        """
        release_error: OSError | AssertionError | None = None
        launcher_error: OSError | AssertionError | None = None
        launcher_alive = False
        try:
            try:
                self.holder_stop.write_text("stop\n", encoding="utf-8")
                _wait_for_lock_release(self.holder_pid, timeout=timeout)
            except (OSError, AssertionError) as exc:
                release_error = exc
                try:
                    _terminate_confirmed_holder(self.holder_pid, timeout=timeout)
                except (OSError, AssertionError) as cleanup_exc:
                    release_error = AssertionError(
                        f"holder cleanup failed after {exc!r}: {cleanup_exc}"
                    )
            launcher_alive = self.launcher.poll() is None
        finally:
            try:
                _reap_launcher(self.launcher, self.launcher_stop)
            except (OSError, AssertionError) as exc:
                launcher_error = exc

        if release_error is not None and launcher_error is not None:
            raise ExceptionGroup(
                "foreign lock holder and launcher cleanup failed",
                [release_error, launcher_error],
            )
        if release_error is not None:
            raise release_error
        if launcher_error is not None:
            raise launcher_error
        return HolderReleaseEvidence(
            launcher_pid=self.launcher.pid,
            holder_pid=self.holder_pid,
            lock_released=True,
            launcher_alive_at_release=launcher_alive,
        )


def _wait_for_lock_release(expected_pid: int, *, timeout: float) -> None:
    """Require the isolated OS lock to become free within a bounded deadline."""
    deadline = time.monotonic() + timeout
    poll_gate = threading.Event()
    while True:
        live_holder = machine_lock_live_holder()
        if live_holder == 0:
            return
        if live_holder != expected_pid:
            msg = (
                "isolated machine lock changed holder during cleanup: "
                f"expected {expected_pid}, observed {live_holder}"
            )
            raise AssertionError(msg)
        if time.monotonic() >= deadline:
            msg = (
                f"test-owned lock holder {expected_pid} did not release the OS lock "
                f"within {timeout:.1f}s"
            )
            raise AssertionError(msg)
        poll_gate.wait(0.01)


def _terminate_confirmed_holder(holder_pid: int, *, timeout: float) -> None:
    """Terminate only the PID still proven to own this isolated OS lock."""
    live_holder = machine_lock_live_holder()
    if live_holder == 0:
        return
    if live_holder != holder_pid:
        msg = (
            "refusing to terminate an unexpected machine-lock holder: "
            f"expected {holder_pid}, observed {live_holder}"
        )
        raise AssertionError(msg)
    with contextlib.suppress(ProcessLookupError):
        os.kill(holder_pid, signal.SIGTERM)
    _wait_for_lock_release(holder_pid, timeout=timeout)


def _reap_launcher(launcher: subprocess.Popen[str], stop: Path) -> None:
    """Signal and await the test-owned launcher, force-reaping its tree if stuck."""
    signal_error: OSError | None = None
    try:
        stop.write_text("stop\n", encoding="utf-8")
    except OSError as exc:
        signal_error = exc
    if launcher.poll() is None:
        try:
            launcher.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(launcher.pid)],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=5.0,
                    )
            else:
                launcher.kill()
            if launcher.poll() is None:
                with contextlib.suppress(OSError):
                    launcher.kill()
            try:
                launcher.wait(timeout=5.0)
            except subprocess.TimeoutExpired as exc:
                msg = f"test-owned launcher {launcher.pid} did not exit"
                raise AssertionError(msg) from exc
    if signal_error is not None:
        raise signal_error


def _abort_failed_start(
    launcher: subprocess.Popen[str],
    holder_stop: Path,
    launcher_stop: Path,
) -> None:
    """Clean every test-owned process after readiness fails."""
    holder_error: OSError | AssertionError | None = None
    launcher_error: OSError | AssertionError | None = None
    with contextlib.suppress(OSError):
        holder_stop.write_text("stop\n", encoding="utf-8")
    try:
        live_holder = machine_lock_live_holder()
        if live_holder != 0:
            _terminate_confirmed_holder(live_holder, timeout=_SHUTDOWN_TIMEOUT)
    except (OSError, AssertionError) as exc:
        holder_error = exc
    finally:
        try:
            _reap_launcher(launcher, launcher_stop)
        except (OSError, AssertionError) as exc:
            launcher_error = exc
    if holder_error is not None and launcher_error is not None:
        raise ExceptionGroup(
            "failed-start holder and launcher cleanup failed",
            [holder_error, launcher_error],
        )
    if holder_error is not None:
        raise holder_error
    if launcher_error is not None:
        raise launcher_error


def spawn_foreign_machine_lock_holder(
    storage_dir: str | Path,
) -> ForeignMachineLockHolder:
    """Start a real launcher and distinct lock-owning interpreter."""
    storage = Path(storage_dir)
    control_dir = storage.parent / "holder-control"
    control_dir.mkdir(parents=True, exist_ok=True)
    holder_stop = control_dir / "holder.stop"
    launcher_stop = control_dir / "launcher.stop"
    holder_stop.unlink(missing_ok=True)
    launcher_stop.unlink(missing_ok=True)
    preexisting_holder = machine_lock_live_holder()
    if preexisting_holder != 0:
        msg = (
            "refusing to spawn a test holder over an existing isolated lock holder "
            f"{preexisting_holder}"
        )
        raise AssertionError(msg)
    launcher = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _LAUNCHER,
            str(storage),
            str(holder_stop),
            str(launcher_stop),
            _HOLDER,
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    lines: Queue[str] = Queue(maxsize=1)

    def read_readiness() -> None:
        line = launcher.stdout.readline() if launcher.stdout is not None else ""
        lines.put(line)

    reader = threading.Thread(target=read_readiness, daemon=True)
    reader.start()
    try:
        line = lines.get(timeout=_STARTUP_TIMEOUT)
    except Empty as exc:
        _abort_failed_start(launcher, holder_stop, launcher_stop)
        msg = (
            "lock-holder launcher did not report readiness within "
            f"{_STARTUP_TIMEOUT:.1f}s"
        )
        raise AssertionError(msg) from exc
    if not line.startswith("ACQUIRED:"):
        _abort_failed_start(launcher, holder_stop, launcher_stop)
        msg = f"lock-holder child failed to acquire: {line!r}"
        raise AssertionError(msg)
    holder_pid = int(line.split(":", 1)[1].strip())
    if launcher.pid == holder_pid:
        _abort_failed_start(launcher, holder_stop, launcher_stop)
        msg = "foreign lock harness did not create distinct launcher and holder PIDs"
        raise AssertionError(msg)
    return ForeignMachineLockHolder(
        launcher=launcher,
        holder_pid=holder_pid,
        holder_stop=holder_stop,
        launcher_stop=launcher_stop,
    )
