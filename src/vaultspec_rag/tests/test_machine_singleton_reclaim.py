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
from typing import TYPE_CHECKING

import pytest
import typer

from .._machine_lock import probe_machine_lock
from .._process_probe import pid_terminated
from ..cli._service_stop import (
    _reclaim_machine_singleton,
)
from ..config._types import EnvVar
from ._config_fixtures import reset_config
from ._unnamed_lock_holder import unnamed_machine_lock_holder
from .test_service_stop_port import _starting_process

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


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
    del isolated_storage
    with _starting_process(
        ["-m", "vaultspec_rag.server", "--port", "8766"], hold_machine_lock=True
    ) as proc:
        assert probe_machine_lock().holder_pid == proc.pid
        reclaimed = _reclaim_machine_singleton(False)
        assert reclaimed is not None, "no machine holder was reclaimed"
        assert pid_terminated(proc.pid), "witnessed resident holder was not terminated"
        assert not probe_machine_lock().held, "machine lock still held after reclaim"


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
