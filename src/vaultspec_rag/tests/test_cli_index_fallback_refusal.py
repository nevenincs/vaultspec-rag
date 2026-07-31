"""CPU-only guards against local indexing after delegated refusals."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]


def _run_delegation_refusal_probe(
    tmp_path: Path,
    mode: str,
) -> subprocess.CompletedProcess[str]:
    """Run the real CLI against an unavailable or quiesced delegated endpoint."""
    probe = r"""
import http.server
import json
import socket
import sys
import threading
from pathlib import Path

from typer.testing import CliRunner
from vaultspec_rag.cli import app

root = Path(sys.argv[1])
mode = sys.argv[2]
target = root / "project"
target.mkdir()
(target / ".vaultspec").mkdir()

listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.bind(("127.0.0.1", 0))
port = int(listener.getsockname()[1])

server = None
thread = None
if mode == "quiesced":
    envelope = {
        "ok": False,
        "error": "quiesce_admission_closed",
        "message": "service-owned admission refusal",
        "quiesce": {
            "state": "quiesced",
            "admission_epoch": 4,
            "admissions_open": False,
            "active_compute_tickets": 0,
            "drain_complete": True,
            "vram_released": True,
            "safe_to_borrow_gpu": True,
            "pause_requested_at": 100.0,
            "drain_acknowledged_at": 101.0,
            "quiesced_at": 102.0,
            "warming_started_at": None,
            "failure_reason": None,
        },
    }

    class RefusalHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            encoded = json.dumps(envelope).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format, *args):
            del format, args

    listener.close()
    server = http.server.HTTPServer(("127.0.0.1", port), RefusalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
elif mode in {"dead", "dead_human"}:
    listener.close()
else:
    raise AssertionError(f"unknown mode: {mode}")

heavy_before = {
    name
    for name in sys.modules
    if name.split(".", 1)[0]
    in {"torch", "sentence_transformers", "transformers", "qdrant_client"}
}
try:
    result = CliRunner().invoke(
        app,
        [
            "--target",
            str(target),
            "index",
            "--type",
            "vault",
            "--port",
            str(port),
            *( ["--json"] if mode != "dead_human" else [] ),
        ],
        terminal_width=200,
    )
finally:
    if server is not None:
        server.shutdown()
        server.server_close()
    if thread is not None:
        thread.join(timeout=5)
        assert not thread.is_alive()

heavy_after = {
    name
    for name in sys.modules
    if name.split(".", 1)[0]
    in {"torch", "sentence_transformers", "transformers", "qdrant_client"}
}
assert heavy_after == heavy_before, (heavy_before, heavy_after)
print(
    json.dumps(
        {"exit_code": result.exit_code, "port": port, "output": result.output}
    )
)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd() / "src")
    return subprocess.run(
        [sys.executable, "-c", probe, str(tmp_path), mode],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def test_delegation_refuses_a_dead_port_without_local_imports(
    tmp_path: Path,
) -> None:
    """A selected but unreachable service cannot authorize local indexing."""
    completed = _run_delegation_refusal_probe(tmp_path, "dead")

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["exit_code"] == 1
    payload = json.loads(result["output"])
    assert payload == {
        "ok": False,
        "command": "indexing",
        "error": "port_unreachable",
        "message": (
            f"Service on port {result['port']} is unreachable. Local indexing "
            "requires a borrower lease and a verified safe service condition."
        ),
        "port": result["port"],
        "remediation": [
            "vaultspec-rag server status",
            "vaultspec-rag server start",
        ],
    }


def test_dead_delegated_port_has_no_local_fallback_hint_in_human_output(
    tmp_path: Path,
) -> None:
    """The human refusal names only the safe service recovery actions."""
    completed = _run_delegation_refusal_probe(tmp_path, "dead_human")

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["exit_code"] == 1
    assert result["output"].splitlines() == [
        f"Service on port {result['port']} is unreachable.",
        (
            "Local indexing requires a borrower lease and a verified safe service "
            "condition."
        ),
        "Next actions:",
        "  1. Check status:  vaultspec-rag server status",
        "  2. Start service: vaultspec-rag server start",
    ]


def test_quiesced_delegated_refusal_never_authorizes_local_indexing(
    tmp_path: Path,
) -> None:
    """A service-owned quiesced refusal remains a service failure, not a loan."""
    completed = _run_delegation_refusal_probe(tmp_path, "quiesced")

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["exit_code"] == 1
    payload = json.loads(result["output"])
    assert payload["ok"] is False
    assert payload["error"] == "quiesce_admission_closed"
    assert payload["message"] == "service-owned admission refusal"
