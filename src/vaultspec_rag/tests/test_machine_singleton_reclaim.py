"""Reclaim a wedged machine-singleton holder (real OS lock, real subprocess).

A holder process acquires the machine-global singleton lock under an isolated
storage dir and never writes a ``service.json`` - the wedged/undiscoverable
singleton that the ``mcp-conformance`` research found deadlocking the machine
(``server start`` refuses the lock holder, ``server stop`` finds no discovery
file, ``server status`` reports stopped). ``_reclaim_machine_singleton`` must
detect that holder through the lock and terminate it, so ``server stop`` becomes
the real recovery instead of a manual OS kill. No mocks: the lock is acquired
for real in a child process and reclaimed for real.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest
import typer

from .._machine_lock import probe_machine_lock
from ..cli._service_stop import (
    _reclaim_machine_singleton,
)
from ..config._settings import reset_config
from ..config._types import EnvVar
from ._unnamed_lock_holder import unnamed_machine_lock_holder

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

# Child that acquires the machine lock under the given storage dir, signals
# readiness, and then idles - holding the singleton with no status file.
_HOLDER_SRC = """
import os, sys, time

os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"] = sys.argv[1]
from vaultspec_rag.config._settings import reset_config  # absolute-import-ok

reset_config()
from vaultspec_rag._machine_lock import acquire_machine_lock  # absolute-import-ok

acquired, _holder = acquire_machine_lock()
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    fh.write("1" if acquired else "0")
time.sleep(120)
"""


@pytest.fixture
def isolated_storage(tmp_path: Path) -> Iterator[Path]:
    """Relocate the machine lock under a temp storage dir (never the real one)."""
    key = EnvVar.QDRANT_STORAGE_DIR.value
    prev = os.environ.get(key)
    os.environ[key] = str(tmp_path / "qdrant-server" / "storage")
    reset_config()
    try:
        yield tmp_path
    finally:
        if prev is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prev
        reset_config()


# Bounds the wait for a detached child to acquire the lock and say so.
_HOLDER_READY_TIMEOUT_SECONDS = 60.0


def test_reclaim_terminates_a_wedged_machine_holder(isolated_storage: Path) -> None:
    """A live lock holder with no status file is found and terminated."""
    storage = os.environ[EnvVar.QDRANT_STORAGE_DIR.value]
    # The script path carries "vaultspec_rag" so the POSIX cmdline identity check
    # recognises the child as our service (Windows checks the python image name).
    holder_script = isolated_storage / "vaultspec_rag_holder.py"
    holder_script.write_text(_HOLDER_SRC, encoding="utf-8")
    ready = isolated_storage / "ready.txt"

    # Spawn the holder detached and in its own process group, exactly as the
    # real daemon is spawned. The reclaim terminates it with CTRL_BREAK_EVENT on
    # Windows, which propagates through the shared console; a detached holder has
    # no console, so the signal cannot reach this test runner (the force-kill
    # then terminates it by handle).
    cmd = [sys.executable, str(holder_script), storage, str(ready)]
    if sys.platform == "win32":
        proc = subprocess.Popen(
            cmd,
            creationflags=subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        proc = subprocess.Popen(cmd, start_new_session=True)
    try:
        # A detached child on a runner executing a dozen workers can take far
        # longer than a developer machine simply to be scheduled, and the wait
        # ends as soon as the file appears. Its absence is reported as the
        # assertion below rather than as a FileNotFoundError from the read,
        # which is what a bare read of a file the child never wrote produces.
        deadline = time.monotonic() + _HOLDER_READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline and not ready.exists():
            time.sleep(0.25)
        assert ready.exists(), (
            "holder child never signalled ready within "
            f"{_HOLDER_READY_TIMEOUT_SECONDS:.0f}s"
        )
        assert ready.read_text(encoding="utf-8") == "1", (
            "holder child failed to acquire the machine lock"
        )

        # No status file was written; reclaim must locate the holder through the
        # machine lock alone and terminate it. (We assert via the lock, not
        # proc.pid: the venv launcher shim's pid can differ from the python
        # process that actually acquired the lock.)
        reclaimed = _reclaim_machine_singleton(False)
        assert reclaimed is not None, "no machine holder was reclaimed"

        # The singleton lock is now free - the wedged holder was terminated.
        for _ in range(50):
            if not probe_machine_lock().held:
                break
            time.sleep(0.1)
        assert not probe_machine_lock().held, "machine lock still held after reclaim"
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


@pytest.mark.usefixtures("isolated_storage")
def test_reclaim_returns_none_when_no_holder() -> None:
    """With no lock holder, reclaim is a no-op returning ``None``."""
    assert _reclaim_machine_singleton(False) is None


def test_probe_reports_a_held_unnameable_lock_as_held(isolated_storage: Path) -> None:
    """A held lock whose owner record cannot be read is held, never free.

    The OS lock is the authority: something owns the machine even when its
    published record is garbage, and reporting that as free is what lets a
    caller spawn a second resident service or report the running one stopped.
    Mutation: collapsing the contended-but-unnameable observation back into
    the not-held result fails the ``held is True`` assertion here, while the
    free case stays pinned by ``test_reclaim_returns_none_when_no_holder``.
    """
    with unnamed_machine_lock_holder(isolated_storage):
        probe = probe_machine_lock()
        assert probe.held is True, "a held machine lock was reported free"
        assert probe.holder_pid == 0


def test_reclaim_refuses_a_held_lock_it_cannot_name(
    isolated_storage: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reclaim over an unnameable holder is a distinct failure, not a no-op.

    Returning ``None`` here would let the stop verb report "not running" over
    a machine something demonstrably owns. Mutation: treating the unnamed
    holder as no holder skips the raise and fails on the expected exception.
    """
    with unnamed_machine_lock_holder(isolated_storage):
        with pytest.raises(typer.Exit):
            _reclaim_machine_singleton(True)
        payload = json.loads(capsys.readouterr().out)
        assert payload["error"] == "machine_holder_unnamed"
