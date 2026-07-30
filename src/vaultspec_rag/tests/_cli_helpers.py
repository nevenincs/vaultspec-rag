"""Shared fixtures, helpers, and HTTP contract servers for the CLI test suite."""

from __future__ import annotations

import contextlib
import http.server
import json
import os
import re
import typing
from dataclasses import dataclass

from typer.testing import CliRunner, Result
from vaultspec_core.config import (
    reset_config as reset_base_config,
)

from ..cli import app
from ..cli._process import _is_our_service
from ..cli._render import _display_search_results, _display_service_error
from ..cli._service_status import _write_service_status, read_service_status
from ..config._settings import reset_config as reset_rag_config
from ..config._types import EnvVar
from ..serviceclient._compat import DataPlaneService, classify_service_version
from ..serviceclient._transport import (
    DEFAULT_SEARCH_TIMEOUT_SECONDS,
    _get_search_timeout,
    _try_http_search,
)
from ..torch_config._constants import TorchConfigAction
from ._http_stubs import QuietHandler


@dataclass(frozen=True, slots=True)
class _StatusContractOptions:
    last_progress_age_seconds: float = 2.0
    extra_running_job: bool = False
    failed_jobs: int = 0
    omit_project: bool = False
    omit_job_started_at: bool = False
    health: dict[str, object] | None = None
    jobs: dict[str, object] | None = None
    jobs_status_code: int = 200


if typing.TYPE_CHECKING:
    import threading
    from pathlib import Path

    #: A contract server's ``(server, thread)`` pair. The stub servers below
    #: are always a stdlib ``http.server.HTTPServer`` (or its threading
    #: subclass) run on a daemon ``threading.Thread`` - concrete types, not the
    #: ``Any`` the untyped tuple previously let every caller's unpacking
    #: inherit.
    type _ContractServer = tuple[http.server.HTTPServer, threading.Thread]

runner = CliRunner()


@contextlib.contextmanager
def _isolated_status_dir(status_dir: Path) -> typing.Generator[Path]:
    """Point the CLI's service discovery at a temp directory for one block.

    Every CLI test that touches service state has to redirect this and put the
    environment back, including on failure - so it is one helper rather than a
    try/finally in each test, where a missed restore leaks into the next one.
    """
    os.environ[EnvVar.STATUS_DIR] = str(status_dir)
    try:
        yield status_dir
    finally:
        os.environ.pop(EnvVar.STATUS_DIR, None)


#: The identity token a stubbed daemon publishes on ``/health`` and records in
#: its discovery file, so the two round-trip the way a real pair does.
#:
#: Identity is that round-trip. Without a token on both sides the CLI falls
#: back to inspecting the recorded process itself - its executable image on
#: Windows, the command line that started it elsewhere - and the interpreter
#: running these tests answers that question differently per platform and per
#: runner. A fixture that leans on the fallback is asserting a property of the
#: test runner; one that publishes a token asserts the check the daemon ships.
_CONTRACT_SERVICE_TOKEN = "contract-service-token-3f5a1c9e"


def _with_service_token(health: dict[str, object]) -> dict[str, object]:
    """Return *health* as a daemon would report it, carrying its identity token.

    Applied to every ``/health`` body a contract server serves, including one a
    test supplied outright: a real daemon reports its token whatever else its
    health says, and a stub that omitted it on the customised payloads would
    make identity depend on which test wrote the body.
    """
    return {**health, "service_token": _CONTRACT_SERVICE_TOKEN}


@contextlib.contextmanager
def _serving(contract_server: _ContractServer) -> typing.Generator[int]:
    """Own the shutdown of a contract server and its thread, yielding the port."""
    server, thread = contract_server
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextlib.contextmanager
def _running_service_record(
    status_dir: Path,
    port: int,
    *,
    drop: tuple[str, ...] = (),
) -> typing.Generator[Path]:
    """Isolate the status dir and leave a record that reads as a live daemon.

    A running daemon publishes three things: the discovery file, a heartbeat it
    keeps fresh, and the identity token its ``/health`` answers with. A record
    without the heartbeat is *correctly* read as crashed, and one without the
    token names a pid the CLI can only judge by inspecting the process - which
    for this interpreter is not the daemon and reads as a recycled pid. A test
    that wants a running service has to write all three, which is why this is
    one helper rather than three lines in each test. ``drop`` removes keys
    afterwards, for the tests whose subject is a field the daemon omitted.

    Yields the record path and restores the environment on exit.
    """
    from datetime import UTC, datetime

    with _isolated_status_dir(status_dir):
        _write_service_status(pid=os.getpid(), port=port)
        record_path = status_dir / "service.json"
        raw_record = typing.cast(
            "object", json.loads(record_path.read_text(encoding="utf-8"))
        )
        assert isinstance(raw_record, dict)
        record = typing.cast("dict[str, object]", raw_record)
        record["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
        record["service_token"] = _CONTRACT_SERVICE_TOKEN
        for key in drop:
            record.pop(key, None)
        record_path.write_text(json.dumps(record), encoding="utf-8")
        yield record_path


def _no_service() -> DataPlaneService:
    """Return the data-plane resolution a client sees when no daemon is up.

    Stands in for ``resolve_data_plane_service`` in the tests whose subject is
    the in-process path, which is only reached when nothing is discovered. Built
    from the production classifier rather than a hand-written verdict, so it
    stays the resolution an absent service actually produces - no address, and a
    release that cannot be confirmed because there is nothing to ask.
    """
    return DataPlaneService(port=None, version=classify_service_version(None))


def _parsed_json_object(raw: bytes) -> dict[str, object]:
    """Decode a POST body as the JSON object every stub handler expects.

    ``json.loads`` types its return as ``Any`` regardless of what the bytes
    hold, so every handler below narrowed through its own cast; this is the
    one place that narrowing happens, built once rather than repeated at each
    handler's call site.
    """
    if not raw:
        return {}
    parsed = typing.cast("object", json.loads(raw))
    return typing.cast("dict[str, object]", parsed) if isinstance(parsed, dict) else {}


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
        "Identity check": "verified",
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
) -> Result:
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
    from .._store_locks import FileLock
    from ..config._settings import get_config

    cfg = get_config()
    index_dir = root / str(cfg.data_dir) / str(cfg.qdrant_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(index_dir / "exclusive.lock")
    assert lock.acquire()
    return lock


def _status_contract_server(
    options: _StatusContractOptions | None = None,
    **legacy: object,
) -> _ContractServer:
    """Start a local HTTP service exposing /health and /jobs for status tests.

    The keyword flags shape the default payloads for tests that vary one job
    property. ``health`` and ``jobs`` replace a payload outright, and
    ``jobs_status_code`` lets a test drive the jobs-route error path - for tests
    whose subject is the payload itself, so a status test never has to stand up
    its own server.
    """
    import threading
    import time

    if options is None:
        options = _StatusContractOptions(**typing.cast("dict[str, typing.Any]", legacy))
    elif legacy:
        raise TypeError("use either _StatusContractOptions or named inputs")

    running_job_started_at = time.time() - 42

    class _StatusContractHandler(QuietHandler):
        def do_GET(self):
            status_code = 200
            if self.path.startswith("/jobs"):
                status_code = options.jobs_status_code
                payload = (
                    options.jobs
                    if options.jobs is not None
                    else _status_contract_jobs_payload(
                        running_job_started_at,
                        options,
                    )
                )
            else:
                payload = _with_service_token(
                    options.health
                    if options.health is not None
                    else _status_contract_health_payload()
                )
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

    server = http.server.HTTPServer(("127.0.0.1", 0), _StatusContractHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _status_contract_jobs_payload(
    started_at: float,
    options: _StatusContractOptions,
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
        "last_progress_age_seconds": options.last_progress_age_seconds,
    }
    if not options.omit_job_started_at:
        running_job["started_at"] = started_at
    if not options.omit_project:
        running_job["initiator"] = {
            "command": "reindex_codebase",
            "project_root": (
                r"C:\projects\code-worktrees"
                r"\feature-server-supervision"
            ),
        }
    jobs: list[dict[str, object]] = [running_job]
    if options.extra_running_job:
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
        {"id": f"failed-{index}", "phase": "error"}
        for index in range(options.failed_jobs)
    )
    running_count = 2 if options.extra_running_job else 1
    phases = {"running": running_count, "done": 2}
    if options.failed_jobs:
        phases["error"] = options.failed_jobs
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
) -> _ContractServer:
    """Start a local service that lets /search time out while probes work."""
    import threading
    import time

    class _SlowSearchHandler(QuietHandler):
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

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SlowSearchHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def invoke_timed_out_search(
    tmp_path: Path,
    *extra: str,
    health_payload: dict[str, object] | None = None,
    jobs_payload: dict[str, object] | None = None,
    jobs_status_code: int = 200,
) -> tuple[Result, int]:
    """Run one CLI search whose service answers /search too slowly.

    Returns the CLI result and the port, which the diagnostic under test
    quotes back. The service is shut down before the caller asserts, so a
    failing assertion cannot leave the contract server running.
    """
    (tmp_path / ".vaultspec").mkdir()
    server, thread = _slow_search_contract_server(
        health_payload=health_payload,
        jobs_payload=jobs_payload,
        jobs_status_code=jobs_status_code,
    )
    port = server.server_address[1]
    try:
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "service status jobs logs timeout diagnostics",
                "--type",
                "code",
                "--max-results",
                "3",
                "--port",
                str(port),
                "--timeout",
                "0.001",
                *extra,
            ],
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return result, port


def _search_output_contract_server() -> tuple[
    http.server.HTTPServer, threading.Thread, list[object]
]:
    """Start a local service returning deterministic search results."""
    import threading

    requests: list[object] = []

    class _SearchOutputHandler(QuietHandler):
        def do_POST(self):
            if self.path != "/search":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = _parsed_json_object(self.rfile.read(length))
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

    server = http.server.HTTPServer(("127.0.0.1", 0), _SearchOutputHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _sparse_search_output_contract_server() -> tuple[
    http.server.HTTPServer, threading.Thread, list[object]
]:
    """Start a local service returning a result without locator fields."""
    import threading

    requests: list[object] = []

    class _SparseSearchOutputHandler(QuietHandler):
        def do_POST(self):
            if self.path != "/search":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = _parsed_json_object(self.rfile.read(length))
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

    server = http.server.HTTPServer(("127.0.0.1", 0), _SparseSearchOutputHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _empty_search_contract_server() -> tuple[
    http.server.HTTPServer, threading.Thread, list[object]
]:
    """Start a local service returning empty-search diagnostics."""
    import threading

    requests: list[object] = []

    class _EmptySearchHandler(QuietHandler):
        def do_POST(self):
            if self.path != "/search":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = _parsed_json_object(self.rfile.read(length))
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

    server = http.server.HTTPServer(("127.0.0.1", 0), _EmptySearchHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


_FORBIDDEN_DOCSTRING_TOKENS = ("Args:", "Raises:", "CLIState", " ctx ")


def _find_free_port() -> int:
    """Return a loopback port nothing is listening on.

    The name the CLI tests already call; the suite has one implementation of
    "a free port" and this is an alias onto it, not a second one.
    """
    from ._ports import free_loopback_port

    return free_loopback_port()


def _projects_list_contract_server() -> tuple[
    http.server.HTTPServer, threading.Thread, list[str]
]:
    import threading

    requests: list[str] = []

    class _ProjectsHandler(QuietHandler):
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

    server = http.server.HTTPServer(("127.0.0.1", 0), _ProjectsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _logs_contract_server() -> tuple[
    http.server.HTTPServer, threading.Thread, list[str]
]:
    import threading

    requests: list[str] = []

    class _LogsContractHandler(QuietHandler):
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

    server = http.server.HTTPServer(("127.0.0.1", 0), _LogsContractHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _empty_logs_contract_server() -> tuple[
    http.server.HTTPServer, threading.Thread, list[str]
]:
    import threading

    requests: list[str] = []

    class _LogsContractHandler(QuietHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"lines": []}).encode("utf-8"))

    server = http.server.HTTPServer(("127.0.0.1", 0), _LogsContractHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _jobs_empty_contract_server() -> tuple[
    http.server.HTTPServer, threading.Thread, list[str]
]:
    import threading
    import urllib.parse

    requests: list[str] = []

    class _JobsContractHandler(QuietHandler):
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

    server = http.server.HTTPServer(("127.0.0.1", 0), _JobsContractHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _jobs_populated_contract_server() -> tuple[
    http.server.HTTPServer, threading.Thread, list[str]
]:
    import threading

    requests: list[str] = []

    class _JobsContractHandler(QuietHandler):
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

    server = http.server.HTTPServer(("127.0.0.1", 0), _JobsContractHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def _projects_unload_contract_server(
    response: dict[str, object] | None = None,
) -> tuple[http.server.HTTPServer, threading.Thread, list[dict[str, object]]]:
    import threading

    requests: list[dict[str, object]] = []
    payload = response or {"unexpected": {"raw": True}}

    class _ProjectsEvictHandler(QuietHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            requests.append(_parsed_json_object(self.rfile.read(length)))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

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
    "_isolated_status_dir",
    "_jobs_empty_contract_server",
    "_jobs_populated_contract_server",
    "_label_values",
    "_logs_contract_server",
    "_no_service",
    "_parsed_json_object",
    "_plain_lines",
    "_projects_list_contract_server",
    "_projects_unload_contract_server",
    "_reindex_contract_server",
    "_running_service_record",
    "_search_output_contract_server",
    "_search_records",
    "_section_label_values",
    "_serving",
    "_slow_search_contract_server",
    "_sparse_search_output_contract_server",
    "_status_contract_health_payload",
    "_status_contract_jobs_payload",
    "_status_contract_server",
    "_try_http_search",
    "_write_service_status",
    "app",
    "read_service_status",
    "reset_base_config",
    "reset_rag_config",
    "runner",
]


def _reindex_contract_server() -> tuple[
    http.server.HTTPServer, threading.Thread, list[dict[str, object]]
]:
    """Serve the reindex route, recording each request body it was sent.

    Records the decoded body rather than the path, because what a delegation
    test needs to assert is which source the CLI asked to be reindexed and on
    whose behalf - both of which travel in the body, not the URL.
    """
    import threading

    requests: list[dict[str, object]] = []

    class _ReindexContractHandler(QuietHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            if self.path != "/reindex":
                self.send_response(404)
                self.end_headers()
                return
            try:
                parsed: object = json.loads(raw) if raw else {}
            except ValueError:
                parsed = {}
            requests.append(
                typing.cast("dict[str, object]", parsed)
                if isinstance(parsed, dict)
                else {}
            )
            payload = {
                "ok": True,
                "added": 1,
                "updated": 0,
                "removed": 0,
                "total": 1,
                "duration_ms": 10,
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = http.server.HTTPServer(("127.0.0.1", 0), _ReindexContractHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


@contextlib.contextmanager
def process_the_identity_check_recognises() -> typing.Generator[int]:
    """Run a live process this build accepts as its own daemon, yielding its pid.

    Where no ``/health`` token can be round-tripped - a daemon still warming
    has not bound its port - identity falls back to inspecting the process
    itself: its executable image on Windows, the command line that started it
    everywhere else. The interpreter running these tests satisfies neither rule
    on purpose; it is not the daemon, and whether its own command line happens
    to mention the package is a property of how the suite was invoked rather
    than of the code under test. So a test that needs a recognisable pid starts
    a process that carries the witness on both platforms - a python interpreter
    running this package - instead of lending out its own.
    """
    import subprocess
    import sys
    import textwrap

    holder = textwrap.dedent("""
        import time
        import vaultspec_rag
        print("up", flush=True)
        time.sleep(120)
    """)
    process = subprocess.Popen(
        [sys.executable, "-c", holder],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        # typeshed types every Popen stream as IO[Any] regardless of `text=True`
        # (subprocess.pyi declares stdin/stdout/stderr as IO[Any] | None
        # unconditionally), so this is the one cast back to the str stream
        # `text=True` actually produces, rather than one at every read.
        stdout = typing.cast("typing.IO[str]", process.stdout)
        if stdout.readline().strip() != "up":
            msg = "the stand-in daemon process never started"
            raise AssertionError(msg)
        yield process.pid
    finally:
        process.kill()
        process.wait(timeout=10)


@contextlib.contextmanager
def store_locked_by_another_process(root: Path) -> typing.Generator[None]:
    """Hold *root*'s store open in a separate process for the block's duration.

    The lock is per process, not per handle: a second ``VaultStore`` in THIS
    interpreter opens happily, so a same-interpreter holder proves nothing.
    Only a genuinely foreign holder makes the production path raise, which is
    the condition the locked-store message exists to report.
    """
    import subprocess
    import sys
    import textwrap

    holder = textwrap.dedent(f"""
        import pathlib, time
        from vaultspec_rag.store_runtime import VaultStore  # absolute-import-ok
        VaultStore(pathlib.Path(r"{root}"))
        print("held", flush=True)
        time.sleep(120)
    """)
    process = subprocess.Popen(
        [sys.executable, "-c", holder],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        # See process_the_identity_check_recognises: typeshed types every Popen
        # stream as IO[Any] regardless of `text=True`, so this casts back to the
        # str stream `text=True` actually produces, once, rather than at every
        # read.
        stdout = typing.cast("typing.IO[str]", process.stdout)
        if stdout.readline().strip() != "held":
            msg = "the holder process never took the store lock"
            raise AssertionError(msg)
        yield
    finally:
        process.kill()
        process.wait(timeout=10)
