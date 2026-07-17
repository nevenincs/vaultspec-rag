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
import time
from typing import TYPE_CHECKING, Any, cast

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration]

EXPECTED_TOOLS = {
    "search_vault",
    "search_codebase",
    "get_code_file",
    "reindex_vault",
    "reindex_codebase",
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
        content = cast("list[dict[str, Any]]", response["result"]["content"])
        text = " ".join(
            str(block.get("text", "")) for block in content if isinstance(block, dict)
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
