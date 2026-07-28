"""End-to-end tests for the stdio shim: served capability plus lifetime.

The functional assertion floor (issue #232, mirroring the companion core
repo's adopted contract): every test that spawns the real shim asserts at
least one measurable served capability - the initialize handshake, the
exact five-tool surface, or a structurally-asserted tool result - over the
actual line-delimited JSON-RPC stdio transport, never process existence
alone. The lifetime scenarios (issue #229) then compose on top:

- client-kill: an intermediary client proves the shim serves (handshake +
  tools/list), then dies; the pipe-creator anchor must reap the shim
  immediately - no grace window applies to precise anchors.
- EOF-still-primary: the served shim exits cleanly when stdin closes.
- degraded tool call: with the daemon unreachable, ``search_vault`` must
  return its service-down guidance THROUGH the wire.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import sysconfig
import time
from pathlib import Path
from typing import Any, cast

import pytest

pytestmark = [pytest.mark.integration]

EXPECTED_TOOLS = {
    "clean_all",
    "clean_documents",
    "get_code_file",
    "get_index_status",
    "reindex_all",
    "reindex_codebase",
    "reindex_documents",
    "reindex_vault",
    "search_codebase",
    "search_combined",
    "search_documents",
    "search_vault",
}

_SHIM_CMD = [sys.executable, "-c", "from vaultspec_rag.server import main; main()"]


def _spawn_shim(env: dict[str, str] | None = None) -> subprocess.Popen[bytes]:
    merged = dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.Popen(
        _SHIM_CMD,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=merged,
    )


def _send(shim: subprocess.Popen[bytes], message: dict[str, Any]) -> None:
    assert shim.stdin is not None
    shim.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
    shim.stdin.flush()


def _recv(
    shim: subprocess.Popen[bytes], want_id: int, timeout: float = 60.0
) -> dict[str, Any]:
    """Read line-delimited JSON-RPC until the response with ``want_id``."""
    assert shim.stdout is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = shim.stdout.readline()
        if not line:
            raise AssertionError(
                "shim closed stdout before responding; stderr tail: "
                + (shim.stderr.read() if shim.stderr else b"").decode(errors="replace")[
                    -2000:
                ]
            )
        try:
            message = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            continue
        if message.get("id") == want_id:
            return message
    raise AssertionError(f"no response with id {want_id} within {timeout}s")


def _handshake(shim: subprocess.Popen[bytes]) -> dict[str, Any]:
    """initialize -> initialized; returns the server's initialize result."""
    _send(
        shim,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "rag-e2e-harness", "version": "0"},
            },
        },
    )
    response = _recv(shim, 1)
    assert "result" in response, response
    return response["result"]


def _initialized(shim: subprocess.Popen[bytes]) -> None:
    # The notification carries no id; the next request's response proves it
    # was consumed.
    _send(shim, {"jsonrpc": "2.0", "method": "notifications/initialized"})


def _list_tool_names(shim: subprocess.Popen[bytes], request_id: int = 2) -> set[str]:
    _send(shim, {"jsonrpc": "2.0", "id": request_id, "method": "tools/list"})
    response = _recv(shim, request_id)
    assert "result" in response, response
    return {tool["name"] for tool in response["result"]["tools"]}


def test_shim_serves_the_five_tool_surface_then_exits_on_eof() -> None:
    """The floor for the EOF scenario: prove serving, then prove shutdown."""
    shim = _spawn_shim()
    try:
        init = _handshake(shim)
        assert init["serverInfo"]["name"] == "VaultSpec Search"
        _initialized(shim)
        assert _list_tool_names(shim) == EXPECTED_TOOLS

        assert shim.stdin is not None
        shim.stdin.close()
        assert shim.wait(timeout=60) == 0
    finally:
        if shim.poll() is None:
            shim.kill()


def test_degraded_search_vault_reports_service_down_through_the_wire(
    tmp_path: Path,
) -> None:
    """A tool call must produce correct degraded-mode guidance on the wire."""
    # Full machine isolation: discovery is authoritative on the machine
    # singleton (derived from the qdrant storage dir), so the status dir
    # alone would still find a live resident service on this machine.
    shim = _spawn_shim(
        {
            "VAULTSPEC_RAG_STATUS_DIR": str(tmp_path / "status"),
            "VAULTSPEC_RAG_QDRANT_STORAGE_DIR": str(
                tmp_path / "qdrant-server" / "storage"
            ),
            "VAULTSPEC_RAG_PORT": "59999",
            "VAULTSPEC_RAG_ROOT": str(tmp_path),
        }
    )
    try:
        _handshake(shim)
        _initialized(shim)
        _send(
            shim,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "search_vault",
                    "arguments": {"query": "anything at all"},
                },
            },
        )
        response = _recv(shim, 3, timeout=90)
        assert "result" in response, response
        content = cast("list[Any]", response["result"]["content"])
        text = " ".join(
            str(cast("dict[str, Any]", block).get("text", ""))
            for block in content
            if isinstance(block, dict)
        )
        assert (
            "is not running" in text
            or "not reachable" in text.lower()
            or ("server start" in text)
        ), f"degraded guidance missing from wire payload: {text[:500]}"
    finally:
        if shim.poll() is None:
            shim.kill()


_CLIENT_SCRIPT = """
import json
import subprocess
import sys
import time
from pathlib import Path

shim = subprocess.Popen(
    [sys.executable, "-c", "from vaultspec_rag.server import main; main()"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
)

def send(message):
    shim.stdin.write((json.dumps(message) + "\\n").encode("utf-8"))
    shim.stdin.flush()

def recv(want_id):
    while True:
        line = shim.stdout.readline()
        if not line:
            raise SystemExit("shim closed stdout during handshake")
        try:
            message = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            continue
        if message.get("id") == want_id:
            return message

send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {},
    "clientInfo": {"name": "kill-test-client", "version": "0"}}})
recv(1)
send({"jsonrpc": "2.0", "method": "notifications/initialized"})
send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
tools = {t["name"] for t in recv(2)["result"]["tools"]}
Path(sys.argv[1]).write_text(
    json.dumps({"shim_pid": shim.pid, "tools": sorted(tools)}), encoding="utf-8"
)
time.sleep(120)
"""


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        from ...server._stdio_lifetime import _kernel32, _open_process

        handle = _open_process(pid)
        if handle is None:
            return False
        try:
            # 0x102 = WAIT_TIMEOUT: still running.
            return _kernel32.WaitForSingleObject(handle, 0) == 0x102
        finally:
            _kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_shim_reaps_instantly_when_its_serving_client_dies(tmp_path: Path) -> None:
    """Served capability + exact-client reap in one real-process scenario.

    The intermediary client spawns the real shim over pipes (so IT is the
    stdin pipe creator - the precise anchor), proves the shim serves the
    five-tool surface, then idles; killing it must reap the shim without
    waiting out any grace window, because precise anchors are never
    grace-pruned.
    """
    client_py = tmp_path / "client.py"
    client_py.write_text(_CLIENT_SCRIPT, encoding="utf-8")
    report_file = tmp_path / "report.json"

    client = subprocess.Popen([sys.executable, str(client_py), str(report_file)])
    try:
        deadline = time.monotonic() + 60
        while not report_file.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        assert report_file.exists(), "client never completed the shim handshake"
        report = json.loads(report_file.read_text(encoding="utf-8"))
        assert set(report["tools"]) == EXPECTED_TOOLS, report
        shim_pid = int(report["shim_pid"])
        assert _pid_alive(shim_pid)

        client.kill()
        client.wait(timeout=15)

        # Precise anchor: no grace window applies; allow only process
        # scheduling slack, far below the 10s fallback grace.
        deadline = time.monotonic() + 8
        while _pid_alive(shim_pid) and time.monotonic() < deadline:
            time.sleep(0.25)
        assert not _pid_alive(shim_pid), (
            "shim survived its client's death; the pipe-creator anchor never fired"
        )
    finally:
        if client.poll() is None:
            client.kill()
        if report_file.exists():
            leftover = int(
                json.loads(report_file.read_text(encoding="utf-8"))["shim_pid"]
            )
            if _pid_alive(leftover) and sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(leftover)],
                    capture_output=True,
                    check=False,
                )


# First generation: spawns the second and exits at once. Its death is what
# truncates the orphan's ancestor walk below the (immortal) pytest process;
# without it the walk finds a live anchor and correctly never re-arms.
# argv: [1] second-generation source, [2] interpreter for the orphan,
# [3] orphan source, [4] pid file, [5] stderr log, [6] grace seconds,
# [7] re-arm seconds.
_FIRST_LAUNCHER = """
import os
import subprocess
import sys

subprocess.Popen(
    [sys.executable, "-c", sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4],
     sys.argv[5], str(os.getpid()), sys.argv[6], sys.argv[7]],
    stdin=subprocess.DEVNULL,
)
"""

# Second generation: waits out the first, spawns the orphan, then exits the
# moment the orphan reports its watchdog installed - inside the grace
# window, so every discovered ancestor is pruned as a transient spawn
# helper. Leaving on the orphan's own signal rather than a fixed sleep is
# what keeps that ordering deterministic: the window it has to beat starts
# at the install this waits for, so shortening the window cannot narrow the
# margin. argv: [1] interpreter, [2] orphan source, [3] pid file,
# [4] stderr log, [5] first-generation pid, [6] grace seconds,
# [7] re-arm seconds.
_SECOND_LAUNCHER = """
import subprocess
import sys
import time
from pathlib import Path

from vaultspec_rag.server import _stdio_lifetime as w  # absolute-import-ok

first_pid = int(sys.argv[5])
deadline = time.monotonic() + 60
while first_pid in w._snapshot_processes()[0] and time.monotonic() < deadline:
    time.sleep(0.2)

pid_file = Path(sys.argv[3])
with open(sys.argv[4], "w", encoding="utf-8") as log:
    subprocess.Popen(
        [sys.argv[1], "-c", sys.argv[2], sys.argv[3], sys.argv[6], sys.argv[7]],
        stdin=subprocess.DEVNULL,
        stderr=log,
    )
    deadline = time.monotonic() + 60
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
"""

# The orphan: installs the real watchdog, then blocks forever WITHOUT ever
# reading stdin - the reported shape exactly, where the client's inherited
# write handle outlives it so EOF never arrives. Both intervals are handed
# in shortened; the state machine they pace is the shipped one, untouched.
# The pid file is published by rename so neither poller can read it empty.
# argv: [1] pid file, [2] grace seconds, [3] re-arm seconds.
_ORPHAN_WORKER = """
import os
import sys
import time
from pathlib import Path

from vaultspec_rag.server import _stdio_lifetime as w  # absolute-import-ok

w._REARM_SECONDS = float(sys.argv[3])
w.install_stdio_lifetime_watchdog(grace_seconds=float(sys.argv[2]))
pid_file = Path(sys.argv[1])
staged = pid_file.with_suffix(".staged")
staged.write_text(str(os.getpid()), encoding="utf-8")
os.replace(staged, pid_file)
time.sleep(600)
"""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ancestry semantics")
def test_orphaned_shim_reaps_itself_once_its_whole_chain_is_gone(
    tmp_path: Path,
) -> None:
    """The reported leak: every ancestor gone, and the process survives.

    Reproducing it needs two launcher generations and a trampoline-free
    interpreter for the orphan itself. The first generation exits before
    the orphan starts, so the ancestor walk breaks there instead of
    reaching pytest; the second exits inside the grace window, so the whole
    discovered chain is pruned as transient. The orphan runs under the base
    interpreter because a venv ``python.exe`` is a uv trampoline that stays
    resident as the child's parent - a permanent live anchor, and one that
    takes the child down with it when killed, so no orphan could form
    beneath it.

    The structured stderr events are the proof of MECHANISM: without them a
    worker that merely died with its launcher would pass, and they are what
    lets the two interval constants be shortened below without weakening
    anything - the events show the full shipped count of confirming rounds
    ran before the reap.
    """
    from ...server._stdio_lifetime import (
        _GRACE_SECONDS,
        _ORPHAN_CONFIRM_ROUNDS,
        _REARM_SECONDS,
    )

    # The orphan gets shortened intervals. What is under test is the state
    # machine - the discovered chain pruned as transient, re-discovery
    # finding nothing above, the reap withheld until _ORPHAN_CONFIRM_ROUNDS
    # consecutive rounds agree - and no step of it reads the clock for
    # anything but how long to sleep between rounds. The shipped cadence is
    # ~55s of pure sleep per run, which bought no assertion the events do
    # not already make. The round COUNT is deliberately not shortened: it is
    # mechanism, not pacing.
    grace_seconds = 5.0
    rearm_seconds = 2.0

    # The one thing waiting out the real cadence did cover: a shipped
    # cadence so slow the backstop fires long after an operator has written
    # the shim off. That is a property of the constants, so assert it
    # directly instead of spending a minute of sleep re-observing it.
    assert _GRACE_SECONDS + _REARM_SECONDS * _ORPHAN_CONFIRM_ROUNDS <= 120.0

    base_python = getattr(sys, "_base_executable", None) or sys.executable
    src_root = Path(__file__).resolve().parents[3]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (
            str(src_root),
            sysconfig.get_paths()["purelib"],
            env.get("PYTHONPATH"),
        )
        if part
    )

    pid_file = tmp_path / "orphan.pid"
    log_file = tmp_path / "orphan.stderr"
    first = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _FIRST_LAUNCHER,
            _SECOND_LAUNCHER,
            base_python,
            _ORPHAN_WORKER,
            str(pid_file),
            str(log_file),
            str(grace_seconds),
            str(rearm_seconds),
        ],
        stdin=subprocess.DEVNULL,
        env=env,
    )
    first.wait(timeout=60)

    deadline = time.monotonic() + 90
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert pid_file.exists(), "the orphan worker never started; stderr: " + (
        log_file.read_text(encoding="utf-8") if log_file.exists() else "(none)"
    )
    orphan_pid = int(pid_file.read_text(encoding="utf-8"))

    try:
        assert _pid_alive(orphan_pid)

        budget = grace_seconds + rearm_seconds * (_ORPHAN_CONFIRM_ROUNDS + 2) + 30.0
        deadline = time.monotonic() + budget
        while _pid_alive(orphan_pid) and time.monotonic() < deadline:
            time.sleep(0.25)
        events = [
            json.loads(line)
            for line in log_file.read_text(encoding="utf-8").splitlines()
            if line.startswith("{")
        ]
        assert not _pid_alive(orphan_pid), (
            f"orphaned worker {orphan_pid} survived {budget:.0f}s with no live "
            f"ancestor; the watchdog disarmed instead of re-arming. Events: "
            f"{events}"
        )

        kinds = [event.get("event") for event in events]
        assert "stdio_watchdog_unanchored" in kinds, (
            f"the orphan never reported losing its anchor: {kinds}"
        )
        assert kinds[-1] == "stdio_watchdog_exit", (
            f"the orphan died without reaping itself: {kinds}"
        )

        # The reap must follow a full run of CONSECUTIVE confirming rounds,
        # numbered from zero: the counter restarting on a live-but-unopenable
        # ancestor (or a recycled pid slot) is the safety valve that keeps a
        # live session from being reaped, so a reap that never counted up to
        # the shipped total means the valve is not holding. A benign restart
        # mid-run is tolerated; only the run ending in the reap is asserted.
        unanchored = [
            event
            for event in events
            if event.get("event") == "stdio_watchdog_unanchored"
        ]
        rounds = [event.get("round") for event in unanchored]
        confirming_run = list(range(_ORPHAN_CONFIRM_ROUNDS))
        assert rounds[-_ORPHAN_CONFIRM_ROUNDS:] == confirming_run, (
            f"the reap did not follow {_ORPHAN_CONFIRM_ROUNDS} consecutive "
            f"confirming rounds: {rounds}"
        )
        totals = {event.get("reap_after_rounds") for event in unanchored}
        assert totals == {_ORPHAN_CONFIRM_ROUNDS}, (
            f"the orphan counted toward a different total than the shipped "
            f"{_ORPHAN_CONFIRM_ROUNDS}: {totals}"
        )
    finally:
        if _pid_alive(orphan_pid):
            subprocess.run(
                ["taskkill", "/F", "/PID", str(orphan_pid)],
                capture_output=True,
                check=False,
            )
