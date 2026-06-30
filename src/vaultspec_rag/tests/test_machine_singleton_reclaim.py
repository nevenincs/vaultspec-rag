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

import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from .._machine_lock import machine_lock_live_holder
from ..cli._service_lifecycle import (
    _reclaim_machine_singleton,  # pyright: ignore[reportPrivateUsage]  # unit under test
)
from ..config import EnvVar, reset_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

# Child that acquires the machine lock under the given storage dir, signals
# readiness, and then idles - holding the singleton with no status file.
_HOLDER_SRC = """
import os, sys, time

os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"] = sys.argv[1]
from vaultspec_rag.config import reset_config

reset_config()
from vaultspec_rag._machine_lock import acquire_machine_lock

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
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(0.1)
        assert ready.read_text(encoding="utf-8") == "1", (
            "holder child failed to acquire the machine lock"
        )

        # No status file was written; reclaim must locate the holder through the
        # machine lock alone and terminate it. (We assert via the lock, not
        # proc.pid: the venv launcher shim's pid can differ from the python
        # process that actually acquired the lock.)
        reclaimed = _reclaim_machine_singleton()
        assert reclaimed is not None, "no machine holder was reclaimed"

        # The singleton lock is now free - the wedged holder was terminated.
        for _ in range(50):
            if machine_lock_live_holder() == 0:
                break
            time.sleep(0.1)
        assert machine_lock_live_holder() == 0, "machine lock still held after reclaim"
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


@pytest.mark.usefixtures("isolated_storage")
def test_reclaim_returns_none_when_no_holder() -> None:
    """With no lock holder, reclaim is a no-op returning ``None``."""
    assert _reclaim_machine_singleton() is None
