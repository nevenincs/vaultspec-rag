"""Integration tests for service daemon lifecycle.

Exercises real subprocess spawning, real GPU model loading, and real
Qdrant operations.  No mocks, patches, stubs, or skips.

Closes TESTGAP-001 (_terminate_pid), TESTGAP-002 (_spawn_service),
TESTGAP-003 (service_start), TESTGAP-004 (service_stop happy path),
TESTGAP-005 (service_status running), TESTGAP-009 (multi-project MCP).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from contextlib import suppress
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from ...cli import app
from ._helpers import (
    _get_ephemeral_port,
    _service_env,
    _wait_for_exit,
)

if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()

pytestmark = [pytest.mark.integration]


def _json_envelopes(output: str) -> list[dict[str, object]]:
    """Return every structured outcome envelope found in *output*.

    The broker contract is "exactly one envelope per exit path", so the count
    matters as much as the content and the caller asserts on it. Scanning for
    every parseable envelope - rather than taking the first or last line that
    looks like one - is what lets a second envelope be caught instead of
    silently discarded.
    """
    envelopes: list[dict[str, object]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            parsed = cast("dict[str, object]", json.loads(stripped))
        except json.JSONDecodeError:
            continue
        if "ok" in parsed:
            envelopes.append(parsed)
    return envelopes


def _spawn_reap_witness(port: int) -> subprocess.Popen[bytes]:
    """Spawn a harmless sleeper whose command line carries the launch witness.

    The witness tokens ride as trailing argv to ``-c``, so the process
    enumerates with the daemon's launch signature without importing the daemon
    or touching a GPU. It sleeps far longer than one host-wide command-line
    sweep costs, because a process that exits mid-sweep is dropped from the
    enumeration and the test would then be asserting against an empty match.
    Spawned into its own group or session, as the real detached daemon is, so
    the reap's termination cannot cascade back into this test process.
    """
    argv = [
        sys.executable,
        "-c",
        "import time; time.sleep(600)",
        "-m",
        "vaultspec_rag.server",
        "--port",
        str(port),
    ]
    if sys.platform == "win32":
        return subprocess.Popen(argv, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(argv, start_new_session=True)


def _witness_tree(launcher_pid: int, port: int, timeout: float = 10.0) -> set[int]:
    """Return the witness-carrying pids one spawn produced, launcher included.

    Read from the launcher's own child list rather than from a host-wide
    command-line sweep. The sweep is what the reap itself does, it costs tens of
    seconds, and it is therefore useless for observing something the test just
    spawned. A Windows venv launcher re-execs the real interpreter, so a second
    pid appears within milliseconds carrying an identical command line; the loop
    waits for that pid and returns on the first sample that shows it.
    """
    import psutil

    marker = ("-m", "vaultspec_rag.server", "--port", str(port))
    deadline = time.monotonic() + timeout
    found: set[int] = set()
    while time.monotonic() < deadline:
        try:
            launcher = psutil.Process(launcher_pid)
            found.add(launcher_pid)
            for child in launcher.children(recursive=True):
                try:
                    argv = tuple(child.cmdline())
                except psutil.Error:
                    continue
                if all(token in argv for token in marker):
                    found.add(child.pid)
        except psutil.Error:
            break
        if len(found) > 1 or sys.platform != "win32":
            break
        time.sleep(0.05)
    return found


# One host-wide command-line sweep is the reap's dominant cost. It ran into
# tens of seconds while the sweep read every process's parent pid eagerly - a
# full-system snapshot per process on Windows - and now lands in a few seconds
# because that attribute is read only for processes whose command line already
# matched. The budget stays well above both figures on purpose: it is a ceiling
# a passing reap never spends, so headroom costs nothing, whereas too little of
# it kills the guard on `TimeoutExpired` before any assertion runs.
_REAP_SUBPROCESS_BUDGET_SECONDS = 240.0


class TestOrphanReapStructuredStop:
    """The orphan reap answers to the same structured-stop contract as its peers.

    ``server stop --orphans`` is a lifecycle verb a supervising broker drives, so
    it owes the same envelope discipline the other stop outcomes already keep:
    one envelope per exit path in ``--json`` mode, none in human mode, an
    already-satisfied request as a success rather than a fault, and a non-zero
    exit only where the requested state was not achieved.

    Every test here pins the reap to an explicit ephemeral port under isolated
    singleton paths. That is a safety property, not a convenience: the port is
    the reap's blast radius.
    """

    def test_nothing_to_reap_is_one_idempotent_success_envelope(
        self, tmp_path: Path
    ) -> None:
        # The broker's idempotent case: asked to clear orphans where there are
        # none, the reap reports success rather than a fault a supervisor would
        # have to special-case.
        port = _get_ephemeral_port()
        with _service_env(tmp_path):
            result = runner.invoke(
                app, ["server", "stop", "--orphans", "--port", str(port), "--json"]
            )
        assert result.exit_code == 0, result.output
        envelopes = _json_envelopes(result.stdout)
        assert len(envelopes) == 1, f"expected one envelope, got: {result.stdout!r}"
        envelope = envelopes[0]
        assert envelope["ok"] is True
        assert envelope["command"] == "service.stop"
        data = cast("dict[str, object]", envelope["data"])
        assert data["status"] == "reaped"
        assert data["reaped"] == 0
        assert data["reaped_pids"] == []
        assert data["port"] == port
        # The reap is a terminating outcome, so it carries the same initiator
        # attribution the other terminating stops do - "who cleared the machine"
        # is answerable from the envelope alone.
        assert data["initiator_pid"] == str(os.getpid())
        assert data["initiator_cwd"] == os.getcwd()

    def test_human_mode_reap_emits_no_envelope(self, tmp_path: Path) -> None:
        # The mode split: human output never leaks a machine envelope, and the
        # satisfied no-op still exits 0.
        port = _get_ephemeral_port()
        with _service_env(tmp_path):
            result = runner.invoke(
                app, ["server", "stop", "--orphans", "--port", str(port)]
            )
        assert result.exit_code == 0, result.output
        assert _json_envelopes(result.stdout) == []
        assert str(port) in result.stdout

    def test_unresolvable_port_refuses_instead_of_defaulting(
        self, tmp_path: Path
    ) -> None:
        # Without --port the reap resolves its own scope, and when it cannot it
        # must REFUSE. Falling back to a shared default here would aim a
        # terminating sweep at whatever service happens to hold that port on the
        # machine, which is the one outcome a scoped reap exists to prevent.
        with _service_env(tmp_path):
            result = runner.invoke(app, ["server", "stop", "--orphans", "--json"])
        assert result.exit_code == 1, result.output
        envelopes = _json_envelopes(result.stdout)
        assert len(envelopes) == 1, f"expected one envelope, got: {result.stdout!r}"
        envelope = envelopes[0]
        assert envelope["ok"] is False
        assert envelope["command"] == "service.stop"
        assert envelope["error"] == "port_unresolved"

    def test_real_reap_emits_one_terminating_envelope_naming_its_pids(
        self, tmp_path: Path
    ) -> None:
        # The terminating success path end to end, and specifically whether the
        # envelope TELLS THE TRUTH: its count matches its pid list, every pid it
        # names is really gone afterwards, and at least one of them belongs to
        # the daemon this test spawned.
        #
        # It deliberately does not require the report to name the WHOLE spawned
        # pair. Whether a shim launcher is cleared alongside its worker belongs
        # to the reap-safety suite, which asserts it against the processes
        # themselves; requiring it again here would duplicate that coverage and
        # bind an envelope test to enumeration completeness.
        #
        # The reap runs OUT of process: the witness is this test's own child,
        # and an in-process reap would spare it as the descendant of an anchor -
        # a confound absent in production, where the reap is never the orphans'
        # parent.
        port = _get_ephemeral_port()
        with _service_env(tmp_path):
            witness = _spawn_reap_witness(port)
            spawned: set[int] = set()
            try:
                spawned = _witness_tree(witness.pid, port)
                assert spawned, "the witness daemon did not materialise"
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
                assert completed.returncode == 0, completed.stdout + completed.stderr
                envelopes = _json_envelopes(completed.stdout)
                assert len(envelopes) == 1, (
                    f"expected one envelope, got: {completed.stdout!r}"
                )
                envelope = envelopes[0]
                assert envelope["ok"] is True
                assert envelope["command"] == "service.stop"
                data = cast("dict[str, object]", envelope["data"])
                assert data["status"] == "reaped"
                assert cast("int", data["reaped"]) >= 1
                reaped_pids = cast("list[int]", data["reaped_pids"])
                assert len(reaped_pids) == data["reaped"], (
                    f"the count {data['reaped']} disagrees with the pid list "
                    f"{reaped_pids}"
                )
                assert set(reaped_pids) & spawned, (
                    f"the reaped pids {reaped_pids} name none of the daemon "
                    f"this test spawned ({sorted(spawned)})"
                )
                for pid in reaped_pids:
                    assert _wait_for_exit(pid, timeout=30.0), (
                        f"the envelope reported pid {pid} reaped, but it is alive"
                    )
                assert data["port"] == port
                assert data["initiator_pid"] not in {"", str(os.getpid())}
            finally:
                # Clear the whole spawned tree, not just the pid Popen holds: a
                # reap that took the worker and left its shim launcher would
                # otherwise strand a witness for the rest of the session, where
                # it enumerates into every later sweep. Killed by pid rather
                # than by console-group signal - the worker is not a group
                # leader, and a stray CTRL_BREAK would reach this test run's own
                # console.
                import psutil

                for pid in spawned:
                    with suppress(psutil.Error):
                        psutil.Process(pid).kill()
                if witness.poll() is None:
                    witness.kill()
                    witness.wait(timeout=10)
