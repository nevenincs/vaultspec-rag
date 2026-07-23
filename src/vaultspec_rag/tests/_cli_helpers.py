"""Shared fixtures, helpers, and HTTP contract servers for the CLI test suite."""

from __future__ import annotations

import contextlib
import json
import os
import re
import typing

from typer.testing import CliRunner
from vaultspec_core.config import (  # pyright: ignore[reportMissingTypeStubs]
    reset_config as reset_base_config,
)

from ..cli import (
    _display_search_results,
    _display_service_error,
    _is_our_service,
    _is_pid_alive,
    _read_service_status,
    _try_http_search,
    _write_service_status,
    app,
)
from ..cli._http_search import DEFAULT_SEARCH_TIMEOUT_SECONDS, _get_search_timeout
from ..config import EnvVar
from ..config import reset_config as reset_rag_config
from ..torch_config import TorchConfigAction

if typing.TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")
_SEARCH_RECORD_RE = re.compile(
    r"^(?P<number>\d+)\. "
    r"(?P<location>\S+)"
    r"(?: \(score (?P<score>\d+\.\d{4})\))?$"
)


def _plain_lines(output: str) -> list[str]:
    clean = _ANSI_RE.sub("", output)
    return [line.strip() for line in clean.splitlines() if line.strip()]


def _label_values(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _plain_lines(output):
        if ": " in line:
            label, value = line.split(": ", 1)
            values[label] = value
    return values


def _section_label_values(output: str, section: str) -> dict[str, str]:
    lines = _plain_lines(output)
    try:
        start = lines.index(f"{section}:") + 1
    except ValueError as exc:
        raise AssertionError(f"Missing section {section!r}") from exc

    values: dict[str, str] = {}
    for line in lines[start:]:
        if not line.startswith(("Operation:", "Project:", "Runtime:", "Progress:")):
            break
        label, value = line.split(": ", 1)
        values[label] = value
    return values


def _assert_default_status_summary(output: str, port: int) -> None:
    labels = _label_values(output)
    assert labels["Server"] == "running"
    assert labels["Requests"] == "ready for requests"
    assert "Health" not in labels
    assert labels["Busy"] == "processing 1 job"
    assert labels["Address"] == f"http://127.0.0.1:{port}"
    assert labels["Uptime"] == "5 minutes 12 seconds"
    assert labels["Queue"] == "nothing waiting; 1 active job"
    assert labels["Processed jobs"] == "2 finished, 1 active, 0 waiting, 0 failed"
    job = _section_label_values(output, "Current job")
    assert job["Operation"] == "code index refresh"
    assert job["Project"] == "feature-server-supervision"
    assert re.fullmatch(r"\d+ seconds?", job["Runtime"])
    assert job["Progress"] == "embedding source code sections 7 of 20"
    lines = _plain_lines(output)
    next_action_index = lines.index("Next action:")
    assert lines[next_action_index + 1] == "vaultspec-rag server jobs --state active"
    _assert_no_table_borders(output)
    assert max(len(line) for line in output.splitlines()) <= 100


def _assert_verbose_status_summary(output: str, port: int) -> None:
    lines = _plain_lines(output)
    assert lines[0] == "Service status"
    labels = _label_values(output)
    expected_labels = {
        "Local record": "found",
        "Process ID": str(os.getpid()),
        "Address": f"http://127.0.0.1:{port}",
        "Process": "running",
        "Process check": "verified",
        "Identity check": "not verified by this status check",
        "Network": "accepting connections",
        "Server": "running",
        "Requests": "ready for requests",
        "Compute": "GPU available",
        "Search models": "ready",
        "Reranking": "ready",
    }
    for label, value in expected_labels.items():
        assert labels[label] == value
    for absent in ("State", "Health"):
        assert absent not in labels
    assert re.search(r"\d+ local time", labels["Started"])
    job = _section_label_values(output, "Current job")
    expected_job = {
        "Operation": "code index refresh",
        "Project": "feature-server-supervision",
        "Progress": "embedding source code sections 7 of 20",
    }
    for label, value in expected_job.items():
        assert job[label] == value
    assert re.fullmatch(r"\d+ seconds?", job["Runtime"])
    next_action_index = lines.index("Next action:")
    assert lines[next_action_index + 1] == "vaultspec-rag server jobs --state active"
    _assert_no_table_borders(output)


def _search_records(output: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    text_lines: list[str] = []
    for line in _plain_lines(output):
        match = _SEARCH_RECORD_RE.fullmatch(line)
        if match is not None:
            if current is not None:
                current["text"] = "\n".join(text_lines)
                records.append(current)
            current = {
                "number": int(match.group("number")),
                "location": match.group("location"),
                "score": match.group("score"),
                "text": "",
            }
            text_lines = []
            continue
        assert current is not None, f"Expected search record header, got {line!r}"
        text_lines.append(line)
    if current is not None:
        current["text"] = "\n".join(text_lines)
        records.append(current)
    return records


def _assert_no_table_borders(output: str) -> None:
    assert not any(glyph in output for glyph in ("─", "│", "┌", "┐", "└", "┘"))


def _help_option_descriptions(output: str) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    active_options: list[str] = []
    for raw_line in _ANSI_RE.sub("", output).splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            active_options = []
            continue

        if stripped.startswith("--"):
            parts = re.split(r"\s{2,}", stripped, maxsplit=1)
            active_options = re.findall(r"--[a-z0-9-]+", parts[0])
            description = parts[1] if len(parts) == 2 else ""
            for option in active_options:
                descriptions[option] = description
            continue

        if active_options:
            for option in active_options:
                descriptions[option] = f"{descriptions[option]} {stripped}".strip()

    return descriptions


def _invoke_search_contract(
    tmp_path: Path,
    port: int,
    *extra: str,
) -> typing.Any:
    return runner.invoke(
        app,
        [
            "--target",
            str(tmp_path),
            "search",
            "service status",
            "--type",
            "code",
            "--limit",
            "2",
            "--port",
            str(port),
            *extra,
        ],
    )


def _expected_code_search_request(tmp_path: Path, query: str) -> dict[str, object]:
    return {
        "query": query,
        "top_k": 2,
        "project_root": str(tmp_path),
        "type": "code",
    }


def _assert_record(
    record: dict[str, object],
    *,
    number: int,
    location: str,
    text: str,
    score: str | None = None,
) -> None:
    assert record == {
        "number": number,
        "location": location,
        "score": score,
        "text": text,
    }


def _hold_local_index_lock(root: Path):
    from ..config import get_config
    from ..store import FileLock

    cfg = get_config()
    index_dir = root / cfg.data_dir / cfg.qdrant_dir
    index_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(index_dir / "exclusive.lock")
    assert lock.acquire()
    return lock


def _status_contract_server(
    last_progress_age_seconds: float = 2.0,
    *,
    extra_running_job: bool = False,
    failed_jobs: int = 0,
    omit_project: bool = False,
    omit_job_started_at: bool = False,
) -> tuple[typing.Any, typing.Any]:
    """Start a local HTTP service exposing /health and /jobs for status tests."""
    import http.server
    import threading
    import time

    running_job_started_at = time.time() - 42

    class _StatusContractHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            payload = (
                _status_contract_jobs_payload(
                    running_job_started_at,
                    last_progress_age_seconds=last_progress_age_seconds,
                    extra_running_job=extra_running_job,
                    failed_jobs=failed_jobs,
                    omit_project=omit_project,
                    omit_job_started_at=omit_job_started_at,
                )
                if self.path.startswith("/jobs")
                else _status_contract_health_payload()
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            _ = format, args

    server = http.server.HTTPServer(("127.0.0.1", 0), _StatusContractHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _status_contract_jobs_payload(
    started_at: float,
    *,
    last_progress_age_seconds: float,
    extra_running_job: bool,
    failed_jobs: int,
    omit_project: bool,
    omit_job_started_at: bool,
) -> dict[str, object]:
    running_job: dict[str, object] = {
        "id": "running-job",
        "source": "code",
        "trigger": "tool",
        "phase": "running",
        "finished_at": None,
        "result": None,
        "progress": {
            "step": "embed",
            "completed": 7,
            "total": 20,
        },
        "last_progress_age_seconds": last_progress_age_seconds,
    }
    if not omit_job_started_at:
        running_job["started_at"] = started_at
    if not omit_project:
        running_job["initiator"] = {
            "command": "reindex_codebase",
            "project_root": (
                r"C:\projects\vaultspec-rag-worktrees"
                r"\feature-server-supervision"
            ),
        }
    jobs: list[dict[str, object]] = [running_job]
    if extra_running_job:
        jobs.append(
            {
                "id": "vault-running-job",
                "source": "vault",
                "trigger": "watcher",
                "phase": "running",
                "started_at": started_at - 60,
                "finished_at": None,
                "result": None,
                "progress": {
                    "step": "index_documents",
                    "completed": 5,
                    "total": 9,
                },
                "last_progress_age_seconds": 3.0,
                "initiator": {
                    "command": "watcher_vault_index",
                    "project_root": r"C:\projects\other-project",
                },
            }
        )
    jobs.extend([{"id": "done-1", "phase": "done"}, {"id": "done-2", "phase": "done"}])
    jobs.extend(
        {"id": f"failed-{index}", "phase": "error"} for index in range(failed_jobs)
    )
    running_count = 2 if extra_running_job else 1
    phases = {"running": running_count, "done": 2}
    if failed_jobs:
        phases["error"] = failed_jobs
    return {
        "ok": True,
        "jobs": jobs,
        "total": len(jobs),
        "returned": len(jobs),
        "summary": {
            "running": running_count,
            "phases": phases,
        },
    }


def _status_contract_health_payload() -> dict[str, object]:
    return {
        "status": "ready",
        "cuda": True,
        "models_loaded": True,
        "reranker_loaded": True,
        "project_count": 3,
        "uptime_s": 312.0,
        "backend_capabilities": {
            "same_project_search_strategy": "serialized",
            "cross_project_search_strategy": "parallel",
            "local_storage_process_model": "exclusive",
        },
    }


def _slow_search_contract_server(
    *,
    health_payload: dict[str, object] | None = None,
    jobs_payload: dict[str, object] | None = None,
    jobs_status_code: int = 200,
) -> tuple[typing.Any, typing.Any]:
    """Start a local service that lets /search time out while probes work."""
    import http.server
    import threading
    import time

    class _SlowSearchHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/search":
                self.send_response(404)
                self.end_headers()
                return
            time.sleep(0.05)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            with contextlib.suppress(OSError):
                self.wfile.write(json.dumps({"ok": True, "results": []}).encode())

        def do_GET(self):
            payload: dict[str, object]
            if self.path == "/health":
                payload = (
                    health_payload
                    if health_payload is not None
                    else _status_contract_health_payload()
                )
            elif self.path.startswith("/jobs"):
                payload = (
                    jobs_payload
                    if jobs_payload is not None
                    else {
                        "ok": True,
                        "jobs": [],
                        "total": 0,
                        "returned": 0,
                        "summary": {"running": 0, "phases": {}},
                    }
                )
                self.send_response(jobs_status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode("utf-8"))
                return
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            _ = format, args

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SlowSearchHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _search_output_contract_server() -> tuple[typing.Any, typing.Any, list[object]]:
    """Start a local service returning deterministic search results."""
    import http.server
    import threading

    requests: list[object] = []

    class _SearchOutputHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/search":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            requests.append(body)
            payload = {
                "ok": True,
                "results": [
                    {
                        "path": "src/search_ui.py",
                        "line_start": 12,
                        "score": 0.875,
                        "snippet": "def render_search",
                        "rerank_text": (
                            "def render_search_results():\n"
                            "    return 'full service text'"
                        ),
                    },
                    {
                        "anchor": "docs/ops.md#service-status",
                        "path": "docs/ops.md",
                        "score": 0.5,
                        "snippet": "Use server status",
                        "rerank_text": (
                            "Use server status for service readiness and current work."
                        ),
                    },
                ],
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            _ = format, args

    server = http.server.HTTPServer(("127.0.0.1", 0), _SearchOutputHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _sparse_search_output_contract_server() -> tuple[
    typing.Any, typing.Any, list[object]
]:
    """Start a local service returning a result without locator fields."""
    import http.server
    import threading

    requests: list[object] = []

    class _SparseSearchOutputHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/search":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            requests.append(body)
            payload = {
                "ok": True,
                "results": [
                    {
                        "score": 0.25,
                        "snippet": "result text without a source location",
                    }
                ],
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            _ = format, args

    server = http.server.HTTPServer(("127.0.0.1", 0), _SparseSearchOutputHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _empty_search_contract_server() -> tuple[typing.Any, typing.Any, list[object]]:
    """Start a local service returning empty-search diagnostics."""
    import http.server
    import threading

    requests: list[object] = []

    class _EmptySearchHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/search":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            requests.append(body)
            payload: dict[str, object] = {
                "ok": True,
                "results": [],
                "empty": {
                    "reason": "index_missing",
                    "message": "No indexed code items are available.",
                    "remediation": [
                        "vaultspec-rag index --type code --port 8766",
                        "vaultspec-rag server status",
                    ],
                },
                "index_state": {
                    "source": "code",
                    "indexed_count": 0,
                    "requested_target_root": "current project",
                    "indexed_target_root": "other project",
                    "target_matches": False,
                },
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            _ = format, args

    server = http.server.HTTPServer(("127.0.0.1", 0), _EmptySearchHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


_FORBIDDEN_DOCSTRING_TOKENS = ("Args:", "Raises:", "CLIState", " ctx ")


def _find_free_port() -> int:
    """Bind to an ephemeral port, close, and return the number.

    Good enough for the in-process service-down tests: the OS will not
    reuse it immediately, so subsequent connection attempts reliably
    fail with ConnectionRefused.
    """
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _projects_list_contract_server() -> tuple[typing.Any, typing.Any, list[str]]:
    import http.server
    import threading

    requests: list[str] = []

    class _ProjectsHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "projects": [
                            {
                                "root": r"C:\projects\busy",
                                "idle_seconds": 65,
                                "ref_count": 2,
                                "last_access_iso": "2026-06-12T14:05:06Z",
                            },
                            {
                                "root": r"C:\projects\ready",
                                "idle_seconds": 4,
                                "ref_count": 0,
                                "last_access_iso": "",
                            },
                        ],
                        "max_projects": 8,
                        "idle_ttl_seconds": 600,
                    }
                ).encode("utf-8")
            )

        def log_message(self, format: str, *args: object) -> None:
            _ = format, args

    server = http.server.HTTPServer(("127.0.0.1", 0), _ProjectsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _logs_contract_server() -> (  # pyright: ignore[reportUnusedFunction]
    tuple[typing.Any, typing.Any, list[str]]
):
    import http.server
    import threading

    requests: list[str] = []

    class _LogsContractHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "lines": [
                            "2026-06-13 10:05:06 INFO vaultspec_rag.service: "
                            "service.lifecycle event=search search_type=code "
                            "results=3 total_seconds=0.42 "
                            r"root=C:\projects\feature-server-supervision "
                            "request_id=abcdef123456"
                        ]
                    }
                ).encode("utf-8")
            )

        def log_message(self, format: str, *args: object) -> None:
            _ = format, args

    server = http.server.HTTPServer(("127.0.0.1", 0), _LogsContractHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _empty_logs_contract_server() -> tuple[typing.Any, typing.Any, list[str]]:
    import http.server
    import threading

    requests: list[str] = []

    class _LogsContractHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"lines": []}).encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            _ = format, args

    server = http.server.HTTPServer(("127.0.0.1", 0), _LogsContractHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _jobs_empty_contract_server() -> tuple[typing.Any, typing.Any, list[str]]:
    import http.server
    import threading
    import urllib.parse

    requests: list[str] = []

    class _JobsContractHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            payload: dict[str, object] = {
                "jobs": [],
                "total": 0,
                "returned": 0,
                "filters": {
                    "limit": int(query.get("limit", ["20"])[0]),
                    "phase": query.get("phase", [None])[0],
                    "source": query.get("source", [None])[0],
                    "trigger": query.get("trigger", [None])[0],
                    "query": query.get("query", [None])[0],
                    "failed": query.get("failed", [False])[0],
                },
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            _ = format, args

    server = http.server.HTTPServer(("127.0.0.1", 0), _JobsContractHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _jobs_populated_contract_server() -> tuple[typing.Any, typing.Any, list[str]]:
    import http.server
    import threading

    requests: list[str] = []

    class _JobsContractHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            payload = {
                "jobs": [
                    {
                        "id": "finished-job-123",
                        "source": "code",
                        "phase": "done",
                        "started_at": 1000.0,
                        "finished_at": 1001.0,
                        "result": "+1 /0 -0 (1000ms)",
                        "initiator": {
                            "command": "reindex_codebase",
                            "project_root": r"C:\projects\finished-project",
                        },
                    },
                    {
                        "id": "running-job-456",
                        "source": "vault",
                        "trigger": "watcher",
                        "phase": "running",
                        "started_at": 1002.0,
                        "progress": {
                            "step": "embed",
                            "completed": 2,
                            "total": 5,
                        },
                        "runtime_seconds": 7,
                        "initiator": {
                            "command": "watcher_vault_index",
                            "project_root": r"C:\projects\running-project",
                        },
                    },
                ],
                "total": 2,
                "returned": 2,
                "filters": {"limit": 2},
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            _ = format, args

    server = http.server.HTTPServer(("127.0.0.1", 0), _JobsContractHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _projects_unload_contract_server(
    response: dict[str, object] | None = None,
) -> tuple[typing.Any, typing.Any, list[dict[str, object]]]:
    import http.server
    import threading

    requests: list[dict[str, object]] = []
    payload = response or {"unexpected": {"raw": True}}

    class _ProjectsEvictHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            requests.append(json.loads(self.rfile.read(length).decode("utf-8")))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, format: str, *args: object) -> None:
            _ = format, args

    server = http.server.HTTPServer(("127.0.0.1", 0), _ProjectsEvictHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _assert_project_summary_language(out: str) -> None:
    expected = {
        "Capacity: 1 of 16 projects loaded",
        "Automatic unload: after 30 minutes idle",
        "- Project: example",
        r"  Path: C:\projects\example",
        "  Active requests: 1",
        "  Last activity: 2 minutes 5 seconds ago",
        "  Last request: 14:05:06",
    }
    missing = [line for line in expected if line not in out]
    assert not missing, f"missing project summary lines: {missing}"
    forbidden = (
        "Handling 1 active request; idle for 2 minutes 5 seconds",
        "Active uses:",
        "Requests:",
        "Last used:",
        "Auto-unload",
        "Loaded projects:",
        "In use:",
    )
    leaked = [text for text in forbidden if text in out]
    assert not leaked, f"internal project summary language leaked: {leaked}"
    lower = out.lower()
    forbidden_lower = (
        "no timestamp from service",
        "project slots",
        "project handle",
        "idle ttl",
        "references",
    )
    lower_leaks = [text for text in forbidden_lower if text in lower]
    assert not lower_leaks, f"internal project summary language leaked: {lower_leaks}"
    assert {"yes", "no"}.isdisjoint({line.strip() for line in _plain_lines(out)})


__all__ = [
    "DEFAULT_SEARCH_TIMEOUT_SECONDS",
    "_ANSI_RE",
    "_FORBIDDEN_DOCSTRING_TOKENS",
    "_SEARCH_RECORD_RE",
    "EnvVar",
    "TorchConfigAction",
    "_assert_default_status_summary",
    "_assert_no_table_borders",
    "_assert_project_summary_language",
    "_assert_record",
    "_assert_verbose_status_summary",
    "_display_search_results",
    "_display_service_error",
    "_empty_logs_contract_server",
    "_empty_search_contract_server",
    "_expected_code_search_request",
    "_find_free_port",
    "_get_search_timeout",
    "_help_option_descriptions",
    "_hold_local_index_lock",
    "_invoke_search_contract",
    "_is_our_service",
    "_is_pid_alive",
    "_jobs_empty_contract_server",
    "_jobs_populated_contract_server",
    "_label_values",
    "_logs_contract_server",
    "_plain_lines",
    "_projects_list_contract_server",
    "_projects_unload_contract_server",
    "_read_service_status",
    "_search_output_contract_server",
    "_search_records",
    "_section_label_values",
    "_slow_search_contract_server",
    "_sparse_search_output_contract_server",
    "_status_contract_health_payload",
    "_status_contract_jobs_payload",
    "_status_contract_server",
    "_try_http_search",
    "_write_service_status",
    "app",
    "reset_base_config",
    "reset_rag_config",
    "runner",
]
