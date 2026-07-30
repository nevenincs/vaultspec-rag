"""CPU-only adapter guards for the canonical service quiesce vocabulary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

_QUIESCED_BLOCK = {
    "state": "quiesced",
    "admission_epoch": 7,
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
}


def _run_mcp_service_state_probe(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Drive the MCP service-state tool through discovery and a real socket."""
    probe = r"""
import asyncio
import http.server
import json
import os
import sys
import threading
from pathlib import Path

base = Path(sys.argv[1])
status_dir = base / "status"
status_dir.mkdir()
workspace = base / "workspace"
(workspace / ".vault").mkdir(parents=True)
(workspace / ".vaultspec").mkdir()
os.environ["VAULTSPEC_RAG_STATUS_DIR"] = str(status_dir)
os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"] = str(base / "qdrant")

from vaultspec_rag.config._settings import reset_config

reset_config()

quiesce = {
    "state": "quiesced",
    "admission_epoch": 7,
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
}
service_state = {
    "index": {"status": "ready"},
    "projects": {"projects": []},
    "watcher": {"watching": []},
    "qdrant": {"alive": True},
    "quiesce": quiesce,
    "schema_version": 1,
}
body = json.dumps(service_state).encode("utf-8")


class ServiceStateResponder(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0] != "/service-state":
            self.send_response(404)
            self.end_headers()
            return
        token = self.headers.get("Authorization")
        assert token == "Bearer quiesce-adapter-token", token
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ServiceStateResponder)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    from vaultspec_rag.config._paths import SERVICE_STATUS_FILENAME
    from vaultspec_rag.serviceclient._compat import (
        SERVICE_VERSION_FIELD,
        local_package_version,
    )
    from vaultspec_rag.serviceclient._discovery import (
        SERVICE_DISCOVERY_SCHEMA,
        SERVICE_DISCOVERY_VERSION,
    )

    (status_dir / SERVICE_STATUS_FILENAME).write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "port": server.server_address[1],
                "schema": SERVICE_DISCOVERY_SCHEMA,
                "version": SERVICE_DISCOVERY_VERSION,
                SERVICE_VERSION_FIELD: local_package_version(),
                "service_token": "quiesce-adapter-token",
            }
        ),
        encoding="utf-8",
    )

    from vaultspec_rag.mcp._tools import get_index_status

    result = asyncio.run(get_index_status(project_root=str(workspace)))
    assert result == service_state, result
    forbidden = {"torch", "sentence_transformers", "transformers", "qdrant_client"}
    assert not forbidden.intersection(name.split(".", 1)[0] for name in sys.modules)
    print(json.dumps(result))
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd() / "src")
    return subprocess.run(
        [sys.executable, "-c", probe, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def test_mcp_service_state_keeps_the_canonical_quiesce_block_verbatim(
    tmp_path: Path,
) -> None:
    """MCP observes a bare service-state document without lifecycle inference.

    Mutation: wrap the successful service-state result in a new envelope.
    Exact equality fails, proving the adapter cannot hide, rename, or recreate
    the controller-owned quiesce block.
    """
    completed = _run_mcp_service_state_probe(tmp_path)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["quiesce"] == _QUIESCED_BLOCK
    assert set(result["quiesce"]) == set(_QUIESCED_BLOCK)
