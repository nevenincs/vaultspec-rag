"""Canonical detached spawning retains its real launcher until process exit."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING, cast

import pytest

from .._process_probe import wait_for_exit
from ._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_LAUNCH = """
import gc, json, sys, threading, time
from pathlib import Path
from vaultspec_rag.cli._process import _spawn_service
root = Path(sys.argv[1])
started = time.monotonic()
pid = _spawn_service(12345, root / 'launcher.log', timeout=10)
launcher_witness = root / 'launcher.pid.tmp'
launcher_witness.write_text(str(pid))
launcher_witness.replace(root / 'launcher.pid')
elapsed = time.monotonic() - started
gc.collect()
deadline = time.monotonic() + 10
while not (root / 'child.pid').exists():
    assert time.monotonic() < deadline, 'CPU child never became ready'
    time.sleep(.01)
waiters = [thread for thread in threading.enumerate()
           if thread.name == 'service-launcher-reaper']
assert len(waiters) == 1 and waiters[0].daemon
assert waiters[0].is_alive(), 'spawn waited for the detached child'
assert not (root / 'stop').exists()
print(json.dumps({'launcher': pid,
                  'interpreter': int((root / 'child.pid').read_text()),
                  'elapsed': elapsed}), flush=True)
(root / 'stop').touch()
waiters[0].join(timeout=10)
assert not waiters[0].is_alive(), 'launcher was not reaped after real exit'
gc.collect()
"""

_FAIL_START = """
import gc, sys, threading, time
from pathlib import Path
import pytest
from vaultspec_rag.cli._process import _spawn_service
from vaultspec_rag._process_probe import pid_alive
root = Path(sys.argv[1])
original_start = threading.Thread.start
def refuse_reaper(self):
    if self.name != 'service-launcher-reaper':
        return original_start(self)
    deadline = time.monotonic() + 10
    while not (root / 'child.pid').exists():
        assert time.monotonic() < deadline, 'CPU child never became ready'
        time.sleep(.01)
    raise RuntimeError('controlled waiter startup failure')
with pytest.MonkeyPatch.context() as monkeypatch:
    # Only waiter startup is refused; process creation and witness cleanup are real.
    monkeypatch.setattr(threading.Thread, 'start', refuse_reaper)
    try:
        _spawn_service(12345, root / 'launcher.log', timeout=10, cleanup_timeout=10)
    except RuntimeError as error:
        assert str(error) == 'controlled waiter startup failure'
        assert not getattr(error, '__notes__', ()), str(error.__notes__)
    else:
        raise AssertionError('waiter setup failure was reported as successful spawn')
child_pid = int((root / 'child.pid').read_text())
assert not pid_alive(child_pid), 'witnessed child survived ownership failure'
gc.collect()
"""


def _cpu_bootstrap_environment(tmp_path: Path) -> dict[str, str]:
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "sitecustomize.py").write_text(
        "import os, sys, time\nfrom pathlib import Path\n"
        "if any(sys.orig_argv[i:i+2] == ['-m', 'vaultspec_rag.server'] "
        "for i in range(len(sys.orig_argv)-1)):\n"
        f"    root = Path({str(tmp_path)!r})\n"
        # Existence is readiness: publish complete witnesses atomically.
        "    witness = root / 'child.pid.tmp'\n"
        "    witness.write_text(str(os.getpid()))\n"
        "    witness.replace(root / 'child.pid')\n"
        "    while not (root / 'stop').exists():\n"
        "        time.sleep(.01)\n"
        "    os._exit(0)\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(bootstrap), environment.get("PYTHONPATH", ""))
    )
    environment["PYTHONWARNINGS"] = "error"
    return environment


def _stop_cpu_children(tmp_path: Path) -> None:
    (tmp_path / "stop").touch()
    for name in ("child.pid", "launcher.pid"):
        witness = tmp_path / name
        if witness.exists():
            assert wait_for_exit(int(witness.read_text()), timeout=10), name


def test_canonical_spawn_hands_off_and_reaps_the_real_detached_launcher(
    tmp_path: Path,
) -> None:
    """A CPU bootstrap exercises real spawn/anchor/flags without loading a service.

    Removing ownership must expose the real Popen ResourceWarning under forced GC.
    """
    environment = _cpu_bootstrap_environment(tmp_path)
    try:
        result = subprocess.run(
            [sys.executable, "-W", "error", "-c", _LAUNCH, str(tmp_path)],
            capture_output=True,
            text=True,
            env=environment,
            timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == "", result.stderr
        report: object = json.loads(result.stdout)
        assert isinstance(report, dict)
        fields = cast("dict[str, object]", report)
        assert isinstance(fields["launcher"], int)
        assert isinstance(fields["interpreter"], int)
        assert isinstance(fields["elapsed"], float)
        assert fields["elapsed"] < 10
    finally:
        _stop_cpu_children(tmp_path)


def test_failed_waiter_start_reaps_the_real_witnessed_process_tree(
    tmp_path: Path,
) -> None:
    """One startup seam fails; the actual launcher's child must be contained."""
    environment = _cpu_bootstrap_environment(tmp_path)
    try:
        result = subprocess.run(
            [sys.executable, "-W", "error", "-c", _FAIL_START, str(tmp_path)],
            capture_output=True,
            text=True,
            env=environment,
            timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == "", result.stderr
    finally:
        _stop_cpu_children(tmp_path)
