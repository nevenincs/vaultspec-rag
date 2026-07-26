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
import subprocess
import sys
import time
from typing import TYPE_CHECKING, cast

import psutil
import pytest
from typer.testing import CliRunner

from .._machine_lock import machine_lock_live_holder
from ..cli import app
from ..cli._service_status import _write_service_status
from ..cli._service_stop import (
    _orphan_daemon_pids,
    _service_pid_on_port,
    _stop_service_on_port,
)
from ..config import reset_config
from ._ports import free_loopback_port

if TYPE_CHECKING:
    from pathlib import Path

#: Budget for one `server stop --orphans` subprocess. The reap walks the whole
#: process table, and the CLI is a fresh process every time, so it always pays
#: the COLD walk: measured at 65.4s on a host with ~1400 processes, against
#: 3.8-5.6s warm. A 60s budget therefore killed these guards on
#: `TimeoutExpired` before a single safety assertion ran - they reported a
#: failure that said nothing about whether the reap spares the singleton, which
#: is the only thing they exist to check. The integration tier already carries
#: this figure; the unit tier now shares it rather than rediscovering it.
_REAP_SUBPROCESS_BUDGET_SECONDS = 240.0


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


def _spawn_witness_daemon(port: int) -> subprocess.Popen[bytes]:
    """Spawn a harmless sleeper whose cmdline carries the launch witness.

    The marker tokens ride as trailing argv to ``-c`` so ``psutil`` reports the
    subsequence ``-m vaultspec_rag.server --port <port>`` without the process
    ever importing the daemon or touching a GPU. Spawned in its own process
    group / session (as the real detached daemon is) so the reap's group-scoped
    termination signal cannot cascade back to this test process.
    """
    argv = [
        sys.executable,
        "-c",
        "import time; time.sleep(120)",
        "-m",
        "vaultspec_rag.server",
        "--port",
        str(port),
    ]
    if sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP (0x00000200): isolate the CTRL_BREAK group.
        return subprocess.Popen(argv, creationflags=0x00000200)
    return subprocess.Popen(argv, start_new_session=True)


# A Windows venv launcher shim re-execs the real interpreter, so each spawned
# `-m vaultspec_rag.server` witness enumerates as a launcher+worker PAIR; on
# POSIX the `-c` process is a single enumerable process with no such child. The
# reap must spare the singleton and reap the orphan under BOTH process models,
# so the expected witness count per daemon is platform-conditional.
_PROCS_PER_DAEMON = 2 if sys.platform == "win32" else 1


def _wait_for_matched(port: int, count: int) -> dict[int, int]:
    """Wait until at least *count* witness processes enumerate for *port*."""
    matched: dict[int, int] = {}
    for _ in range(100):
        matched = _orphan_daemon_pids(port)
        if len(matched) >= count:
            return matched
        time.sleep(0.1)
    msg = f"only {len(matched)} of {count} witness processes enumerated on {port}"
    raise AssertionError(msg)


def _pair_of(launcher_pid: int, matched: dict[int, int]) -> set[int]:
    """Return a launcher pid plus its matched worker children (the daemon pair)."""
    return {launcher_pid} | {
        pid for pid, ppid in matched.items() if ppid == launcher_pid
    }


def _pid_terminated(pid: int) -> bool:
    """True if *pid* is gone or a POSIX zombie (dead, awaiting its parent's reap).

    The reap runs out-of-process and is not the witnesses' parent, so on POSIX a
    force-killed orphan lingers as a zombie until this test (its parent) waits on
    it. A zombie is terminated - it holds no port, lock, or GPU - so 'reaped'
    means gone-or-zombie, matching the production reap's own liveness check.
    Windows has no zombie state, so this reduces to ``not pid_exists`` there.
    """
    if not psutil.pid_exists(pid):
        return True
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def _pid_live(pid: int) -> bool:
    """True only if *pid* is a live process - NOT gone and NOT a zombie.

    A spared singleton must be genuinely alive; a zombie would pass a bare
    ``pid_exists``, so a predicate mutation that wrongly kills the singleton would
    read as spared. Checking non-zombie liveness keeps the spare assertion honest.
    """
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _await_all_terminated(pids: set[int]) -> None:
    for _ in range(100):
        if all(_pid_terminated(pid) for pid in pids):
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


def _spawn_lock_holding_daemon(port: int) -> subprocess.Popen[bytes]:
    """Spawn a witness that HOLDS the machine lock, publishing no pointer.

    Models the singleton in the no-pointer recovery scenario the reap must
    tolerate: the resident daemon holds the machine-lock lease (so it is the
    reap's ``machine_lock_live_holder`` anchor) but wrote no service-status
    pointer, so the lock anchor is the ONLY thing sparing it. The lease-acquire
    runs in the worker the shim spawns, so the worker's pid is recorded in the
    lock file and the trailing witness argv keeps the whole pair enumerable.
    """
    code = (
        "import time;"
        "from vaultspec_rag.config import reset_config;"
        "reset_config();"
        "from vaultspec_rag._machine_lock import acquire_machine_lock_lease;"
        "lease, holder = acquire_machine_lock_lease();"
        "assert lease is not None, holder;"
        "time.sleep(120)"
    )
    argv = [
        sys.executable,
        "-c",
        code,
        "-m",
        "vaultspec_rag.server",
        "--port",
        str(port),
    ]
    if sys.platform == "win32":
        return subprocess.Popen(argv, creationflags=0x00000200)
    return subprocess.Popen(argv, start_new_session=True)


def _wait_for_lock_holder(candidates: set[int]) -> int:
    """Wait until the machine lock is held by a pid in *candidates*; return it."""
    for _ in range(100):
        holder = machine_lock_live_holder()
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
            singleton = _spawn_witness_daemon(port)
            orphan = _spawn_witness_daemon(port)
            foreign = _spawn_witness_daemon(foreign_port)
            procs = [singleton, orphan, foreign]

            # Each witness spawn is a shim launcher + worker pair; wait for both.
            matched = _wait_for_matched(port, count=2 * _PROCS_PER_DAEMON)
            singleton_pair = _pair_of(singleton.pid, matched)
            orphan_pair = _pair_of(orphan.pid, matched)

            # The singleton launcher is the recorded discovery-pointer pid.
            _write_service_status(singleton.pid, port)
            envelope = _reap_via_subprocess(port)
            assert envelope["ok"] is True, envelope

            _await_all_terminated(orphan_pair)
            assert all(_pid_terminated(pid) for pid in orphan_pair), (
                f"the whole orphan pair {orphan_pair} must be reaped"
            )
            assert all(_pid_live(pid) for pid in singleton_pair), (
                f"the singleton pair {singleton_pair} (pointer plus shim) "
                "must be spared"
            )
            assert _pid_live(foreign.pid), (
                "a daemon launched for a different port must be spared"
            )
        finally:
            reset_config()
            for proc in procs:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
            for straggler_port in (port, foreign_port):
                for pid in _orphan_daemon_pids(straggler_port):
                    with contextlib.suppress(Exception):
                        psutil.Process(pid).kill()

    def test_reap_spares_singleton_pair_when_worker_is_the_pointer(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
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
            singleton = _spawn_witness_daemon(port)
            orphan = _spawn_witness_daemon(port)
            procs = [singleton, orphan]
            matched = _wait_for_matched(port, count=2 * _PROCS_PER_DAEMON)
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
            assert all(_pid_terminated(pid) for pid in orphan_pair), (
                f"the whole orphan pair {orphan_pair} must be reaped"
            )
            assert all(_pid_live(pid) for pid in singleton_pair), (
                f"the singleton pair {singleton_pair} (worker + shim launcher) "
                "must be spared"
            )
        finally:
            reset_config()
            for proc in procs:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
            for pid in _orphan_daemon_pids(port):
                with contextlib.suppress(Exception):
                    psutil.Process(pid).kill()

    def test_reap_spares_the_lock_holding_singleton_without_a_pointer(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The no-pointer recovery scenario the ADR targets: the singleton holds
        # the machine lock but published NO service-status pointer, so the lock
        # anchor is the only thing sparing it. Proves machine_lock_live_holder
        # feeds the reap's anchor set, distinct from the pointer-anchored cases.
        monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
        monkeypatch.setenv(
            "VAULTSPEC_RAG_QDRANT_STORAGE_DIR", str(tmp_path / "qdrant" / "storage")
        )
        reset_config()

        port = free_loopback_port()
        procs: list[subprocess.Popen[bytes]] = []
        try:
            singleton = _spawn_lock_holding_daemon(port)
            orphan = _spawn_witness_daemon(port)
            procs = [singleton, orphan]
            matched = _wait_for_matched(port, count=2 * _PROCS_PER_DAEMON)
            singleton_pair = _pair_of(singleton.pid, matched)
            orphan_pair = _pair_of(orphan.pid, matched)

            # The lease holder is the singleton's worker; wait until it holds.
            holder = _wait_for_lock_holder(singleton_pair)
            assert holder in singleton_pair, (holder, singleton_pair)

            # No pointer written - only the machine-lock anchor protects.
            envelope = _reap_via_subprocess(port)
            assert envelope["ok"] is True, envelope

            _await_all_terminated(orphan_pair)
            assert all(_pid_terminated(pid) for pid in orphan_pair), (
                f"the whole orphan pair {orphan_pair} must be reaped"
            )
            assert all(_pid_live(pid) for pid in singleton_pair), (
                f"the lock-holding singleton pair {singleton_pair} must be "
                "spared by the machine-lock anchor alone"
            )
        finally:
            reset_config()
            for proc in procs:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
            for pid in _orphan_daemon_pids(port):
                with contextlib.suppress(Exception):
                    psutil.Process(pid).kill()
