"""CLI discovery and automatic service delegation coverage."""

from __future__ import annotations

import json
import typing

import pytest

from ._cli_helpers import (
    app,
    runner,
)

if typing.TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestAutoDelegation:
    """Verify CLI search and index auto-detect and delegate to a running service."""

    @staticmethod
    def _run_resolution_probe(tmp_path: Path, mode: str) -> dict[str, object]:
        """Run real discovery, search, and index routing in a fresh interpreter."""
        import subprocess
        import sys

        code = r"""
import http.server
import json
import os
import socket
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

root = Path(sys.argv[1])
mode = sys.argv[2]
target = root / "project"
status_dir = root / "status"
storage_dir = root / "qdrant-server" / "storage"
target.mkdir(parents=True)
(target / ".vaultspec").mkdir()
status_dir.mkdir()

os.environ["VAULTSPEC_RAG_STATUS_DIR"] = str(status_dir)
os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"] = str(storage_dir)
os.environ.pop("VAULTSPEC_RAG_LOCAL_ONLY", None)

from vaultspec_rag.tests._config_fixtures import reset_config  # absolute-import-ok

reset_config()


from vaultspec_rag._machine_lock import (  # absolute-import-ok
    acquire_machine_lock,
    machine_discovery_path,
    release_machine_lock,
)
from vaultspec_rag.serviceclient._compat import (  # absolute-import-ok
    SERVICE_VERSION_FIELD,
    local_package_version,
)

requests = []


class CaptureHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        requests.append({"path": self.path, "body": body})
        if self.path == "/search":
            payload = {"ok": True, "results": []}
            status = 200
        elif self.path == "/reindex":
            payload = {"ok": True, "job_id": "isolated-vault-job"}
            status = 200
        else:
            payload = {"ok": False, "error": "unexpected_endpoint"}
            status = 404
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        _ = format, args


capture_server = http.server.HTTPServer(("127.0.0.1", 0), CaptureHandler)
capture_thread = threading.Thread(target=capture_server.serve_forever, daemon=True)
nonselected_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
machine_lock_acquired = False
capture_thread_started = False

try:
    nonselected_socket.bind(("127.0.0.1", 0))
    capture_port = int(capture_server.server_address[1])
    nonselected_port = int(nonselected_socket.getsockname()[1])
    assert capture_port != nonselected_port

    if mode == "machine":
        machine_port = capture_port
        fallback_port = nonselected_port
    elif mode == "fallback":
        machine_port = nonselected_port
        fallback_port = capture_port
    else:
        raise AssertionError(f"unknown probe mode: {mode}")

    (status_dir / "service.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "port": fallback_port,
                "service_token": "fallback-token",
                SERVICE_VERSION_FIELD: local_package_version(),
            }
        ),
        encoding="utf-8",
    )

    if mode == "machine":
        machine_lock_acquired, holder = acquire_machine_lock()
        assert machine_lock_acquired, holder
        pointer = machine_discovery_path()
        pointer.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "port": machine_port,
                    "service_token": "machine-token",
                    "last_heartbeat": datetime.now(UTC).isoformat(timespec="seconds"),
                    "stale_after_s": 60,
                    SERVICE_VERSION_FIELD: local_package_version(),
                }
            ),
            encoding="utf-8",
        )

    capture_thread.start()
    capture_thread_started = True
    expected = machine_port if mode == "machine" else fallback_port
    initial_target_tree = sorted(
        str(path.relative_to(target)) for path in target.rglob("*")
    )
    assert initial_target_tree == [".vaultspec"]

    from vaultspec_rag.cli._index import (  # absolute-import-ok
        resolve_data_plane_service as index_resolve,
    )
    from vaultspec_rag.cli._search import (  # absolute-import-ok
        resolve_data_plane_service as search_resolve,
    )

    assert search_resolve().port == expected
    assert index_resolve().port == expected

    from typer.testing import CliRunner
    from vaultspec_rag.cli import app  # absolute-import-ok

    runner = CliRunner()
    search_result = runner.invoke(
        app,
        [
            "--target",
            str(target),
            "search",
            "anything",
            "--type",
            "code",
            "--json",
        ],
    )
    search_envelope = json.loads(search_result.output)
    assert search_result.exit_code == 0, search_result.output
    assert search_envelope["command"] == "search", search_envelope
    assert search_envelope["data"]["via"] == "service", search_envelope

    index_result = runner.invoke(
        app,
        [
            "--target",
            str(target),
            "index",
            "--type",
            "vault",
            "--json",
        ],
    )
    index_envelope = json.loads(index_result.output)
    assert index_result.exit_code == 0, index_result.output
    assert index_envelope["command"] == "index", index_envelope
    assert index_envelope["data"] == {
        "via": "service",
        "source": "vault",
        "outcome": {"ok": True, "job_id": "isolated-vault-job"},
    }, index_envelope

    assert requests == [
        {
            "path": "/search",
            "body": {
                "query": "anything",
                "top_k": 10,
                "project_root": str(target),
                "type": "code",
                "freshness_policy": "immediate",
            },
        },
        {
            "path": "/reindex",
            "body": {
                "type": "vault",
                "clean": False,
                "authority": "publication",
                "project_root": str(target),
                "initiator_kind": "cli",
            },
        },
    ], requests

    forbidden = (
        "torch",
        "sentence_transformers",
        "qdrant_client",
        "transformers",
        "onnxruntime",
    )
    heavy = sorted(
        module
        for module in sys.modules
        if any(module == name or module.startswith(name + ".") for name in forbidden)
    )
    assert not heavy, heavy
    final_target_tree = sorted(
        str(path.relative_to(target)) for path in target.rglob("*")
    )
    assert final_target_tree == initial_target_tree, final_target_tree
    print(
        json.dumps(
            {
                "mode": mode,
                "expected": expected,
                "machine_port": machine_port,
                "fallback_port": fallback_port,
                "capture_port": capture_port,
                "requests": requests,
                "search_via": search_envelope["data"]["via"],
                "index_via": index_envelope["data"]["via"],
                "heavy": heavy,
                "target_tree": final_target_tree,
            }
        )
    )
finally:
    if machine_lock_acquired:
        release_machine_lock()
    if capture_thread_started:
        capture_server.shutdown()
    capture_server.server_close()
    if capture_thread_started:
        capture_thread.join(timeout=5)
        assert not capture_thread.is_alive()
    nonselected_socket.close()
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path), mode],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return typing.cast("dict[str, object]", json.loads(result.stdout))

    @staticmethod
    def _assert_real_cli_routes(
        tmp_path: Path,
        evidence: dict[str, object],
    ) -> None:
        """Require both commands to use the selected real service endpoint."""
        assert evidence["capture_port"] == evidence["expected"]
        assert evidence["search_via"] == "service"
        assert evidence["index_via"] == "service"
        assert evidence["heavy"] == []
        assert evidence["target_tree"] == [".vaultspec"]
        requests = typing.cast("list[dict[str, object]]", evidence["requests"])
        assert [request["path"] for request in requests] == ["/search", "/reindex"]
        reindex = typing.cast("dict[str, object]", requests[1]["body"])
        assert reindex == {
            "type": "vault",
            "clean": False,
            "authority": "publication",
            "project_root": str(tmp_path / "project"),
            "initiator_kind": "cli",
        }

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_search_auto_delegates_when_service_running(self, tmp_path: Path) -> None:
        """A discovered, live daemon takes the search rather than the local path.

        Discovery is real end to end: a status record naming this process and a
        real port, a bound server answering /health with the token that record
        publishes, and the production identity check comparing the two. The
        substituted version asserted the CLI called a function someone replaced,
        which could not notice discovery moving - the sibling locked-store tests
        failed on exactly that, patching a symbol that had been relocated.

        Proven able to fail: removing the service record leaves nothing to
        discover, the CLI keeps the search local, and the request log stays
        empty (0 == 1).

        What this does NOT bind, checked rather than assumed: publishing a
        token the health server never serves still delegates. So the identity
        comparison is not exercised on this path, and claiming otherwise here
        would be a guard test asserting a branch it never reaches. That
        comparison has its own real coverage in the service-identity tests,
        which drive it against a bound /health and this process's own pid.
        """
        from ._cli_helpers import (
            _running_service_record,
            _search_output_contract_server,
        )

        (tmp_path / ".vaultspec").mkdir()
        server, thread, requests = _search_output_contract_server()
        try:
            port = server.server_address[1]
            with _running_service_record(tmp_path / "status", port):
                runner.invoke(
                    app,
                    ["--target", str(tmp_path), "search", "anything"],
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert len(requests) == 1

    def test_index_auto_delegates_when_service_running(self, tmp_path: Path) -> None:
        """A discovered, live daemon takes the index rather than running locally.

        Same real discovery as the search case: a status record naming this
        process and a real port, and a bound server that records what it was
        asked to do. The substituted version asserted the CLI called a function
        someone replaced, which could not notice discovery moving.

        Proven able to fail: removing the service record leaves nothing to
        discover, the CLI indexes locally, and the request log stays empty.
        """
        from ._cli_helpers import _reindex_contract_server, _running_service_record

        (tmp_path / ".vaultspec").mkdir()
        server, thread, requests = _reindex_contract_server()
        try:
            port = server.server_address[1]
            with _running_service_record(tmp_path / "status", port):
                runner.invoke(
                    app,
                    ["--target", str(tmp_path), "index", "--type", "vault"],
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert len(requests) == 1
        assert requests[0].get("type") == "vault"
        assert requests[0].get("initiator_kind") == "cli"

    def test_auto_delegation_prefers_machine_global_resolution(
        self, tmp_path: Path
    ) -> None:
        """A valid machine-global service outranks a conflicting status hint."""
        evidence = self._run_resolution_probe(tmp_path, "machine")
        self._assert_real_cli_routes(tmp_path, evidence)
        assert evidence["expected"] == evidence["machine_port"]
        assert evidence["expected"] != evidence["fallback_port"]

    def test_auto_delegation_uses_status_fallback_without_machine_service(
        self, tmp_path: Path
    ) -> None:
        """The real status file is used only when machine resolution is absent."""
        evidence = self._run_resolution_probe(tmp_path, "fallback")
        self._assert_real_cli_routes(tmp_path, evidence)
        assert evidence["expected"] == evidence["fallback_port"]
        assert evidence["expected"] != evidence["machine_port"]
