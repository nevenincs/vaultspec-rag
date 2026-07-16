"""Unit tests for the CLI application."""

from __future__ import annotations

import contextlib
import json
import os
import re
import typing
from pathlib import Path

import pytest
from typer.testing import CliRunner
from vaultspec_core.config import (  # pyright: ignore[reportMissingTypeStubs]
    reset_config as reset_base_config,
)

from ..cli import (
    _display_search_results,
    _display_service_error,
    _health_probe,
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

pytestmark = [pytest.mark.unit]

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
        "type": "codebase",
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
                r"Y:\code\vaultspec-rag-worktrees"
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
                    "project_root": r"Y:\code\other-project",
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


class TestSearchTimeoutDefaults:
    """Tests for service-delegated search timeout defaults."""

    def test_default_search_timeout_is_production_budget(self) -> None:
        previous = os.environ.pop("VAULTSPEC_RAG_SEARCH_TIMEOUT", None)
        try:
            assert _get_search_timeout(None) == DEFAULT_SEARCH_TIMEOUT_SECONDS
        finally:
            if previous is not None:
                os.environ["VAULTSPEC_RAG_SEARCH_TIMEOUT"] = previous

    def test_invalid_env_timeout_uses_production_budget(self) -> None:
        previous = os.environ.get("VAULTSPEC_RAG_SEARCH_TIMEOUT")
        os.environ["VAULTSPEC_RAG_SEARCH_TIMEOUT"] = "not-a-number"
        try:
            assert _get_search_timeout(None) == DEFAULT_SEARCH_TIMEOUT_SECONDS
        finally:
            if previous is None:
                os.environ.pop("VAULTSPEC_RAG_SEARCH_TIMEOUT", None)
            else:
                os.environ["VAULTSPEC_RAG_SEARCH_TIMEOUT"] = previous

    def test_explicit_timeout_still_wins(self) -> None:
        assert _get_search_timeout(0.25) == 0.25


class TestMainHelp:
    """Tests for top-level CLI help and options."""

    def test_help_shows_usage(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "VaultSpec RAG" in result.output

    def test_help_lists_commands(self):
        result = runner.invoke(app, ["--help"])
        assert "index" in result.output
        assert "clean" in result.output
        assert "search" in result.output
        assert "status" in result.output
        assert "test" in result.output
        assert "server" in result.output

    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        # no_args_is_help=True causes typer to exit with code 0
        # but some versions exit with 2; accept both
        assert "Usage" in result.output

    @pytest.mark.parametrize(
        ("args", "expected_commands"),
        [
            (["server"], ("status", "jobs", "logs")),
            (["server", "projects"], ("list", "unload")),
            (["server", "updates"], ("status", "start", "stop", "timing")),
            (["server", "qdrant"], ("install", "status", "clean")),
            (["preprocess"], ("list", "check", "run-one")),
        ],
    )
    def test_nested_groups_without_command_show_help(
        self,
        args: list[str],
        expected_commands: tuple[str, ...],
    ) -> None:
        result = runner.invoke(app, args)

        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output
        assert "Missing command" not in result.output
        missing = [
            command for command in expected_commands if command not in result.output
        ]
        assert not missing, f"missing commands from help: {missing}"

    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "vaultspec-rag" in result.output


class TestTestCommand:
    """Tests for the `test` subcommand argument pass-through."""

    def test_help(self):
        result = runner.invoke(app, ["test", "--help"])
        assert result.exit_code == 0
        assert "pytest" in result.output.lower()
        assert "Extra arguments are passed to pytest" in result.output
        for forbidden in ("Args:", "Raises:", "Examples::", "ctx:"):
            assert forbidden not in result.output

    def test_accepts_marker_flag(self):
        """Verify the command accepts -m without erroring on arg parsing."""
        result = runner.invoke(app, ["test", "--collect-only", "-q"])
        # Exit code depends on pytest finding tests, but the CLI
        # should not reject the args at the typer level.
        # A typer rejection would show "Error" and "Usage" in output.
        assert "Usage:" not in result.output

    def test_accepts_multiple_pytest_args(self):
        """Verify arbitrary pytest flags pass through."""
        result = runner.invoke(
            app,
            ["test", "-m", "unit", "-v", "--timeout=5", "-x"],
        )
        assert "Usage:" not in result.output


class TestWorkspaceRequired:
    """Commands that require a workspace should fail gracefully without one."""

    def test_index_requires_workspace(self):
        result = runner.invoke(
            app,
            ["--target", "/nonexistent/path", "index"],
        )
        assert result.exit_code != 0

    def test_search_requires_workspace(self):
        result = runner.invoke(
            app,
            ["--target", "/nonexistent/path", "search", "query"],
        )
        assert result.exit_code != 0

    def test_status_requires_workspace(self):
        result = runner.invoke(
            app,
            ["--target", "/nonexistent/path", "status"],
        )
        assert result.exit_code != 0


class TestCleanCommand:
    """Tests for the wipe-only ``clean`` command."""

    @staticmethod
    def _workspace(tmp_path: Path) -> Path:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        return tmp_path

    def test_clean_help_renders(self):
        result = runner.invoke(app, ["clean", "--help"])
        assert result.exit_code == 0
        assert "wipe" in result.output.lower()

    def test_clean_confirm_prompt_uses_search_index_language(self, tmp_path: Path):
        root = self._workspace(tmp_path)
        result = runner.invoke(
            app,
            ["--target", str(root), "clean", "all"],
            input="n\n",
        )

        assert result.exit_code == 1
        assert "Delete all search index data for" in result.output
        assert "Clean cancelled." in result.output
        assert "RAG index data" not in result.output

    def test_clean_noninteractive_abort_uses_operator_language(self, tmp_path: Path):
        root = self._workspace(tmp_path)
        result = runner.invoke(
            app,
            ["--target", str(root), "clean", "vault"],
        )

        assert result.exit_code == 1
        assert "Clean cancelled." in result.output
        assert "Aborted!" not in result.output

    def test_clean_all_clears_collections_and_metadata(self, tmp_path: Path):
        from ..config import get_config
        from ..store import VaultStore

        root = self._workspace(tmp_path)
        cfg = get_config()
        data_dir = root / cfg.data_dir
        data_dir.mkdir(parents=True)
        (data_dir / cfg.index_metadata_file).write_text('{"x": "y"}', encoding="utf-8")
        (data_dir / cfg.code_index_metadata_file).write_text(
            '{"src/app.py": "hash"}',
            encoding="utf-8",
        )

        store = VaultStore(root)
        try:
            store.ensure_table()
            store.ensure_code_table()
        finally:
            store.close()

        result = runner.invoke(app, ["--target", str(root), "clean", "all", "--yes"])
        assert result.exit_code == 0, result.output
        assert "Clean summary" in result.output
        assert "Vault index: empty." in result.output
        assert "Source code index: empty." in result.output
        assert "Vault: empty" not in result.output
        assert "Code: empty" not in result.output
        for forbidden in ("─", "│", "┌", "┐", "└", "┘"):
            assert forbidden not in result.output

        store = VaultStore(root)
        try:
            assert store.count() == 0
            assert store.count_code() == 0
        finally:
            store.close()
        assert not (data_dir / cfg.index_metadata_file).exists()
        assert not (data_dir / cfg.code_index_metadata_file).exists()

    def test_clean_lock_error_uses_operator_language(self, tmp_path: Path) -> None:
        root = self._workspace(tmp_path)
        lock = _hold_local_index_lock(root)
        try:
            result = runner.invoke(
                app,
                ["--target", str(root), "clean", "all", "--yes"],
            )
        finally:
            lock.release()

        assert result.exit_code == 1, result.output
        assert "Cannot clean the index because the local index is busy" in result.output
        assert "vaultspec-rag server status" in result.output
        for leaked in (
            "Qdrant",
            "Local-file-backed",
            "parallel-safe",
            "exclusive.lock",
            "another process holds the lock",
        ):
            assert leaked not in result.output


class TestStatusCommand:
    """Tests for the project index status command."""

    @staticmethod
    def _workspace(tmp_path: Path) -> Path:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        return tmp_path

    def test_status_human_output_uses_operator_labels(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._status import _render_status_text

        _render_status_text(
            {
                "cuda": False,
                "gpu_name": "",
                "vram_mb": 0,
                "storage_path": tmp_path / ".vault" / "data" / "search-data",
                "vault_documents": 12,
                "codebase_chunks": 34,
            },
            target=tmp_path,
            service_port=8766,
        )

        output = capsys.readouterr().out
        lines = _plain_lines(output)
        labels = _label_values(output)
        assert lines[0] == "Project index"
        assert labels["Project"] == str(tmp_path)
        assert labels["Index data"] == str(tmp_path / ".vault" / "data" / "search-data")
        assert labels["Compute"] == "CPU only (no supported GPU detected)"
        assert labels["Vault documents"] == "12"
        assert labels["Source code sections"] == "34"
        assert labels["Server"] == "running"
        assert labels["Address"] == "http://127.0.0.1:8766"
        assert lines[lines.index("Server details:") + 1] == (
            "vaultspec-rag server status --port 8766"
        )
        assert "Next action:" not in output

    def test_status_empty_index_output_is_actionable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._status import _render_status_text

        _render_status_text(
            {
                "cuda": False,
                "gpu_name": "",
                "vram_mb": 0,
                "storage_path": tmp_path / ".vault" / "data" / "search-data",
                "vault_documents": 0,
                "codebase_chunks": 0,
            },
            target=tmp_path,
            service_port=8766,
        )

        lines = _plain_lines(capsys.readouterr().out)
        next_action_index = lines.index("Next action:")
        assert lines[next_action_index + 1] == "vaultspec-rag index --type all"
        assert all("Health:" not in line for line in lines)

    def test_status_partial_index_output_names_missing_index(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._status import _render_status_text

        _render_status_text(
            {
                "cuda": False,
                "gpu_name": "",
                "vram_mb": 0,
                "storage_path": tmp_path / ".vault" / "data" / "search-data",
                "vault_documents": 3,
                "codebase_chunks": 0,
            },
            target=tmp_path,
        )

        lines = _plain_lines(capsys.readouterr().out)
        next_action_index = lines.index("Next action:")
        assert lines[next_action_index + 1] == "vaultspec-rag index --type code"

    def test_status_prefers_running_service_index_state(self, tmp_path: Path) -> None:
        import http.server
        import threading
        import urllib.parse

        root = self._workspace(tmp_path)
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        requests: list[str] = []

        class ServiceStateHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                requests.append(self.path)
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                assert parsed.path == "/service-state"
                assert query["project_root"] == [str(root)]
                response = {
                    "ok": True,
                    "index": {
                        "cuda": False,
                        "gpu_name": "",
                        "vram_mb": 0,
                        "storage_path": "http://127.0.0.1:8765",
                        "vault_documents": 7,
                        "codebase_chunks": 9,
                        "target_dir": str(root),
                    },
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), ServiceStateHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        os.environ[EnvVar.QDRANT_STORAGE_DIR] = str(tmp_path / "qdrant" / "storage")
        reset_base_config()
        reset_rag_config()
        try:
            _write_service_status(pid=os.getpid(), port=server.server_port)
            result = runner.invoke(app, ["--target", str(root), "status"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
            os.environ.pop(EnvVar.STATUS_DIR, None)
            os.environ.pop(EnvVar.QDRANT_STORAGE_DIR, None)
            reset_base_config()
            reset_rag_config()

        assert result.exit_code == 0, result.output
        assert requests == [
            "/service-state?project_root=" + urllib.parse.quote(str(root))
        ]
        labels = _label_values(result.output)
        lines = _plain_lines(result.output)
        assert lines[0] == "Project index"
        assert labels["Project"] == str(root)
        assert labels["Index data"] == "running service storage"
        assert labels["Vault documents"] == "7"
        assert labels["Source code sections"] == "9"
        assert labels["Server"] == "running"
        assert labels["Address"] == f"http://127.0.0.1:{server.server_port}"
        assert lines[lines.index("Server details:") + 1] == (
            f"vaultspec-rag server status --port {server.server_port}"
        )

    def test_status_lock_error_uses_operator_language(self, tmp_path: Path) -> None:
        root = self._workspace(tmp_path)
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        os.environ[EnvVar.QDRANT_STORAGE_DIR] = str(tmp_path / "qdrant" / "storage")
        reset_base_config()
        reset_rag_config()
        lock = _hold_local_index_lock(root)
        try:
            result = runner.invoke(app, ["--target", str(root), "status"])
        finally:
            lock.release()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            os.environ.pop(EnvVar.QDRANT_STORAGE_DIR, None)
            reset_base_config()
            reset_rag_config()

        assert result.exit_code == 1, result.output
        assert "Cannot read index status because the local index is busy" in (
            result.output
        )
        assert "vaultspec-rag server status" in result.output
        for leaked in (
            "Qdrant",
            "Local-file-backed",
            "parallel-safe",
            "exclusive.lock",
            "another process holds the lock",
        ):
            assert leaked not in result.output


class TestIndexRebuild:
    """Tests for the drop-and-reindex flag."""

    def test_index_rebuild_parses_with_dry_run(self, tmp_path: Path):
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "code",
                "--rebuild",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "files would be indexed" in result.output

    def test_index_dry_run_rejects_document_indexing_in_user_language(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()

        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "index", "--type", "vault", "--dry-run"],
        )

        assert result.exit_code == 2
        lines = _plain_lines(result.output)
        assert lines == [
            "Dry run is available for source-code indexing only.",
            "Run:",
            "vaultspec-rag index --type code --dry-run",
        ]
        assert "--dry-run only applies" not in result.output
        assert "codebase" not in result.output

    def test_index_dry_run_document_indexing_json_has_next_action(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "vault",
                "--dry-run",
                "--json",
            ],
        )

        assert result.exit_code == 2
        envelope = json.loads(result.output)
        assert envelope["ok"] is False
        assert envelope["command"] == "index"
        assert envelope["error"] == "dry_run_requires_code"
        assert (
            envelope["message"] == "Dry run is available for source-code indexing only."
        )
        assert envelope["remediation"] == ["vaultspec-rag index --type code --dry-run"]

    def test_index_dry_run_human_output_is_bounded(self, tmp_path: Path) -> None:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        for name in ("alpha.py", "beta.py", "gamma.py"):
            (tmp_path / name).write_text("print('indexed')\n", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "code",
                "--dry-run",
                "--dry-run-limit",
                "2",
            ],
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert lines == [
            "Dry run: 3 source-code files would be indexed.",
            "Files shown:",
            "- alpha.py",
            "- beta.py",
            (
                "1 more file not shown. Use --dry-run-limit 3 "
                "or --json for the full list."
            ),
        ]
        assert "gamma.py" not in result.output

    def test_index_dry_run_json_keeps_full_file_list(self, tmp_path: Path) -> None:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        for name in ("alpha.py", "beta.py", "gamma.py"):
            (tmp_path / name).write_text("print('indexed')\n", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "code",
                "--dry-run",
                "--dry-run-limit",
                "1",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        envelope = json.loads(result.output)
        assert envelope["ok"] is True
        files = set(envelope["data"]["files"])
        assert files == {"alpha.py", "beta.py", "gamma.py"}

    def test_index_dry_run_rejects_negative_limit(self, tmp_path: Path) -> None:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "code",
                "--dry-run",
                "--dry-run-limit",
                "-1",
            ],
        )

        assert result.exit_code == 2
        lines = _plain_lines(result.output)
        assert lines == [
            "Dry-run file limit must be zero or greater.",
            "Run:",
            "vaultspec-rag index --type code --dry-run --dry-run-limit 50",
        ]

    def test_index_rebuild_without_explicit_type_exits_2(self, tmp_path: Path):
        """--rebuild without --type is rejected.

        The audit found --rebuild silently inherited --type all from the
        default and the in-process branch destroyed both collections.
        Require explicit --type when --rebuild is set; bare `index` stays
        frictionless.
        """
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "index", "--rebuild"],
        )
        assert result.exit_code == 2
        assert "explicit --type" in result.output

    def test_index_rebuild_without_explicit_type_json_envelope(
        self,
        tmp_path: Path,
    ):
        """The same guard surfaces a rebuild_requires_explicit_type envelope."""
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "index", "--rebuild", "--json"],
        )
        assert result.exit_code == 2
        env = json.loads(result.output.strip())
        assert env["ok"] is False
        assert env["command"] == "index"
        assert env["error"] == "rebuild_requires_explicit_type"
        # Remediation lists the three valid forms.
        rem = env["remediation"]
        assert any("--type vault" in r for r in rem)
        assert any("--type code" in r for r in rem)
        assert any("--type all" in r for r in rem)

    def test_index_bare_invocation_still_works(self, tmp_path: Path):
        """Bare `vaultspec-rag index` (no --rebuild) keeps the all default.

        Cannot fully exercise the indexers without a GPU + corpus, but the
        guard must not fire on this canonical quick-start invocation. We
        invoke with --dry-run (codebase-only path that short-circuits
        before the guard) to confirm the daily-driver pattern lands in
        the dry-run branch and does not hit the guard.
        """
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "index", "--dry-run"],
        )
        # Dry-run with default --type all picks up code only and exits
        # cleanly. The new --rebuild guard must NOT have been triggered.
        assert "explicit --type" not in result.output
        assert result.exit_code == 0, result.output


class TestServerCommands:
    """Tests for server subcommand group."""

    def test_server_help(self):
        result = runner.invoke(app, ["server", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "updates" in result.output
        assert "watcher" not in result.output.lower()
        assert "mcp" not in result.output.lower()

    @pytest.mark.parametrize(
        "argv",
        [
            ["server", "mcp", "--help"],
            ["server", "mcp", "start", "--help"],
            ["server", "mcp", "stop"],
            ["server", "mcp", "status"],
        ],
    )
    def test_server_mcp_is_not_a_user_facing_command(self, argv: list[str]):
        result = runner.invoke(app, argv)

        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_service_stop_no_status_file(self, tmp_path: Path):
        # Isolate both the status dir and the machine-global storage dir to
        # guaranteed-empty tmp locations. The defaults live under
        # ~/.vaultspec-rag/, so without this the assertion races any real
        # service: `server stop` reclaims a resident service through the
        # machine singleton lock, which is anchored to the storage dir (not the
        # status dir), so isolating the status dir alone is insufficient.
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        storage_dir = tmp_path / "qdrant-server" / "storage"
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        os.environ[EnvVar.QDRANT_STORAGE_DIR] = str(storage_dir)
        reset_base_config()
        reset_rag_config()
        try:
            result = runner.invoke(app, ["server", "stop"])
            assert result.exit_code == 0
            assert (
                "not running" in result.output.lower() or "No service" in result.output
            )
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)
            os.environ.pop(EnvVar.QDRANT_STORAGE_DIR, None)
            reset_base_config()
            reset_rag_config()

    def test_service_status_no_status_file(self, tmp_path: Path):
        """No status file → exit 3 (stopped)."""
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        reset_base_config()
        reset_rag_config()
        try:
            result = runner.invoke(app, ["server", "status"])
            assert result.exit_code == 3
            assert "stopped" in result.output.lower()
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)
            reset_base_config()
            reset_rag_config()

    def test_server_health_is_not_a_user_facing_command(self):
        """server status is the single user-facing readiness entry point."""
        help_result = runner.invoke(app, ["server", "--help"])
        assert help_result.exit_code == 0, help_result.output
        assert "health" not in help_result.output.lower()

        result = runner.invoke(app, ["server", "health", "--help"])
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_server_watcher_alias_is_not_a_user_facing_command(self):
        """server updates is the single user-facing automatic update surface."""
        updates_help = runner.invoke(app, ["server", "updates", "--help"])
        assert updates_help.exit_code == 0, updates_help.output
        assert "automatic index updates" in updates_help.output

        result = runner.invoke(app, ["server", "watcher", "--help"])
        assert result.exit_code != 0
        assert "No such command" in result.output


class TestServerRoutingFlattened:
    """Verify the flattened `server` command surface (W03.P05.S12 #169).

    The `service` nesting level is removed; lifecycle commands and
    operator sub-groups now live directly under `server`.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_server_start_help(self):
        result = runner.invoke(app, ["server", "start", "--help"])
        assert result.exit_code == 0, result.output

    def test_server_status_help(self):
        result = runner.invoke(app, ["server", "status", "--help"])
        assert result.exit_code == 0, result.output
        assert "operator summary" in result.output
        assert "server readiness" in result.output
        assert "server health" not in result.output.lower()
        assert "service identity" in result.output
        assert "token" not in result.output.lower()
        assert "Emit JSON for scripts" in result.output
        assert "JSON envelope" not in result.output
        assert "full-fidelity" not in result.output

    def test_server_health_not_a_command(self):
        result = runner.invoke(app, ["server", "health", "--help"])
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_server_updates_status_help(self):
        result = runner.invoke(app, ["server", "updates", "status", "--help"])
        assert result.exit_code == 0, result.output
        assert "automatic index update" in result.output.lower()
        assert "Emit JSON for scripts" in result.output
        assert "JSON envelope" not in result.output

    def test_server_updates_status_explains_missing_timing(self, tmp_path: Path):
        import http.server
        import threading

        project = tmp_path / "project-alpha"
        project.mkdir()
        paths: list[str] = []

        class WatcherStateHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                paths.append(self.path)
                response = {
                    "watch_enabled": True,
                    "watching": [str(project)],
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), WatcherStateHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = runner.invoke(
                app,
                [
                    "server",
                    "updates",
                    "status",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert paths == ["/watcher"]

        output = _ANSI_RE.sub("", result.output)
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        assert lines[0] == f"Address: http://127.0.0.1:{server.server_port}"
        assert lines[1] == "Automatic index updates: enabled"
        assert lines[2] == "File changes: not reported by service."
        assert lines[3] == "Repeat updates: not reported by service."
        assert lines[4] == "Projects updating automatically: 1"
        assert lines[5] == "- Project: project-alpha"
        assert lines[6] == f"Path: {project}"
        assert "unknown" not in output.lower()
        assert "wait not reported" not in output.lower()

    def test_server_projects_list_help(self):
        result = runner.invoke(app, ["server", "projects", "list", "--help"])
        assert result.exit_code == 0, result.output
        assert "Emit JSON for scripts" in result.output
        assert "JSON envelope" not in result.output

    def test_server_service_not_a_command(self):
        """The `service` nesting level must no longer exist."""
        result = runner.invoke(app, ["server", "service", "--help"])
        assert result.exit_code != 0

    def test_qdrant_status_splits_service_managed_process_details(self, tmp_path: Path):
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        reset_base_config()
        reset_rag_config()
        try:
            _write_service_status(pid=os.getpid(), port=8766)
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            data.update(
                {
                    "qdrant_pid": 43210,
                    "qdrant_alive": True,
                    "qdrant_port": 6334,
                }
            )
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "qdrant", "status"])

            assert result.exit_code == 0, result.output
            labels = _label_values(result.output)
            assert labels["Address"] == "http://127.0.0.1:6334"
            assert labels["Connection"] == "not accepting requests"
            assert labels["Process"] == "running, started by vaultspec-rag"
            assert labels["Process ID"] == "43210"
            assert labels["Process port"] == "6334"
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)
            reset_base_config()
            reset_rag_config()


class TestServiceLifecycleHelpers:
    """_port_is_listening + _heartbeat_age_seconds helpers."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_port_is_listening_true_for_open_socket(self):
        """A socket bound and listening locally is reported as listening."""
        import socket

        from ..cli import _port_is_listening

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            assert _port_is_listening(port) is True
        finally:
            sock.close()

    def test_port_is_listening_false_for_closed_port(self):
        """An unbound ephemeral port returns False without raising."""
        import socket

        from ..cli import _port_is_listening

        # Bind to find a free port, then close so it's unbound.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        assert _port_is_listening(port) is False

    def test_heartbeat_age_missing_field(self):
        """No last_heartbeat → None (caller treats as 'no data')."""
        from ..cli import _heartbeat_age_seconds

        assert _heartbeat_age_seconds({"pid": 1, "port": 2}) is None

    def test_heartbeat_age_malformed_timestamp(self):
        """Unparseable timestamp → None, no exception."""
        from ..cli import _heartbeat_age_seconds

        assert _heartbeat_age_seconds({"last_heartbeat": "not-a-date"}) is None

    def test_heartbeat_age_fresh(self):
        """Just-written heartbeat → near-zero seconds."""
        from datetime import UTC, datetime

        from ..cli import _heartbeat_age_seconds

        ts = datetime.now(UTC).isoformat(timespec="seconds")
        age = _heartbeat_age_seconds({"last_heartbeat": ts})
        assert age is not None
        assert 0 <= age < 5

    def test_heartbeat_age_stale(self):
        """Old heartbeat → seconds matching the synthesized delta."""
        from datetime import UTC, datetime, timedelta

        from ..cli import _heartbeat_age_seconds

        old = (datetime.now(UTC) - timedelta(seconds=120)).isoformat(
            timespec="seconds",
        )
        age = _heartbeat_age_seconds({"last_heartbeat": old})
        assert age is not None
        assert 115 < age < 125

    def test_heartbeat_age_naive_timestamp_assumed_utc(self):
        """Pre-3.13-style naive ISO timestamps must not crash."""
        from datetime import UTC, datetime, timedelta

        from ..cli import _heartbeat_age_seconds

        old = (
            (datetime.now(UTC) - timedelta(seconds=10))
            .replace(
                tzinfo=None,
            )
            .isoformat(timespec="seconds")
        )
        age = _heartbeat_age_seconds({"last_heartbeat": old})
        assert age is not None
        assert 8 < age < 15

    def test_service_status_stale_heartbeat_exits_4(self, tmp_path: Path):
        """File present + PID alive + heartbeat stale → exit 4."""
        from datetime import UTC, datetime, timedelta

        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=os.getpid(), port=1)  # port 1 unbound
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            # 5 minutes old: well past the 60s staleness threshold.
            data["last_heartbeat"] = (
                datetime.now(UTC) - timedelta(seconds=300)
            ).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status"])
            assert result.exit_code == 4
            # Port 1 likely yields "crashed (port silent)" first because
            # port-not-listening is checked before heartbeat staleness in
            # the State derivation. Either message is acceptable; the
            # contract being tested is the non-zero exit code.
            assert "crashed" in result.output.lower()
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_service_status_next_action_starts_stopped_service(self, tmp_path: Path):
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            result = runner.invoke(
                app,
                ["server", "status", "--port", "1", "--json"],
            )
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

        assert result.exit_code == 3
        payload = json.loads(result.output)
        next_action = payload["data"]["operational"]["next_action"]
        assert next_action == "vaultspec-rag server start --port 1"
        assert "logs" not in next_action


class TestMcpFastPath:
    """Tests for MCP fast-path functions (_try_http_search, _display_search_results)."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_tool_map_vault(self):
        """Connection refused on port 1 returns None, no exception."""
        result = _try_http_search("test query", "vault", 5, 1, "/tmp/proj")
        assert result is None

    def test_tool_map_code(self):
        """search_type='code' maps to search_codebase, returns None on failure."""
        result = _try_http_search("test query", "code", 5, 1, "/tmp/proj")
        assert result is None

    def test_invalid_search_type(self):
        """Unknown search_type falls back to search_vault, returns None on failure."""
        result = _try_http_search("test query", "invalid", 5, 1, "/tmp/proj")
        assert result is None

    def test_code_filters_with_vault_returns_usage_error(self):
        """Filter kwargs with --type vault yield a structured usage error."""
        result = _try_http_search(
            "test query",
            "vault",
            5,
            1,
            "/tmp/proj",
            function_name="foo",
        )
        assert isinstance(result, dict)
        assert result.get("ok") is False
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--function-name" in str(result.get("message", ""))

    def test_code_filters_with_all_returns_usage_error(self):
        """search_type='all' is also incompatible with code-only filters."""
        result = _try_http_search(
            "q",
            "all",
            5,
            1,
            "/tmp/proj",
            language="python",
            class_name="Foo",
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        msg = str(result.get("message", ""))
        assert "--language" in msg and "--class-name" in msg

    def test_code_filters_unset_dont_short_circuit(self):
        """All filters None must not trigger the usage error path."""
        # No service running on port 1 → expect transport None, NOT usage-error dict.
        result = _try_http_search("q", "vault", 5, 1, "/tmp/proj")
        assert result is None

    def test_code_filters_with_code_attempts_call(self):
        """Filters paired with --type code reach the call path; no service → None."""
        result = _try_http_search(
            "q",
            "code",
            5,
            1,
            "/tmp/proj",
            language="python",
            function_name="foo",
        )
        # No live service → transport failure → None (not a usage-error dict).
        assert result is None

    def test_search_cmd_rejects_filter_with_vault(self):
        """The CLI ``search`` command refuses filter flags when --type vault."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "vault",
                "--function-name",
                "foo",
            ],
        )
        assert result.exit_code == 2
        assert "require --type code" in result.output

    def test_search_cmd_rejects_vault_filter_with_code(self):
        """Vault filters with --type code error explicitly."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "code",
                "--feature",
                "auth",
            ],
        )
        assert result.exit_code == 2
        assert "require --type vault" in result.output

    def test_search_cmd_rejects_unknown_option_with_plain_language(self):
        result = runner.invoke(app, ["search", "anything", "--bogus-option"])

        assert result.exit_code == 2
        assert "Unexpected search options: --bogus-option" in result.output
        assert "option(s)" not in result.output

    @pytest.mark.parametrize(
        "argv",
        [
            ["search", "anything", "--type", "code", "--node-type", "function"],
            ["search", "anything", "--type", "code", "--no-truncate"],
        ],
    )
    def test_search_removed_legacy_flags_are_not_supported(self, argv: list[str]):
        result = runner.invoke(app, argv)

        assert result.exit_code == 2
        assert "Unexpected search options:" in result.output
        assert "Searching code" not in result.output

    def test_path_filter_with_vault_returns_usage_error(self):
        """--path is a code filter; pairing it with vault must error."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            path="src/foo.py",
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "path" in str(result.get("message", ""))

    def test_vault_filter_with_code_returns_usage_error(self):
        """doc_type/feature/date/tag with --type code must error."""
        result = _try_http_search(
            "test",
            "code",
            5,
            1,
            "/tmp/proj",
            doc_type="adr",
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--doc-type" in str(result.get("message", ""))

    def test_vault_filters_with_code_attempt_call(self):
        """doc_type/feature/date/tag with --type vault reach the call path."""
        result = _try_http_search(
            "q",
            "vault",
            5,
            1,
            "/tmp/proj",
            doc_type="adr",
            feature="auth",
            date="2026-05-28",
            tag="auth",
        )
        # No live service → ConnectionRefused → None.
        assert result is None

    def test_include_path_with_vault_returns_usage_error(self):
        """--include-path is a code filter; --type vault must error."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            include_paths=["src/foo/**"],
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--include-path" in str(result.get("message", ""))

    def test_exclude_path_with_vault_returns_usage_error(self):
        """--exclude-path with --type vault errors out symmetrically."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            exclude_paths=["locales/*.yml"],
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--exclude-path" in str(result.get("message", ""))

    def test_glob_filters_with_code_attempt_call(self):
        """--include-path/--exclude-path with --type code reach the call path."""
        result = _try_http_search(
            "q",
            "code",
            5,
            1,
            "/tmp/proj",
            include_paths=["src/**"],
            exclude_paths=["tests/**"],
        )
        assert result is None

    def test_search_cmd_rejects_include_path_with_vault(self):
        """CLI: --include-path + --type vault exits 2 with usage error."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "vault",
                "--include-path",
                "src/**",
            ],
        )
        assert result.exit_code == 2
        assert "require --type code" in result.output

    def test_search_cmd_rejects_exclude_path_with_vault(self):
        """CLI: --exclude-path + --type vault exits 2 with usage error."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "vault",
                "--exclude-path",
                "locales/*.yml",
            ],
        )
        assert result.exit_code == 2
        assert "require --type code" in result.output

    def test_dedup_locales_with_vault_returns_usage_error(self):
        """--dedup-locales is a code-only post-process flag."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            dedup_locales=True,
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--dedup-locales" in str(result.get("message", ""))

    def test_prefer_with_vault_returns_usage_error(self):
        """--prefer is a code-only post-process flag."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            prefer="prod",
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--prefer" in str(result.get("message", ""))

    def test_postproc_flags_with_code_attempt_call(self):
        """dedup_locales/prefer with --type code reach the call path."""
        result = _try_http_search(
            "q",
            "code",
            5,
            1,
            "/tmp/proj",
            dedup_locales=True,
            prefer="tests",
        )
        assert result is None

    def test_search_cmd_rejects_dedup_locales_with_vault(self):
        """CLI: --dedup-locales + --type vault exits 2 with usage error."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "vault",
                "--dedup-locales",
            ],
        )
        assert result.exit_code == 2
        assert "require --type code" in result.output

    def test_search_cmd_rejects_prefer_with_vault(self):
        """CLI: --prefer + --type vault exits 2 with usage error."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "vault",
                "--prefer",
                "production",
            ],
        )
        assert result.exit_code == 2
        assert "require --type code" in result.output

    def test_search_cmd_rejects_invalid_prefer_value(self):
        """CLI: --prefer reports user-facing supported values."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "code",
                "--prefer",
                "bogus",
            ],
        )
        assert result.exit_code == 2
        assert "production, tests, or documentation" in result.output
        assert "prod|tests|docs" not in result.output

    @pytest.mark.parametrize("prefer", ["prod", "docs"])
    def test_search_cmd_rejects_internal_prefer_values(self, prefer: str):
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "code",
                "--prefer",
                prefer,
            ],
        )

        assert result.exit_code == 2
        assert "production, tests, or documentation" in result.output
        assert prefer in result.output

    def test_path_filter_with_code_attempts_call(self):
        """--path with --type code reaches the call path."""
        result = _try_http_search(
            "q",
            "code",
            5,
            1,
            "/tmp/proj",
            path="src/foo.py",
        )
        assert result is None

    def test_live_but_broken_returns_structured_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Non-connection-refused exception yields ok=False dict, not None.

        Without this discrimination the caller would treat a
        live-but-broken service the same as a dead one and silently
        relane to the unsafe in-process path. The fix preserves the
        ``None`` -> dead-service semantic for ConnectionRefused only.
        """

        from .. import cli as cli_mod

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic live-but-broken tool failure")

        monkeypatch.setattr(
            "vaultspec_rag.serviceclient._transport._do_http_call", _boom
        )

        result = cli_mod._try_http_search(
            "q",
            "code",
            5,
            8766,
            "/tmp/proj",
        )
        assert isinstance(result, dict)
        assert result.get("ok") is False
        assert result.get("error") == "http_call_failed"
        assert "synthetic live-but-broken" in str(result.get("message", ""))

    def test_live_but_broken_reindex_returns_structured_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Same discrimination for _try_http_reindex."""

        from .. import cli as cli_mod

        def mock_timeout(*_a: object, **_kw: object) -> None:
            raise TimeoutError("synthetic mcp timeout")

        monkeypatch.setattr(
            "vaultspec_rag.serviceclient._transport._do_http_call", mock_timeout
        )

        result = cli_mod._try_http_reindex(
            "vault",
            False,
            8766,
            "/tmp/proj",
            initiator_kind="cli",
        )
        assert isinstance(result, dict)
        assert result.get("ok") is False
        assert result.get("error") == "http_call_failed"

    def test_connection_refused_still_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Explicit ConnectionRefusedError must keep the dead-service path."""

        from .. import cli as cli_mod

        def _refuse(*_args: object, **_kwargs: object) -> None:
            raise ConnectionRefusedError("port closed")

        monkeypatch.setattr(
            "vaultspec_rag.serviceclient._transport._do_http_call", _refuse
        )

        result = cli_mod._try_http_search(
            "q",
            "code",
            5,
            8766,
            "/tmp/proj",
        )
        assert result is None


class TestSearchSafetyContract:
    """Fail-hard fast path + path indicator + tqdm suppression."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_search_port_dead_default_fails_hard(self, tmp_path: Path):
        """--port unreachable + no --allow-fallback exits non-zero."""
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "anything",
                "--limit",
                "3",
                "--port",
                "1",
            ],
        )
        assert result.exit_code != 0
        normalized = " ".join(result.output.split())
        assert "unreachable" in normalized.lower()
        assert "allow-fallback" in normalized.lower()
        assert "local search index" in normalized
        assert "one user only" in normalized
        assert "agents waiting" not in normalized
        assert "single-agent" not in normalized
        assert "Qdrant lock" not in normalized
        assert "in-process" not in normalized

    def test_search_port_dead_with_allow_fallback_no_warning(self, tmp_path: Path):
        """--allow-fallback does NOT emit the legacy fallthrough warning."""
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "anything",
                "--port",
                "1",
                "--allow-fallback",
            ],
        )
        normalized = " ".join(result.output.split())
        assert "falling back to in-process" not in normalized

    def test_index_exclude_warning_uses_running_service_language(self, tmp_path: Path):
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "code",
                "--port",
                "1",
                "--exclude",
                "temp.py",
            ],
        )

        assert result.exit_code != 0
        normalized = " ".join(result.output.split())
        assert "--exclude is ignored when using the running service." in normalized
        assert "RAG service" not in normalized

    def test_search_command_renders_numbered_results_from_http_response(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread, requests = _search_output_contract_server()
        try:
            result = _invoke_search_contract(tmp_path, server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert requests == [_expected_code_search_request(tmp_path, "service status")]
        records = _search_records(result.output)
        assert [record["number"] for record in records] == [1, 2]
        _assert_record(
            records[0],
            number=1,
            location="src/search_ui.py:12",
            text="def render_search_results():\nreturn 'full service text'",
        )
        _assert_record(
            records[1],
            number=2,
            location="docs/ops.md#service-status",
            text="Use server status for service readiness and current work.",
        )
        lines = _plain_lines(result.output)
        assert lines[0] == "1. src/search_ui.py:12"
        assert lines[1] == "def render_search_results():"
        assert lines[2] == "return 'full service text'"
        assert " - " not in lines[0]
        _assert_no_table_borders(result.output)

    def test_search_structure_filter_sends_service_node_type(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread, requests = _search_output_contract_server()
        try:
            result = _invoke_search_contract(
                tmp_path,
                server.server_port,
                "--structure",
                "function",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        expected = _expected_code_search_request(tmp_path, "service status")
        expected["node_type"] = "function"
        assert requests == [expected]
        assert "--node-type" not in result.output

    def test_search_prefer_accepts_user_facing_value_alias(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread, requests = _search_output_contract_server()
        try:
            result = _invoke_search_contract(
                tmp_path,
                server.server_port,
                "--prefer",
                "production",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        expected = _expected_code_search_request(tmp_path, "service status")
        expected["prefer"] = "prod"
        assert requests == [expected]

    def test_search_command_humanizes_missing_result_location(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread, requests = _sparse_search_output_contract_server()
        try:
            result = _invoke_search_contract(tmp_path, server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert requests == [_expected_code_search_request(tmp_path, "service status")]
        records = _search_records(result.output)
        _assert_record(
            records[0],
            number=1,
            location="location-not-reported",
            text="result text without a source location",
        )
        assert "<unknown>" not in result.output
        assert "unknown" not in result.output.lower()
        _assert_no_table_borders(result.output)

    def test_search_command_scores_flag_uses_plain_score_label(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread, _requests = _search_output_contract_server()
        try:
            result = _invoke_search_contract(tmp_path, server.server_port, "--scores")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        records = _search_records(result.output)
        _assert_record(
            records[0],
            number=1,
            location="src/search_ui.py:12",
            text="def render_search_results():\nreturn 'full service text'",
            score="0.8750",
        )
        _assert_no_table_borders(result.output)

    def test_empty_search_command_humanizes_service_diagnostics(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread, requests = _empty_search_contract_server()
        try:
            result = runner.invoke(
                app,
                [
                    "--target",
                    str(tmp_path),
                    "search",
                    "missing symbol",
                    "--type",
                    "code",
                    "--limit",
                    "2",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert requests == [_expected_code_search_request(tmp_path, "missing symbol")]
        lines = _plain_lines(result.output)
        assert lines[0].endswith("missing symbol")
        assert lines[1].startswith("Why:")
        assert "No indexed code items are available" in lines[1]
        count_match = re.fullmatch(r"Indexed source code sections: (\d+)\.", lines[2])
        assert count_match is not None
        assert int(count_match.group(1)) == 0
        assert "Project mismatch: requested project differs from indexed project." in (
            lines
        )
        assert "Requested project: current project" in lines
        assert "Indexed project: other project" in lines
        next_actions = lines[lines.index("Next actions:") + 1 :]
        assert next_actions == [
            "- vaultspec-rag index --type code --port 8766",
            "- vaultspec-rag server status",
        ]
        assert "index is for" not in result.output
        assert not any("=" in line for line in lines)

    def test_empty_local_fallback_search_is_actionable(self, tmp_path: Path) -> None:
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "missing local symbol",
                "--type",
                "vault",
                "--limit",
                "1",
                "--port",
                "1",
                "--allow-fallback",
            ],
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert lines[0].endswith("missing local symbol")
        labels = _label_values(result.output)
        assert labels["Why"].startswith("No matching vault documents")
        assert "local index" in labels["Why"]
        assert labels["Project"] == str(tmp_path)
        next_actions = lines[lines.index("Next actions:") + 1 :]
        assert next_actions == [
            "- vaultspec-rag index --type vault",
            "- vaultspec-rag status",
        ]
        assert "No vault results found" not in result.output
        _assert_no_table_borders(result.output)

    def test_suppress_hf_progress_sets_env(self, monkeypatch: pytest.MonkeyPatch):
        """_suppress_hf_progress sets the HF env vars idempotently."""
        from ..cli import _suppress_hf_progress

        monkeypatch.delenv("HF_HUB_DISABLE_PROGRESS_BARS", raising=False)
        monkeypatch.delenv("TRANSFORMERS_VERBOSITY", raising=False)
        _suppress_hf_progress()
        assert os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"
        assert os.environ["TRANSFORMERS_VERBOSITY"] == "error"

    def test_search_locked_store_raises_actionable_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Locked store in direct search prints a friendly routing-mode message."""
        from ..store import VaultStoreLockedError

        (tmp_path / ".vaultspec").mkdir()

        def mock_search(*_args: object, **_kwargs: object) -> None:
            raise VaultStoreLockedError(str(tmp_path / "db"))

        monkeypatch.setattr("vaultspec_rag.search_vault", mock_search)
        monkeypatch.setattr(
            "vaultspec_rag.cli._search._default_service_port", lambda: None
        )

        # Search is service-first: the local store is only opened under an
        # explicit local mandate, so --allow-fallback is required to reach the
        # in-process path that surfaces the locked-store message.
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "anything",
                "--allow-fallback",
            ],
        )
        assert result.exit_code != 0
        normalized = " ".join(result.output.split())
        assert "local search index" in normalized
        assert "background service" in normalized
        assert "automatic index update" in normalized
        assert "vaultspec-rag server status" in normalized
        assert "vaultspec-rag server stop" in normalized
        assert "orphaned Python process" in normalized
        assert "server mcp" not in normalized
        assert "MCP" not in normalized
        assert "direct local-store search" not in normalized
        assert "RAG service" not in normalized
        assert "file watcher" not in normalized

    def test_search_locked_store_json_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Locked store in direct search under --json outputs local_store_locked."""
        import json

        from ..store import VaultStoreLockedError

        (tmp_path / ".vaultspec").mkdir()

        def mock_search(*_args: object, **_kwargs: object) -> None:
            raise VaultStoreLockedError(str(tmp_path / "db"))

        monkeypatch.setattr("vaultspec_rag.search_vault", mock_search)
        monkeypatch.setattr(
            "vaultspec_rag.cli._search._default_service_port", lambda: None
        )

        # Service-first: --allow-fallback is the explicit mandate that opens the
        # local store, the only path that can report local_store_locked.
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "anything",
                "--allow-fallback",
                "--json",
            ],
        )
        assert result.exit_code != 0
        data = json.loads(result.output.strip())
        assert data["ok"] is False
        assert data["error"] == "local_store_locked"
        assert "local search index" in data["message"]
        assert "background service" in data["message"]
        assert "automatic index update" in data["message"]
        remediation = data["remediation"]
        assert "vaultspec-rag server status" in remediation
        assert "vaultspec-rag server stop" in remediation
        assert not any("server mcp" in item.lower() for item in remediation)
        assert "direct local-store search" not in data["message"]
        assert "RAG service" not in data["message"]
        assert "file watcher" not in data["message"]

    def test_search_mcp_timeout_diagnostics(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Timeout in client inside _try_http_search returns http_search_timeout."""
        from ..cli import _try_http_search

        def mock_timeout(*_args: object, **_kwargs: object) -> None:
            raise TimeoutError("connection timed out")

        monkeypatch.setattr(
            "vaultspec_rag.serviceclient._transport._do_http_call", mock_timeout
        )

        res = _try_http_search(
            query="test",
            search_type="vault",
            top_k=5,
            port=8766,
            project_root=str(tmp_path),
            timeout=0.01,
        )
        assert isinstance(res, dict)
        assert res["ok"] is False
        assert res["error"] == "http_search_timeout"
        msg = res["message"]
        assert isinstance(msg, str)
        assert "timed out after" in msg
        assert "same_project_search_strategy" not in msg

    def test_search_timeout_human_output_is_plain_diagnostic(
        self, tmp_path: Path
    ) -> None:
        """Default search timeout output is natural text, not a backend table."""
        (tmp_path / ".vaultspec").mkdir()
        server, thread = _slow_search_contract_server()
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
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert result.exit_code == 1, result.output
        labels = _label_values(result.output)
        folded = " ".join(_plain_lines(result.output))
        assert re.match(
            rf"Error: The search request to the service on port {port} "
            r"timed out after 0\.001 seconds",
            folded,
        )
        assert "active index jobs before retrying." in folded
        assert labels["Service"] == "reachable; requests ready; 3 projects loaded"
        assert labels["Work"] == "no active index jobs"
        lines = _plain_lines(result.output)
        next_actions = lines[lines.index("Next actions:") + 1 :]
        assert next_actions == [
            f"- vaultspec-rag server status --port {port}",
            f"- vaultspec-rag server jobs --state active --port {port}",
            "- Rerun the same search with --timeout 300",
        ]
        assert "running jobs before retrying" not in result.output
        assert "running index jobs" not in result.output
        assert "health check" not in result.output
        for forbidden in (
            "same_project_search_strategy",
            "Backend Contract",
            "Search Concurrency",
            "Cross-project Search",
            "Storage Process Model",
            "http_search_timeout",
            "┌",
            "│",
            "└",
        ):
            assert forbidden not in result.output

    def test_search_timeout_missing_health_status_is_reported_absence(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread = _slow_search_contract_server(
            health_payload={
                "project_count": 1,
                "backend_capabilities": {
                    "same_project_search_strategy": "serialized",
                },
            }
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
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert result.exit_code == 1, result.output
        labels = _label_values(result.output)
        assert (
            labels["Service"]
            == "reachable; request status not reported by service; 1 project loaded"
        )
        assert labels["Work"] == "no active index jobs"
        assert "unknown" not in result.output.lower()
        _assert_no_table_borders(result.output)

    def test_search_timeout_jobs_error_is_reported_absence(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread = _slow_search_contract_server(
            jobs_payload={
                "ok": False,
                "error": "jobs_unavailable",
                "message": "Job summary is not available.",
            },
            jobs_status_code=503,
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
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert result.exit_code == 1, result.output
        labels = _label_values(result.output)
        assert labels["Service"] == "reachable; requests ready; 3 projects loaded"
        assert (
            labels["Work"]
            == "jobs check not reported by service (Job summary is not available.)"
        )
        assert "unknown" not in result.output.lower()
        _assert_no_table_borders(result.output)

    def test_search_timeout_json_preserves_backend_diagnostics(
        self, tmp_path: Path
    ) -> None:
        """JSON timeout output keeps full diagnostic fields for agents."""
        (tmp_path / ".vaultspec").mkdir()
        server, thread = _slow_search_contract_server()
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
                    "--json",
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert result.exit_code == 1, result.output
        envelope = json.loads(result.output)
        assert envelope["ok"] is False
        assert envelope["command"] == "search"
        assert envelope["error"] == "http_search_timeout"
        assert envelope["backend_capabilities"]["same_project_search_strategy"] == (
            "serialized"
        )
        diagnostics = envelope["diagnostics"]
        assert diagnostics["backpressure"]["same_project_search_strategy"] == (
            "serialized"
        )
        assert diagnostics["health"]["status"] == "ready"
        assert diagnostics["jobs"]["running_count"] == 0


_FORBIDDEN_DOCSTRING_TOKENS = ("Args:", "Raises:", "CLIState", " ctx ")


class TestHelpCleanup:
    """Verify --help output is operator-facing and free of developer sections.

    Each test invokes the command's --help via CliRunner and asserts:
    - No developer docstring tokens (Args:, Raises:, CLIState, ctx).
    - The operator summary is present.

    W03.P06.S13 (#170).
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def _assert_clean(self, result: typing.Any) -> None:
        """Shared guard: no forbidden tokens in help output."""
        out = result.output
        for token in _FORBIDDEN_DOCSTRING_TOKENS:
            assert token not in out, (
                f"Forbidden token {token!r} found in help output:\n{out}"
            )

    def test_index_help_clean(self):
        result = runner.invoke(app, ["index", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        normalized = " ".join(result.output.split())
        assert "Build or update" in result.output
        assert "Uses the running service" in normalized
        assert "selected service is not reachable" in normalized
        assert "--dry-run-limit" in result.output
        assert "selected service is unavailable" not in normalized
        for forbidden in ("Qdrant", "tqdm", "agent / CI", "fast path"):
            assert forbidden not in normalized

    def test_index_help_cross_ref(self):
        """index --help must reference docs/indexing.md."""
        result = runner.invoke(app, ["index", "--help"])
        assert result.exit_code == 0, result.output
        assert "docs/indexing.md" in result.output

    def test_clean_help_clean(self):
        result = runner.invoke(app, ["clean", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        normalized = " ".join(result.output.split())
        assert "Delete selected index data" in normalized
        assert "search index data" not in normalized
        assert "Required so nothing is deleted by accident" in normalized
        for forbidden in ("Qdrant", "metadata sidecars", "collections", "footgun"):
            assert forbidden not in normalized

    def test_clean_help_cross_ref(self):
        """clean --help must reference docs/indexing.md."""
        result = runner.invoke(app, ["clean", "--help"])
        assert result.exit_code == 0, result.output
        assert "docs/indexing.md" in result.output

    def test_search_help_clean(self):
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        normalized = " ".join(result.output.split())
        assert "selected service is not reachable" in normalized
        assert "selected service is unavailable" not in normalized
        assert "production, tests, or documentation" in normalized
        assert "'prod', 'tests', or 'docs'" not in normalized
        assert "default 300 seconds" in normalized
        assert "hybrid" in result.output.lower() or "Search" in result.output

    def test_search_help_filter_options_are_plain(self):
        """search --help must list filters without Rich box panels."""
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0, result.output
        descriptions = _help_option_descriptions(result.output)
        assert {"--language", "--structure", "--doc-type"} <= descriptions.keys()
        assert "--node-type" not in descriptions
        structure_help = descriptions["--structure"].lower()
        assert "code results" in structure_help
        assert any(word in structure_help for word in ("structure", "construct"))
        for jargon in ("syntax", "ast", "tree-sitter"):
            assert jargon not in structure_help
        for forbidden in ("─", "│", "┌", "┐", "└", "┘"):
            assert forbidden not in result.output

    def test_root_help_uses_user_facing_language(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0, result.output
        assert "search project documentation and source code" in result.output
        assert "Manage the background search service" in result.output
        assert "Inspect and validate document preprocessing rules" in result.output
        assert "Index data directory" in result.output
        assert "Index data subdirectory" in result.output
        assert "service runtime files" in result.output
        assert "Service log filename inside --status-dir" in result.output
        assert "--storage-dir" in result.output
        for forbidden in (
            "Qdrant",
            "Search data directory",
            "Search storage directory",
            "Index storage directory",
            "service status files",
            "relative to --status-dir",
            "--qdrant-dir",
            "--index-meta",
            "--code-index-meta",
            "MCP protocol adapter",
            "#185",
            "metadata filename",
        ):
            assert forbidden not in result.output

    @pytest.mark.parametrize(
        "argv",
        [
            ["--qdrant-dir", "legacy-storage", "--help"],
            ["--index-meta", "index.json", "--help"],
            ["--code-index-meta", "code-index.json", "--help"],
        ],
    )
    def test_removed_root_config_aliases_are_not_supported(self, argv: list[str]):
        result = runner.invoke(app, argv)

        assert result.exit_code != 0
        assert "No such option" in result.output

    def test_server_help_uses_user_facing_language(self):
        result = runner.invoke(app, ["server", "--help"])
        assert result.exit_code == 0, result.output
        assert "Manage the background search service" in result.output
        assert "Manage the HTTP RAG service" not in result.output
        assert "Model Context Protocol" not in result.output
        assert "MCP" not in result.output
        assert "mcp" not in result.output.lower()
        assert "MCP protocol adapter" not in result.output

    def test_status_help_clean(self):
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        assert "index counts" in result.output
        assert "index data location" in result.output
        assert "storage location" not in result.output
        assert "search data location" not in result.output
        assert "Emit JSON for scripts" in result.output
        assert "MCP" not in result.output
        assert "get_index_status" not in result.output

    def test_search_help_includes_limit_alias(self):
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0, result.output
        assert "--max-results" in result.output
        assert "--limit" in result.output
        assert "Maximum number of results" in result.output

    def test_status_help_cross_ref(self):
        """status --help must reference docs/indexing.md."""
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0, result.output
        assert "docs/indexing.md" in result.output

    def test_server_start_help_clean(self):
        result = runner.invoke(app, ["server", "start", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        out = result.output.lower()
        assert "detached" in out or "background" in out
        assert "--updates" in result.output
        assert "--no-updates" in result.output
        assert "--update-delay-ms" in result.output
        assert "--repeat-update-delay-s" in result.output
        assert "--same-project-delay-s" not in result.output
        assert "--same-source-delay-s" not in result.output
        assert "--watch" not in result.output
        assert "--no-watch" not in result.output
        assert "--watch-debounce-ms" not in result.output
        assert "--watch-cooldown-s" not in result.output
        assert "/health" not in result.output
        assert "auto-reindex" not in out
        assert "watcher" not in out
        assert "VAULTSPEC_RAG_WATCH_ENABLED" not in result.output

    def test_server_start_port_in_use_gives_next_actions(self, tmp_path: Path):
        import socket

        # Isolate the status dir so the idempotent already-running check (now the
        # first guard) finds no recorded service and falls through to the port
        # guard - otherwise an ambient running service would make start return
        # `already_running` regardless of the bound port (service-tests-isolate-
        # status-dir).
        prior_status = os.environ.get(EnvVar.STATUS_DIR)
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "status")
        reset_rag_config()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = int(sock.getsockname()[1])
        try:
            result = runner.invoke(app, ["server", "start", "--port", str(port)])
        finally:
            sock.close()
            if prior_status is None:
                os.environ.pop(EnvVar.STATUS_DIR, None)
            else:
                os.environ[EnvVar.STATUS_DIR] = prior_status
            reset_rag_config()

        assert result.exit_code == 1, result.output
        assert f"Port {port} is already in use." in result.output
        assert "Another process is already using this service address." in result.output
        assert "Next actions:" in result.output
        assert f"vaultspec-rag server status --port {port}" in result.output
        assert (
            f"vaultspec-rag server jobs --state active --port {port}" in result.output
        )
        assert "vaultspec-rag server start --port <free-port>" in result.output
        assert "Traceback" not in result.output

    def test_server_start_update_options_parse_before_port_guard(self, tmp_path: Path):
        import socket

        # Isolated status dir so the idempotent check falls through to the port
        # guard (service-tests-isolate-status-dir).
        prior_status = os.environ.get(EnvVar.STATUS_DIR)
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "status")
        reset_rag_config()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = int(sock.getsockname()[1])
        try:
            result = runner.invoke(
                app,
                [
                    "server",
                    "start",
                    "--port",
                    str(port),
                    "--updates",
                    "--update-delay-ms",
                    "250",
                    "--repeat-update-delay-s",
                    "1.5",
                ],
            )
        finally:
            sock.close()
            if prior_status is None:
                os.environ.pop(EnvVar.STATUS_DIR, None)
            else:
                os.environ[EnvVar.STATUS_DIR] = prior_status
            reset_rag_config()

        assert result.exit_code == 1, result.output
        assert f"Port {port} is already in use." in result.output
        assert "No such option" not in result.output

    @pytest.mark.parametrize(
        "argv",
        [
            ["server", "start", "--watch"],
            ["server", "start", "--no-watch"],
            ["server", "start", "--watch-debounce-ms", "250"],
            ["server", "start", "--same-project-delay-s", "1.5"],
            ["server", "start", "--same-source-delay-s", "1.5"],
            ["server", "start", "--watch-cooldown-s", "1.5"],
        ],
    )
    def test_server_start_removed_legacy_update_flags_are_not_supported(
        self,
        argv: list[str],
    ):
        result = runner.invoke(app, argv)

        assert result.exit_code != 0
        assert "No such option" in result.output
        assert "Starting service" not in result.output

    def test_server_warmup_help_clean(self):
        result = runner.invoke(app, ["server", "warmup", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        assert "model" in result.output.lower() or "GPU" in result.output

    def test_server_warmup_help_cross_ref(self):
        """server warmup --help must reference docs/indexing.md."""
        result = runner.invoke(app, ["server", "warmup", "--help"])
        assert result.exit_code == 0, result.output
        assert "docs/indexing.md" in result.output

    def test_mcp_start_help_removed(self):
        result = runner.invoke(app, ["server", "mcp", "start", "--help"])
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_benchmark_verb_removed(self):
        # D9: dev-only quality/benchmark tooling no longer ships as production
        # CLI verbs; the capability is retained in the marked test suite.
        result = runner.invoke(app, ["benchmark", "--help"])
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_quality_verb_removed(self):
        result = runner.invoke(app, ["quality", "--help"])
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_install_help_clean(self):
        result = runner.invoke(app, ["install", "--help"])
        assert result.exit_code == 0, result.output
        assert "Set up vaultspec-rag in a workspace" in result.output
        assert "Emit JSON for scripts" in result.output
        assert "use --yes or --no-torch-config" in result.output
        for forbidden in (
            "Torch-config gating",
            "MCP source files",
            "provider concept",
            "torch_config_action",
            "rag's bundled",
            "Output result as JSON",
            "``--yes``",
            "``--no-torch-config``",
        ):
            assert forbidden not in result.output

    def test_uninstall_help_clean(self):
        result = runner.invoke(app, ["uninstall", "--help"])
        assert result.exit_code == 0, result.output
        assert "Remove vaultspec-rag setup" in result.output
        assert "Emit JSON for scripts" in result.output
        assert "index data under .vault/data/" in result.output
        assert "search data" not in result.output
        assert "``--force``" not in result.output
        for forbidden in (
            "MCP source files",
            "rag's index",
            "forward compat",
            "vaultspec-core",
            "Output result as JSON",
        ):
            assert forbidden not in result.output


class TestCleanRequiredTarget:
    """Clean target is required (no default)."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_clean_no_target_errors(self, tmp_path: Path):
        """`vaultspec-rag clean` without a target exits non-zero."""
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "clean"],
        )
        # Typer surfaces missing required argument with exit code 2
        # and "Missing argument" in stderr.
        assert result.exit_code != 0


class TestSearchResultRendering:
    """Human search results are line-oriented and never silently truncated."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def _render(
        self,
        result: dict[str, object],
        *,
        show_scores: bool = False,
    ) -> str:
        from io import StringIO

        from rich.console import Console

        out = StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "vaultspec_rag.cli.console",
                Console(file=out, force_terminal=False, width=400),
            )
            _display_search_results(
                [result],
                "code",
                via="service",
                show_scores=show_scores,
            )
        return out.getvalue()

    def test_default_keeps_full_snippet(self):
        """Default output renders the full snippet."""
        rendered = self._render({"path": "foo.py", "score": 0.9, "snippet": "a" * 300})
        [record] = _search_records(rendered)
        assert record["text"] == "a" * 300

    def test_scores_are_hidden_by_default(self):
        """Default output shows numbering, not numeric relevance score."""
        rendered = self._render({"path": "foo.py", "score": 0.9, "snippet": "test"})
        [record] = _search_records(rendered)
        assert record["number"] == 1
        assert record["location"] == "foo.py"
        assert record["score"] is None

    def test_scores_flag_renders_numeric_score(self):
        """--scores detail mode includes the relevance score."""
        rendered = self._render(
            {"path": "foo.py", "score": 0.9, "snippet": "test"},
            show_scores=True,
        )
        [record] = _search_records(rendered)
        assert record["score"] == "0.9000"

    def test_display_empty_results(self):
        """Empty results list renders without raising."""
        _display_search_results([], "vault")

    def test_display_missing_fields(self):
        """Dict with no keys renders without raising."""
        _display_search_results([{}], "vault")

    def test_display_with_line_start(self):
        """Result with line_start appends :N to location."""
        rendered = self._render(
            {"path": "foo.py", "score": 0.9, "snippet": "test", "line_start": 42},
        )
        [record] = _search_records(rendered)
        assert record["location"] == "foo.py:42"

    def test_display_without_line_start(self):
        """Result without line_start renders location as bare path."""
        rendered = self._render({"path": "foo.py", "score": 0.9, "snippet": "test"})
        [record] = _search_records(rendered)
        assert record["location"] == "foo.py"

    def test_display_with_anchor_prefers_deep_link(self):
        """Anchor locators stay mechanically grabbable."""
        rendered = self._render(
            {
                "path": "report.pdf",
                "anchor": "report.pdf#page=4",
                "line_start": 12,
                "score": 0.9,
                "snippet": "test",
            }
        )
        [record] = _search_records(rendered)
        assert record["location"] == "report.pdf#page=4"

    def test_display_service_lock_error_hides_backend_contract(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """Default service errors do not render backend contract tables."""
        _display_service_error(
            {
                "ok": False,
                "error": "local_store_locked",
                "message": "Route concurrent searches through one service.",
                "db_path": "/tmp/qdrant",
                "backend_capabilities": {
                    "same_project_search_strategy": "serialized",
                    "cross_project_search_strategy": "parallel",
                    "local_storage_process_model": "exclusive",
                },
            },
        )

        out = capsys.readouterr().out
        assert "Route concurrent searches through one service." in out
        assert "local_store_locked" in out
        assert "Index data: /tmp/qdrant" in out
        assert "DB path:" not in out
        assert "same-project local backend access" not in out
        assert "same_project_search_strategy" not in out
        assert "serialized" not in out
        for forbidden in ("┌", "└", "│"):
            assert forbidden not in out

    def test_display_service_error_fallback_uses_plain_service_name(
        self, capsys: pytest.CaptureFixture[str]
    ):
        _display_service_error({"ok": False, "error": "service_error"})

        out = capsys.readouterr().out
        assert "Search service returned an error." in out
        assert "RAG service" not in out

    def test_display_search_timeout_error_humanizes_diagnostics(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """Search timeout errors answer readiness/work status without raw keys."""
        _display_service_error(
            {
                "ok": False,
                "error": "http_search_timeout",
                "message": (
                    "HTTP search on port 8766 timed out after 180.0s. "
                    "The service may still be processing the request. "
                    "Service status=unknown; running_jobs=unknown; "
                    "same_project_search_strategy=serialized."
                ),
                "backend_capabilities": {
                    "same_project_search_strategy": "serialized",
                    "cross_project_search_strategy": "parallel",
                    "local_storage_process_model": "exclusive",
                },
                "diagnostics": {
                    "health": {
                        "available": False,
                        "error": "TimeoutError",
                        "message": "timed out",
                    },
                    "jobs": {
                        "available": True,
                        "running_count": 2,
                    },
                },
                "remediation": [
                    "vaultspec-rag search ... --port 8766 --timeout 360",
                    "vaultspec-rag server status",
                    "vaultspec-rag server jobs --state active --port 8766",
                ],
            },
        )

        out = capsys.readouterr().out
        assert "HTTP search on port 8766 timed out after 180.0s." in out
        assert "Service: request check timed out" in out
        assert "Work: 2 active index jobs" in out
        assert "vaultspec-rag server jobs --state active --port 8766" in out
        assert "same_project_search_strategy" not in out
        assert "serialized" not in out
        for forbidden in ("┌", "└", "│"):
            assert forbidden not in out

    def test_display_search_timeout_missing_job_count_uses_absence_language(
        self, capsys: pytest.CaptureFixture[str]
    ):
        _display_service_error(
            {
                "ok": False,
                "error": "http_search_timeout",
                "message": "HTTP search on port 8766 timed out after 180.0s.",
                "diagnostics": {
                    "health": {
                        "available": True,
                        "status": "ready",
                    },
                    "jobs": {
                        "available": True,
                    },
                },
            },
        )

        out = capsys.readouterr().out
        assert "Service: reachable; requests ready" in out
        assert "Work: active job count not reported by service" in out
        assert "running work status unknown" not in out
        assert "unknown" not in out
        assert "health check" not in out


class TestWinShutdownLog:
    """CLI appends a lifecycle shutdown line on win32.

    The daemon's atexit / lifespan ``finally`` never fire under
    Windows ``TerminateProcess`` (which is what ``os.kill(SIGTERM)``
    becomes on win32). The CLI parent emits a mirror line so the
    audit trail stays uniform with POSIX.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_append_writes_expected_format(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from .. import cli

        log_path = tmp_path / "service.log"
        monkeypatch.setattr(cli, "_log_file", lambda: log_path)

        cli._append_lifecycle_shutdown_log(
            "cli_terminate",
            pid=123,
            platform="win32",
        )

        content = log_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        assert len(lines) == 1
        line = lines[0]
        assert "WARNING  cli.lifecycle" in line
        assert "event=shutdown" in line
        assert "reason=cli_terminate" in line
        assert "pid=123" in line
        assert "platform=win32" in line

    def test_append_oserror_is_suppressed_and_debug_logged(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        """OSError on the append must NOT crash the shutdown path.

        No-swallow rule: the helper must debug-log the exception so
        the suppression is observable.
        """
        from .. import cli

        missing_dir = tmp_path / "nonexistent" / "service.log"
        monkeypatch.setattr(cli, "_log_file", lambda: missing_dir)

        with caplog.at_level("DEBUG", logger="vaultspec_rag.cli"):
            cli._append_lifecycle_shutdown_log("cli_terminate", pid=42)

        # No exception escapes; the debug line is present.
        debug_records = [
            r
            for r in caplog.records
            if r.name == "vaultspec_rag.cli"
            and "lifecycle log append failed" in r.getMessage()
        ]
        assert debug_records, (
            "OSError on append must be debug-logged per the no-swallow rule"
        )
        # The log file was never created (the parent directory does
        # not exist) - confirms the exception path was exercised.
        assert not missing_dir.exists()

    def test_service_stop_emits_log_on_win32(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """End-to-end: ``server stop`` on win32 appends the line."""
        from .. import cli

        status_dir = tmp_path / "status"
        status_dir.mkdir()
        log_path = status_dir / "service.log"

        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        try:
            # Set up a status file pointing at the current process so
            # _is_our_service returns True for the test.
            _write_service_status(pid=os.getpid(), port=18999)

            # Treat the current process as the service so service_stop
            # walks past the validation guard, into the stubbed termination,
            # the unlink, and the new log-append branch we want to exercise.
            def _stub_is_our_service(*_a: object, **_kw: object) -> bool:
                return True

            def _stub_terminate_pid(_pid: int) -> None: ...

            def _stub_is_pid_alive(_pid: int) -> bool:
                return False

            monkeypatch.setattr(cli, "_is_our_service", _stub_is_our_service)
            monkeypatch.setattr(cli, "_terminate_pid", _stub_terminate_pid)
            # The post-terminate poll iterates until _is_pid_alive returns
            # False; stub False so the wait collapses immediately.
            monkeypatch.setattr(cli, "_is_pid_alive", _stub_is_pid_alive)
            monkeypatch.setattr(cli.sys, "platform", "win32")

            result = runner.invoke(app, ["server", "stop"])
            assert result.exit_code == 0, result.output
            assert f"Process ID: {os.getpid()}" in result.output
            assert "PID:" not in result.output
            assert log_path.exists(), (
                f"Expected CLI to create {log_path}; result: {result.output}"
            )

            content = log_path.read_text(encoding="utf-8")
            assert "event=shutdown" in content
            assert "reason=cli_terminate" in content
            assert f"pid={os.getpid()}" in content
            assert "platform=win32" in content
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_service_stop_emits_log_on_posix_too(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """POSIX also gets the CLI-side initiator line (emitted on every platform)."""
        from .. import cli

        status_dir = tmp_path / "status"
        status_dir.mkdir()
        log_path = status_dir / "service.log"

        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        try:
            _write_service_status(pid=os.getpid(), port=18999)

            def _stub_is_our_service(*_a: object, **_kw: object) -> bool:
                return True

            def _stub_terminate_pid(_pid: int) -> None: ...

            def _stub_is_pid_alive(_pid: int) -> bool:
                return False

            monkeypatch.setattr(cli, "_is_our_service", _stub_is_our_service)
            monkeypatch.setattr(cli, "_terminate_pid", _stub_terminate_pid)
            monkeypatch.setattr(cli, "_is_pid_alive", _stub_is_pid_alive)
            monkeypatch.setattr(cli.sys, "platform", "linux")

            result = runner.invoke(app, ["server", "stop"])
            assert result.exit_code == 0, result.output
            assert f"Process ID: {os.getpid()}" in result.output
            assert "PID:" not in result.output

            # The CLI-side initiator attribution is emitted on every
            # platform; POSIX additionally gets the daemon's own clean
            # shutdown line via the lifespan finally.
            assert log_path.exists(), (
                "every platform's stop must write the attribution audit line"
            )
            content = log_path.read_text(encoding="utf-8")
            assert "event=shutdown" in content
            assert "reason=cli_terminate" in content
            assert "platform=linux" in content
            assert "initiator_pid" in content
            assert "initiator_cmd" in content
            assert "initiator_cwd" in content
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)


class TestServiceTokenIdentity:
    """Per-process service_token round-trip.

    Daemon writes a uuid4 token into service.json + returns it from
    /health. The CLI compares both - mismatch reports a recycled-PID
    or unrelated-HTTP-server scenario instead of trusting a stale
    truth-lying executable-name check.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_token_match_returns_true(self, monkeypatch: pytest.MonkeyPatch):
        from .. import cli

        def _probe_abc(_port: int) -> dict[str, object]:
            return {"service_token": "abc"}

        def _alive(_pid: int) -> bool:
            return True

        monkeypatch.setattr(cli, "_health_probe", _probe_abc)
        monkeypatch.setattr(cli, "_is_pid_alive", _alive)
        assert cli._is_our_service(123, port=8766, expected_token="abc")

    def test_token_mismatch_returns_false(self, monkeypatch: pytest.MonkeyPatch):
        from .. import cli

        def _probe_abc(_port: int) -> dict[str, object]:
            return {"service_token": "abc"}

        def _alive(_pid: int) -> bool:
            return True

        monkeypatch.setattr(cli, "_health_probe", _probe_abc)
        monkeypatch.setattr(cli, "_is_pid_alive", _alive)
        # Token mismatch is authoritative - return False regardless of
        # whether the executable-name check would have passed.
        assert not cli._is_our_service(123, port=8766, expected_token="xyz")

    def test_token_absent_in_response_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """Pre-upgrade daemon (no token in response) → exe-name fallback."""
        from .. import cli

        def _probe_empty(_port: int) -> dict[str, object]:
            return {}

        def _alive(_pid: int) -> bool:
            return True

        monkeypatch.setattr(cli, "_health_probe", _probe_empty)
        monkeypatch.setattr(cli, "_is_pid_alive", _alive)
        # On Windows the exe-name check inspects the running pytest
        # process (always "python") so this hits the True branch.
        # No-swallow rule: the fallback must debug-log.
        with caplog.at_level("DEBUG", logger="vaultspec_rag.cli"):
            result = cli._is_our_service(
                os.getpid(),
                port=8766,
                expected_token="abc",
            )
        # Result True or False is platform-dependent; the contract
        # under test is the debug log line.
        assert any(
            "service_token absent" in r.getMessage()
            for r in caplog.records
            if r.name == "vaultspec_rag.cli"
        ), "token-absent fallback must debug-log per the no-swallow rule"
        # Sanity: a result was returned (didn't raise).
        assert isinstance(result, bool)

    def test_no_token_in_status_skips_token_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No expected_token (pre-upgrade service.json) → exe-name only."""
        from .. import cli

        probe_called: dict[str, int] = {"n": 0}

        def _probe(_port: int) -> dict[str, str]:
            probe_called["n"] += 1
            return {"service_token": "irrelevant"}

        def _alive_stub(_pid: int) -> bool:
            return True

        monkeypatch.setattr(cli, "_health_probe", _probe)
        monkeypatch.setattr(cli, "_is_pid_alive", _alive_stub)
        # No expected_token → don't probe.
        cli._is_our_service(os.getpid(), port=8766, expected_token=None)
        assert probe_called["n"] == 0

    def test_health_probe_failure_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Network failure on /health → exe-name fallback, no exception."""
        from .. import cli

        def _probe_none(_port: int) -> None:
            return None

        def _alive_stub2(_pid: int) -> bool:
            return True

        monkeypatch.setattr(cli, "_health_probe", _probe_none)
        monkeypatch.setattr(cli, "_is_pid_alive", _alive_stub2)
        # Should fall back without raising.
        result = cli._is_our_service(
            os.getpid(),
            port=8766,
            expected_token="abc",
        )
        assert isinstance(result, bool)


class TestServiceDaemonHelpers:
    """Tests for the service daemon helper functions."""

    def test_is_pid_alive_current_process(self):
        """Current process PID should be alive."""
        assert _is_pid_alive(os.getpid()) is True

    def test_is_pid_alive_impossible_pid(self):
        """An impossibly large PID should not be alive."""
        assert _is_pid_alive(99999999) is False

    def test_is_pid_alive_zero(self):
        """PID 0 should return False."""
        assert _is_pid_alive(0) is False

    def test_is_pid_alive_negative(self):
        """Negative PIDs should return False."""
        assert _is_pid_alive(-1) is False

    def test_is_our_service_current_process(self):
        """Current process (Python) should be recognized as ours."""
        assert _is_our_service(os.getpid()) is True

    def test_is_our_service_dead_pid(self):
        """A dead PID should return False."""
        assert _is_our_service(99999999) is False

    def test_is_our_service_zero(self):
        """PID 0 should return False."""
        assert _is_our_service(0) is False

    def test_is_our_service_negative(self):
        """Negative PIDs should return False."""
        assert _is_our_service(-1) is False

    def test_write_read_status_roundtrip(self, tmp_path: Path):
        """Write and read back should produce the same pid/port."""
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=12345, port=9999)
            data = _read_service_status()
            assert data is not None
            assert data["pid"] == 12345
            assert data["port"] == 9999
            assert "started_at" in data
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_write_creates_valid_json(self, tmp_path: Path):
        """Status file must be valid JSON with expected keys."""
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=42, port=8766)
            import json

            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            assert set(data.keys()) == {
                "schema",
                "version",
                "pid",
                "port",
                "started_at",
            }
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_read_status_missing_file(self, tmp_path: Path):
        """Reading a nonexistent file should return None."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        os.environ[EnvVar.STATUS_DIR] = str(empty_dir)
        try:
            assert _read_service_status() is None
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_read_status_invalid_json(self, tmp_path: Path):
        """Invalid JSON in status file should return None."""
        sf = tmp_path / "service.json"
        sf.write_text("not json", encoding="utf-8")
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            assert _read_service_status() is None
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_read_status_missing_pid_key(self, tmp_path: Path):
        """Status JSON without a pid key should return None."""
        sf = tmp_path / "service.json"
        sf.write_text('{"port": 8766}', encoding="utf-8")
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            assert _read_service_status() is None
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_service_stop_stale_pid(self, tmp_path: Path):
        """service_stop with a dead PID cleans up the status file."""
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=99999999, port=8766)
            sf = tmp_path / "service.json"
            assert sf.exists()

            result = runner.invoke(app, ["server", "stop"])
            assert result.exit_code == 0
            out = result.output.lower()
            assert "no longer running" in out or "cleaned" in out
            assert "recorded process 99999999 is no longer running" in out
            assert "pid:" not in out
            assert not sf.exists()
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_service_status_stale_pid(self, tmp_path: Path):
        """service_status with a dead PID exits 4 and cleans the file.

        Divergent/crashed states exit 4 so scripts can branch on
        "known-bad" without parsing prose.
        """
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=99999999, port=8766)
            sf = tmp_path / "service.json"
            assert sf.exists()

            result = runner.invoke(app, ["server", "status"])
            assert result.exit_code == 4
            lower = result.output.lower()
            assert "crashed" in lower or "stale" in lower
            assert not sf.exists()
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_service_status_stale_pid_verbose_uses_condition_language(
        self, tmp_path: Path
    ):
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=99999999, port=8766)

            result = runner.invoke(app, ["server", "status", "--verbose"])

            assert result.exit_code == 4
            assert "Process: not running" in result.output
            assert (
                "Process check: not verified because the process is not running"
                in result.output
            )
            assert "Network: not accepting connections" in result.output
            assert "Service process:" not in result.output
            assert "not checked" not in result.output
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_health_probe_nonlistening_port(self):
        """Health probe on a port with no listener should return None."""
        assert _health_probe(1) is None

    def test_health_probe_non_json_response(self):
        """Health probe returns None when server sends non-JSON."""
        import http.server
        import threading

        class _GarbageHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"not json at all")

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), _GarbageHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        try:
            result = _health_probe(port)
            assert result is None
        finally:
            server.server_close()
            t.join(timeout=5)

    def test_service_status_default_human_output_is_plain_summary(self, tmp_path: Path):
        """service status renders the W06.P01 plain operator summary by default."""
        import json

        server, thread = _status_contract_server()
        port = server.server_address[1]
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            # A healthy running service writes last_heartbeat to
            # service.json. Without it the divergence check
            # correctly flags "absent + PID alive" as crashed.
            # Inject a fresh heartbeat to model a running daemon.
            _write_service_status(pid=os.getpid(), port=port)
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            from datetime import UTC, datetime

            data["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status"])

            assert result.exit_code == 0
            _assert_default_status_summary(result.output, port)

            verbose = runner.invoke(app, ["server", "status", "--verbose"])
            assert verbose.exit_code == 0
            _assert_verbose_status_summary(verbose.output, port)
            assert "Service record:" not in verbose.output
            assert "Service process:" not in verbose.output
            assert "Service identity:" not in verbose.output
            assert "Identity check: not checked" not in verbose.output
            assert "Started: 2026-" not in verbose.output
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_lists_multiple_active_jobs(self, tmp_path: Path):
        import json

        server, thread = _status_contract_server(extra_running_job=True)
        port = server.server_address[1]
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=os.getpid(), port=port)
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            from datetime import UTC, datetime

            data["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status"])

            assert result.exit_code == 0, result.output
            assert "Busy: processing 2 jobs" in result.output
            assert "Queue: nothing waiting; 2 active jobs" in result.output
            assert "Active jobs:" in result.output
            active_rows = [
                line for line in result.output.splitlines() if line.startswith("  * ")
            ]
            assert len(active_rows) == 2
            assert active_rows[0].startswith("  * vault index update for other-project")
            assert "index documents 5 of 9" in active_rows[0]
            assert active_rows[1].startswith(
                "  * code index refresh for feature-server-supervision"
            )
            assert "embedding source code sections 7 of 20" in active_rows[1]
            assert all(row.count("no progress for") <= 1 for row in active_rows)
            assert "Current job:" not in result.output
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_summary_reports_failed_jobs(self, tmp_path: Path):
        import json

        server, thread = _status_contract_server(failed_jobs=2)
        port = server.server_address[1]
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=os.getpid(), port=port)
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            from datetime import UTC, datetime

            data["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status"])

            assert result.exit_code == 0, result.output
            labels = _label_values(result.output)
            assert (
                labels["Processed jobs"] == "2 finished, 1 active, 0 waiting, 2 failed"
            )
            assert "recent jobs" not in result.output
            assert "Jobs:" not in result.output
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_omits_missing_current_job_project(self, tmp_path: Path):
        import json

        server, thread = _status_contract_server(omit_project=True)
        port = server.server_address[1]
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=os.getpid(), port=port)
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            from datetime import UTC, datetime

            data["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status"])

            assert result.exit_code == 0, result.output
            lines = _plain_lines(result.output)
            assert "Current job:" in lines
            assert "Operation: code index operation" in lines
            assert not any(line.startswith("Project:") for line in lines)
            assert "project not reported" not in result.output
            assert "project unknown" not in result.output
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_missing_start_times_use_reported_absence_language(
        self, tmp_path: Path
    ):
        import json

        server, thread = _status_contract_server(omit_job_started_at=True)
        port = server.server_address[1]
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=os.getpid(), port=port)
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            data.pop("started_at", None)
            from datetime import UTC, datetime

            data["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status", "--verbose"])

            assert result.exit_code == 0, result.output
            labels = _label_values(result.output)
            assert labels["Started"] == "not reported by local record"
            assert labels["Runtime"] == "not reported by service"
            assert "unknown" not in result.output.lower()
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def _service_status_current_job_output(
        self,
        tmp_path: Path,
        *,
        last_progress_age_seconds: float,
    ) -> str:
        import json

        server, thread = _status_contract_server(
            last_progress_age_seconds=last_progress_age_seconds,
        )
        port = server.server_address[1]
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=os.getpid(), port=port)
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            from datetime import UTC, datetime

            data["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status"])

            assert result.exit_code == 0, result.output
            return " ".join(result.output.split())
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_current_job_flags_no_recent_progress(
        self,
        tmp_path: Path,
    ):
        fresh_status = self._service_status_current_job_output(
            tmp_path / "fresh",
            last_progress_age_seconds=2.0,
        )
        stalled_status = self._service_status_current_job_output(
            tmp_path / "stalled",
            last_progress_age_seconds=600.0,
        )

        assert "Current job:" in fresh_status
        assert "Current job:" in stalled_status
        assert "Progress: embedding source code sections 7 of 20" in stalled_status
        assert "no progress for" not in fresh_status
        assert "Warning: no progress for 10 minutes" in stalled_status
        assert stalled_status != fresh_status

    def test_service_status_distinguishes_waiting_from_processing(self):
        from ..cli._service_lifecycle import (
            _status_busy_label,
            _status_jobs_label,
            _status_queue_label,
        )

        jobs: dict[str, object] = {"available": True, "running": 1, "queued": 1}

        assert _status_busy_label(jobs) == "1 job waiting to write"
        assert _status_queue_label(jobs) == "1 waiting job; 0 active jobs"
        assert (
            _status_jobs_label({**jobs, "total": 3, "phases": {"done": 2}})
            == "2 finished, 0 active, 1 waiting, 0 failed"
        )

    def test_service_status_port_only_json(self, tmp_path: Path):
        """server status --port can inspect a reachable service without service.json."""
        import http.server
        import json
        import threading

        class _StatusHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                payload: dict[str, object]
                if self.path == "/health":
                    payload = {
                        "status": "ready",
                        "cuda": True,
                        "models_loaded": True,
                        "project_count": 1,
                        "backend_capabilities": {
                            "same_project_search_strategy": "serialized",
                            "cross_project_search_strategy": "parallel",
                            "local_storage_process_model": "exclusive",
                        },
                    }
                elif self.path.startswith("/jobs"):
                    payload = {
                        "ok": True,
                        "jobs": [],
                        "total": 0,
                        "returned": 0,
                        "summary": {"running": 0, "phases": {}},
                    }
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

        server = http.server.HTTPServer(("127.0.0.1", 0), _StatusHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            result = runner.invoke(
                app,
                ["server", "status", "--port", str(port), "--json"],
            )

            assert result.exit_code == 0
            envelope = json.loads(result.stdout)
            data = envelope["data"]
            assert data["service_json_present"] is False
            assert data["port"] == port
            assert data["state"] == "running"
            operational = data["operational"]
            assert f"--port {port}" in operational["next_action"]
            assert "server info" not in operational["next_action"]
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_sparse_health_uses_reported_absence_language(
        self, tmp_path: Path
    ):
        import http.server
        import threading

        class _SparseHealthHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                payload: dict[str, object]
                if self.path == "/health":
                    payload = {"status": "ready"}
                elif self.path.startswith("/jobs"):
                    payload = {
                        "ok": True,
                        "jobs": [],
                        "total": 0,
                        "returned": 0,
                        "summary": {"running": 0, "phases": {}},
                    }
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

        server = http.server.HTTPServer(("127.0.0.1", 0), _SparseHealthHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            result = runner.invoke(
                app,
                ["server", "status", "--port", str(port), "--verbose"],
            )

            assert result.exit_code == 0, result.output
            labels = _label_values(result.output)
            assert labels["Requests"] == "ready for requests"
            assert "Health" not in labels
            assert labels["Compute"] == "not reported by service"
            assert labels["Search models"] == "not reported by service"
            assert labels["Reranking"] == "not reported by service"
            assert labels["Loaded projects"] == "not reported by service"
            assert labels["Uptime"] == "not reported by service"
            assert "unknown" not in result.output.lower()
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_missing_health_status_is_reported_absence(
        self, tmp_path: Path
    ) -> None:
        import http.server
        import threading

        class _MissingHealthStatusHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                payload: dict[str, object]
                if self.path == "/health":
                    payload = {"uptime_s": 12}
                elif self.path.startswith("/jobs"):
                    payload = {
                        "ok": True,
                        "jobs": [],
                        "total": 0,
                        "returned": 0,
                        "summary": {"running": 0, "phases": {}},
                    }
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

        server = http.server.HTTPServer(("127.0.0.1", 0), _MissingHealthStatusHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            result = runner.invoke(
                app,
                ["server", "status", "--port", str(port)],
            )

            assert result.exit_code == 4, result.output
            labels = _label_values(result.output)
            assert labels["Server"] == "unreachable"
            assert labels["Requests"] == "not reported by service"
            assert "Health" not in labels
            assert labels["Uptime"] == "12 seconds"
            assert "unknown" not in result.output.lower()
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_jobs_error_is_reported_absence(
        self, tmp_path: Path
    ) -> None:
        import http.server
        import threading

        class _JobsErrorStatusHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/health":
                    payload = {"status": "ready", "uptime_s": 60}
                    status_code = 200
                elif self.path.startswith("/jobs"):
                    payload = {
                        "ok": False,
                        "error": "jobs_unavailable",
                        "message": "Job summary is not available.",
                    }
                    status_code = 503
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), _JobsErrorStatusHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            result = runner.invoke(
                app,
                ["server", "status", "--port", str(port)],
            )

            assert result.exit_code == 0, result.output
            labels = _label_values(result.output)
            assert labels["Server"] == "running"
            assert labels["Requests"] == "ready for requests"
            assert "Health" not in labels
            assert labels["Busy"] == "not reported by service"
            assert labels["Queue"] == "not reported by service"
            assert labels["Processed jobs"] == "not reported by service"
            assert labels["Current job"] == "not reported by service"
            assert "unknown" not in result.output.lower()
            assert "unavailable" not in result.output.lower()
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_port_only_verbose_uses_network_language(
        self, tmp_path: Path
    ) -> None:
        """Port-only verbose output should not expose raw yes/no socket labels."""
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            port = _find_free_port()
            result = runner.invoke(
                app,
                ["server", "status", "--port", str(port), "--verbose"],
            )

            assert result.exit_code == 3
            assert "Local record: not found" in result.output
            assert "Process: not reported" in result.output
            assert f"Address: http://127.0.0.1:{port}" in result.output
            assert "Network: not accepting connections" in result.output
            labels = _label_values(result.output)
            assert labels["Server"] == "stopped"
            assert "State" not in labels
            assert "Process ID:" not in result.output
            assert "not checked" not in result.output
            assert "not recorded" not in result.output
            assert "PID:" not in result.output
            assert "Port:" not in result.output
            assert "Port listening" not in result.output
            assert "Port listening: yes" not in result.output
            assert "Port listening: no" not in result.output
            assert "Service file:" not in result.output
            assert "Service record:" not in result.output
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_service_status_port_ignores_stale_service_json(self, tmp_path: Path):
        """server status --port ignores stale service.json."""
        import http.server
        import json
        import threading

        class _StatusHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                payload: dict[str, object]
                if self.path == "/health":
                    payload = {
                        "status": "ready",
                        "cuda": True,
                        "models_loaded": True,
                        "project_count": 1,
                        "backend_capabilities": {
                            "same_project_search_strategy": "serialized",
                            "cross_project_search_strategy": "parallel",
                            "local_storage_process_model": "exclusive",
                        },
                    }
                elif self.path.startswith("/jobs"):
                    payload = {
                        "ok": True,
                        "jobs": [],
                        "total": 0,
                        "returned": 0,
                        "summary": {"running": 0, "phases": {}},
                    }
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

        server = http.server.HTTPServer(("127.0.0.1", 0), _StatusHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=99999999, port=1)
            result = runner.invoke(
                app,
                ["server", "status", "--port", str(port), "--json"],
            )

            assert result.exit_code == 0
            envelope = json.loads(result.stdout)
            data = envelope["data"]
            assert data["service_json_present"] is True
            assert data["pid_alive"] is False
            assert data["port"] == port
            assert data["state"] == "running"
            assert data["operational"]["status_file_port"] == 1

            human = runner.invoke(
                app,
                ["server", "status", "--port", str(port)],
            )

            assert human.exit_code == 0, human.output
            lines = _plain_lines(human.output)
            assert (
                lines[0] == "Local record points to http://127.0.0.1:1; "
                f"checking http://127.0.0.1:{port}."
            )
            assert f"Address: http://127.0.0.1:{port}" in human.output
            assert "probing" not in human.output
            assert "Status file port" not in human.output
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)


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
                                "root": r"Y:\code\busy",
                                "idle_seconds": 65,
                                "ref_count": 2,
                                "last_access_iso": "2026-06-12T14:05:06Z",
                            },
                            {
                                "root": r"Y:\code\ready",
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
                            r"root=Y:\code\feature-server-supervision "
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
                            "project_root": r"Y:\code\finished-project",
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
                            "project_root": r"Y:\code\running-project",
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


class TestServiceLogsCli:
    """In-process CLI coverage for `server logs`."""

    def test_logs_lines_alias_is_not_supported(self) -> None:
        result = runner.invoke(app, ["server", "logs", "--lines", "7"])

        assert result.exit_code != 0
        assert "No such option" in result.output

    def test_empty_logs_offer_wider_bounded_search(self) -> None:
        server, thread, requests = _empty_logs_contract_server()
        try:
            result = runner.invoke(
                app,
                [
                    "server",
                    "logs",
                    "--limit",
                    "5",
                    "--contains",
                    "service.lifecycle",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert requests == ["/logs/json?lines=5&contains=service.lifecycle"]
        lines = _plain_lines(result.output)
        expected_present = [
            f"Address: http://127.0.0.1:{server.server_port}",
            (
                'No service activity found matching text "service.lifecycle" '
                "in the last 5 log lines."
            ),
            "Next actions:",
            (
                "vaultspec-rag server logs --limit 200 "
                f"--port {server.server_port} --contains service.lifecycle"
            ),
            f"vaultspec-rag server jobs --state active --port {server.server_port}",
            f"vaultspec-rag server jobs --state waiting --port {server.server_port}",
            f"vaultspec-rag server status --port {server.server_port}",
            (
                "vaultspec-rag server logs --raw --limit 5 "
                f"--port {server.server_port} --contains service.lifecycle"
            ),
        ]
        missing = [text for text in expected_present if text not in lines]
        assert not missing, f"missing empty-log guidance lines: {missing}"
        assert "Activity: none found" not in result.output
        _assert_no_table_borders(result.output)


class TestServiceJobsCli:
    """In-process CLI coverage for `server jobs`."""

    def test_jobs_empty_filtered_result_stays_actionable(self) -> None:
        server, thread, requests = _jobs_empty_contract_server()
        try:
            result = runner.invoke(
                app,
                [
                    "server",
                    "jobs",
                    "--state",
                    "active",
                    "--limit",
                    "5",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert requests == ["/jobs?limit=5&phase=running"]
        lines = _plain_lines(result.output)
        expected_present = [
            "Jobs",
            f"Address: http://127.0.0.1:{server.server_port}",
            "Displayed: 0 matching jobs",
            "Total: 0 jobs",
            "Displayed jobs: 0 active, 0 waiting, 0 finished, 0 failed",
            "Order: latest job appears last",
            "Filter: state active",
            "There are no active jobs.",
            "Next actions:",
            f"vaultspec-rag server status --port {server.server_port}",
            f"vaultspec-rag server logs --limit 20 --port {server.server_port}",
        ]
        missing = [text for text in expected_present if text not in lines]
        assert not missing, f"missing operator lines: {missing}"
        _assert_no_table_borders(result.output)
        assert "Jobs on service port" not in result.output
        assert "Recent jobs on service" not in result.output
        assert "States:" not in result.output
        assert "watcher" not in result.output.lower()

    def test_jobs_populated_feed_uses_visible_prefixes(self) -> None:
        server, thread, requests = _jobs_populated_contract_server()
        try:
            result = runner.invoke(
                app,
                ["server", "jobs", "--limit", "2", "--port", str(server.server_port)],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert requests == ["/jobs?limit=2"]
        lines = _plain_lines(result.output)
        assert "Legend: * active, ~ waiting, ! failed, - finished" in lines
        finished = [
            line
            for line in lines
            if "finished code index refresh for finished-project" in line
        ]
        active = [
            line
            for line in lines
            if "active vault index update for running-project" in line
        ]
        assert len(finished) == 1
        assert len(active) == 1
        assert finished[0].startswith("- ")
        assert active[0].startswith("* ")
        assert lines.index(finished[0]) < lines.index(active[0])
        _assert_no_table_borders(result.output)


def _assert_project_summary_language(out: str) -> None:
    expected = {
        "Capacity: 1 of 16 projects loaded",
        "Automatic unload: after 30 minutes idle",
        "- Project: example",
        r"  Path: Y:\code\example",
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


class TestServiceProjectsCli:
    """In-process CLI coverage for `server projects list|unload`."""

    def test_projects_list_help_renders(self) -> None:
        result = runner.invoke(
            app,
            ["server", "projects", "list", "--help"],
        )
        assert result.exit_code == 0
        assert "projects currently loaded" in result.output.lower()
        assert "Emit JSON for scripts" in result.output
        assert "JSON envelope" not in result.output
        assert "project slots" not in result.output.lower()
        projects_help = runner.invoke(app, ["server", "projects", "--help"])
        assert projects_help.exit_code == 0
        assert "unload" in projects_help.output.lower()
        assert "evict" not in projects_help.output.lower()

    def test_projects_unload_help_renders(self) -> None:
        result = runner.invoke(
            app,
            ["server", "projects", "unload", "--help"],
        )
        assert result.exit_code == 0
        assert "Unload" in result.output or "unload" in result.output
        assert "PROJECT" in result.output
        assert " ROOT" not in result.output
        assert "Project root" not in result.output
        assert "Emit JSON for scripts" in result.output
        assert "JSON envelope" not in result.output

    def test_projects_evict_alias_is_not_supported(self) -> None:
        result = runner.invoke(
            app,
            ["server", "projects", "evict", "--help"],
        )
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_projects_list_summary_uses_operator_language(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._service_projects import _print_projects_summary

        _print_projects_summary(
            [
                {
                    "root": r"Y:\code\example",
                    "idle_seconds": 125,
                    "ref_count": 1,
                    "last_access_iso": "2026-06-12T14:05:06Z",
                }
            ],
            max_projects=16,
            idle_ttl=1800,
        )

        out = capsys.readouterr().out
        _assert_project_summary_language(out)

    def test_projects_list_service_down_returns_exit_3(self) -> None:
        port = _find_free_port()
        result = runner.invoke(
            app,
            ["server", "projects", "list", "--port", str(port)],
        )
        assert result.exit_code == 3
        assert f"Address: http://127.0.0.1:{port}" in result.output

    def test_projects_unload_service_down_returns_exit_3(self) -> None:
        port = _find_free_port()
        result = runner.invoke(
            app,
            [
                "server",
                "projects",
                "unload",
                "/some/root",
                "--port",
                str(port),
            ],
        )
        assert result.exit_code == 3
        assert f"Address: http://127.0.0.1:{port}" in result.output

    def test_projects_list_command_humanizes_service_payload(self) -> None:
        server, thread, requests = _projects_list_contract_server()
        try:
            result = runner.invoke(
                app,
                ["server", "projects", "list", "--port", str(server.server_port)],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert requests == ["/projects"]
        lines = _plain_lines(result.output)
        expected_present = [
            f"Address: http://127.0.0.1:{server.server_port}",
            "Capacity: 2 of 8 projects loaded",
            "Automatic unload: after 10 minutes idle",
            "- Project: busy",
            r"Path: Y:\code\busy",
            "Active requests: 2",
            "Last activity: 1 minute 5 seconds ago",
            "Last request: 14:05:06",
            "- Project: ready",
            r"Path: Y:\code\ready",
            "Active requests: none",
            "Last activity: 4 seconds ago",
        ]
        missing = [text for text in expected_present if text not in lines]
        assert not missing, f"missing operator lines: {missing}"
        ready_index = lines.index("- Project: ready")
        ready_block = lines[ready_index : ready_index + 4]
        assert ready_block == [
            "- Project: ready",
            r"Path: Y:\code\ready",
            "Active requests: none",
            "Last activity: 4 seconds ago",
        ]
        joined = "\n".join(lines).lower()
        forbidden_substrings = [
            "handling 2 active requests",
            "available for new requests",
            "last used: not recorded",
            "last used:",
            "no timestamp from service",
            "project handle",
            "references",
            "loaded projects:",
            "in use:",
            "active uses:",
            "not currently in use",
        ]
        leaked = [text for text in forbidden_substrings if text in joined]
        assert not leaked, f"internal phrasing leaked: {leaked}"
        leaked_prefixes = [
            line
            for line in lines
            if line.startswith("Requests:") or line in {"yes", "no"}
        ]
        assert not leaked_prefixes, f"internal fields leaked: {leaked_prefixes}"
        _assert_no_table_borders(result.output)

    def test_projects_unload_unexpected_response_stays_actionable(self) -> None:
        server, thread, requests = _projects_unload_contract_server()
        try:
            result = runner.invoke(
                app,
                [
                    "server",
                    "projects",
                    "unload",
                    r"Y:\code\example",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 1, result.output
        assert requests == [{"root": r"Y:\code\example"}]
        labels = _label_values(result.output)
        assert labels["Address"] == f"http://127.0.0.1:{server.server_port}"
        assert labels["Project"] == "example"
        assert labels["Path"] == r"Y:\code\example"
        assert labels["Unload"] == "service could not confirm unload"
        assert (
            labels["Next action"]
            == f"vaultspec-rag server status --port {server.server_port}"
        )
        assert "unexpected" not in result.output
        assert "{" not in result.output

    def test_projects_unload_not_found_uses_project_block(self) -> None:
        server, thread, requests = _projects_unload_contract_server(
            {"evicted": False, "reason": "not_found"}
        )
        try:
            result = runner.invoke(
                app,
                [
                    "server",
                    "projects",
                    "unload",
                    r"Y:\code\not-loaded",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 2, result.output
        assert requests == [{"root": r"Y:\code\not-loaded"}]
        labels = _label_values(result.output)
        assert labels["Address"] == f"http://127.0.0.1:{server.server_port}"
        assert labels["Project"] == "not-loaded"
        assert labels["Path"] == r"Y:\code\not-loaded"
        assert labels["Unload"] == "project is not loaded"
        assert "Project is not loaded:" not in result.output
        _assert_no_table_borders(result.output)

    def test_projects_unload_json_message_stays_user_facing(self) -> None:
        server, thread, requests = _projects_unload_contract_server()
        try:
            result = runner.invoke(
                app,
                [
                    "server",
                    "projects",
                    "unload",
                    r"Y:\code\example",
                    "--port",
                    str(server.server_port),
                    "--json",
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 1, result.output
        assert requests == [{"root": r"Y:\code\example"}]
        envelope = json.loads(result.output)
        assert envelope["ok"] is False
        assert envelope["command"] == "service.projects.unload"
        assert envelope["error"] == "unexpected_response"
        assert r"Y:\code\example" in envelope["message"]
        assert "vaultspec-rag server status" in envelope["message"]
        assert "Eviction failed" not in envelope["message"]
        assert "reason=" not in envelope["message"]


class TestIndexSummaryCLI:
    """Human index summaries are covered through the CLI command surface."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_index_all_renders_service_summary_from_http_response(
        self, tmp_path: Path
    ) -> None:
        import http.server
        import threading

        (tmp_path / ".vaultspec").mkdir()
        requests: list[dict[str, object]] = []

        class _IndexServiceHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                requests.append(body)

                response_by_type = {
                    "vault": {
                        "ok": True,
                        "added": 1,
                        "updated": 2,
                        "removed": 3,
                        "total": 6,
                        "duration_ms": 1234,
                    },
                    "codebase": {
                        "ok": True,
                        "added": "4",
                        "updated": "5",
                        "removed": "6",
                        "total": "15",
                        "duration_ms": "50",
                    },
                }
                response = response_by_type.get(
                    body.get("type"),
                    {"ok": False, "error": "unexpected_type"},
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), _IndexServiceHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = runner.invoke(
                app,
                [
                    "--target",
                    str(tmp_path),
                    "index",
                    "--type",
                    "all",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert [req["type"] for req in requests] == ["vault", "codebase"]
        assert {req["project_root"] for req in requests} == {str(tmp_path)}
        assert {req["initiator_kind"] for req in requests} == {"cli"}
        assert {req["clean"] for req in requests} == {False}

        lines = [line.strip() for line in result.output.splitlines() if line.strip()]
        assert lines == [
            "Indexing summary: ran in running service.",
            "Vault: added 1; updated 2; removed 3; total 6; finished in 1.2 seconds",
            (
                "Source code: added 4; updated 5; removed 6; total 15; "
                "finished in 50 milliseconds"
            ),
        ]

    def test_index_all_handles_sparse_service_summary_without_unknown_text(
        self, tmp_path: Path
    ) -> None:
        import http.server
        import threading

        (tmp_path / ".vaultspec").mkdir()
        requests: list[dict[str, object]] = []

        class SparseIndexServiceHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                requests.append(body)

                response_by_type: dict[str, dict[str, object]] = {
                    "vault": {
                        "ok": True,
                        "added": "not-a-number",
                        "updated": "2",
                        "removed": None,
                        "total": [],
                        "duration_ms": "not-a-duration",
                    },
                    "codebase": {
                        "ok": True,
                        "added": "4",
                        "updated": "5",
                        "removed": "6",
                        "total": "15",
                        "duration_ms": "50",
                    },
                }
                response = response_by_type.get(
                    body.get("type"),
                    {"ok": False, "error": "unexpected_type"},
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), SparseIndexServiceHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = runner.invoke(
                app,
                [
                    "--target",
                    str(tmp_path),
                    "index",
                    "--type",
                    "all",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert [req["type"] for req in requests] == ["vault", "codebase"]

        lines = [line.strip() for line in result.output.splitlines() if line.strip()]
        assert lines == [
            "Indexing summary: ran in running service.",
            "Vault: added 0; updated 2; removed 0; total 0; duration not reported",
            (
                "Source code: added 4; updated 5; removed 6; total 15; "
                "finished in 50 milliseconds"
            ),
        ]
        assert "unknown" not in result.output.lower()
        assert "finished in not reported" not in result.output.lower()

    def test_index_summary_spells_out_reported_durations(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._index import _print_index_summary

        _print_index_summary(
            [
                {
                    "source": "vault",
                    "added": 1,
                    "updated": 0,
                    "removed": 0,
                    "total": 1,
                    "duration_ms": 1000,
                },
                {
                    "source": "codebase",
                    "added": 0,
                    "updated": 1,
                    "removed": 0,
                    "total": 1,
                    "duration_ms": 1500,
                },
                {
                    "source": "vault",
                    "added": 0,
                    "updated": 0,
                    "removed": 1,
                    "total": 0,
                    "duration_ms": 10_000,
                },
            ],
            via="service",
        )

        lines = _plain_lines(capsys.readouterr().out)
        assert lines[1].endswith("finished in 1 second")
        assert lines[2].endswith("finished in 1.5 seconds")
        assert lines[3].endswith("finished in 10 seconds")
        assert not any("ms" in line for line in lines)

    def test_index_summary_humanizes_missing_source_label(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._index import _print_index_summary

        _print_index_summary(
            [{"added": 1, "updated": 2, "removed": 0, "total": 3}],
            via="service",
        )

        lines = _plain_lines(capsys.readouterr().out)
        assert lines[0] == "Indexing summary: ran in running service."
        joined = " ".join(lines[1:])
        assert "Index source not reported:" in joined
        assert "added 1; updated 2; removed 0; total 3" in joined
        assert "duration not reported" in joined
        assert "not_reported" not in joined


class TestCpuOnlyMessageRendering:
    """Regression guard for literal TOML keys in the CPU_ONLY copy.

    The CLI prints this message with Rich markup disabled so TOML keys,
    dependency groups, and command lines stay literal in user output.
    """

    @staticmethod
    def _render() -> str:
        import io

        from rich.console import Console

        from ..cli import _cpu_only_message

        buf = io.StringIO()
        Console(file=buf, force_terminal=False, color_system=None, width=120).print(
            _cpu_only_message(), markup=False, highlight=False
        )
        return buf.getvalue()

    def test_renders_double_brackets_for_aot(self) -> None:
        out = self._render()
        assert "[[tool.uv.index]]" in out, out

    def test_renders_single_brackets_for_section(self) -> None:
        out = self._render()
        assert "[tool.uv.sources]" in out, out

    def test_renders_project_and_groups_keys(self) -> None:
        out = self._render()
        assert "[project].dependencies" in out, out
        assert "[dependency-groups].dev" in out, out

    def test_no_stray_backslashes_in_rendered_output(self) -> None:
        """Rich passes ``\\]`` through verbatim - only ``[`` is escapable.
        A stray backslash in the rendered text means a future edit
        overcorrected and put ``\\]`` somewhere it should not be.
        """
        out = self._render()
        assert "\\" not in out, out


class TestNoGpuMessageRendering:
    """TEST-04 regression: NO_GPU message must render its three
    bullets verbatim through Rich. Symmetric guard with
    TestCpuOnlyMessageRendering.
    """

    @staticmethod
    def _render() -> str:
        import io

        from rich.console import Console

        from ..cli import _no_gpu_message

        buf = io.StringIO()
        Console(file=buf, force_terminal=False, color_system=None, width=120).print(
            _no_gpu_message()
        )
        return buf.getvalue()

    def test_renders_nvidia_smi_check(self) -> None:
        out = self._render()
        assert "nvidia-smi" in out

    def test_renders_torch_version_cuda_check(self) -> None:
        out = self._render()
        assert "torch.version.cuda" in out

    def test_renders_wsl_docker_caveat(self) -> None:
        out = self._render()
        assert "WSL" in out or "Docker" in out
        assert "--gpus all" in out

    def test_no_stray_backslashes(self) -> None:
        out = self._render()
        assert "\\" not in out, out


class TestNoTorchMessageRendering:
    """TEST-11 regression: NO_TORCH message must render its single
    actionable ``uv add`` command line cleanly.
    """

    @staticmethod
    def _render() -> str:
        import io

        from rich.console import Console

        from ..cli import _no_torch_message

        buf = io.StringIO()
        Console(file=buf, force_terminal=False, color_system=None, width=120).print(
            _no_torch_message()
        )
        return buf.getvalue()

    def test_renders_uv_add_command(self) -> None:
        out = self._render()
        assert "uv add vaultspec-rag" in out
        assert "vaultspec-rag install" in out

    def test_no_stray_backslashes(self) -> None:
        out = self._render()
        assert "\\" not in out, out


class TestRenderInstallReport:
    """CLI-01 regression: the install/uninstall warning loop must NOT
    parse warning bodies as markup. The transitive-dep warning
    embeds literal ``[tool.uv.sources]``, ``[project].dependencies``,
    and ``[dependency-groups].dev``; uv stderr tails embed raw
    ``[…]`` tokens; raw exception messages embed ``[tool]`` strings
    from the historic OutOfOrderTableProxy bug. The report renderer
    must preserve those bytes verbatim in captured CLI output.
    """

    @staticmethod
    def _render(report: object) -> str:
        import io

        from rich.console import Console

        from .. import cli as cli_mod

        buf = io.StringIO()
        original = cli_mod.console
        cli_mod.console = Console(
            file=buf, force_terminal=False, color_system=None, width=200
        )
        try:
            cli_mod._render_install_report(report)
        finally:
            cli_mod.console = original
        return buf.getvalue()

    def test_warning_with_literal_toml_keys_preserved(self) -> None:
        from ..commands import InstallReport

        warning = (
            "torch-config patched, but `torch` is not a direct dependency. "
            "uv ignores [tool.uv.sources] for purely transitive packages, "
            "so the cu130 pin will not take effect. "
            "Add `torch>=2.4` to [project].dependencies or "
            "[dependency-groups].dev."
        )
        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.APPLIED,
            warnings=[warning],
        )
        out = self._render(report)
        # All three TOML key tokens must survive the render.
        assert "[tool.uv.sources]" in out, out
        assert "[project].dependencies" in out, out
        assert "[dependency-groups].dev" in out, out

    def test_warning_with_uv_stderr_tail_preserved(self) -> None:
        """Realistic shape: uv stderr embedded in a warning body via
        the new INSTALL-03 tail. ``[project]`` and ``[tool]`` tokens
        in uv's own error rendering must survive.
        """
        from ..commands import InstallReport

        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.APPLIED,
            warnings=[
                "uv sync --reinstall-package torch exited with code 1; "
                "last stderr lines:\n"
                "error: Failed to resolve [project] root\n"
                "error: see [tool.uv] config"
            ],
        )
        out = self._render(report)
        assert "[project]" in out
        assert "[tool.uv]" in out

    def test_conflict_with_aot_token_preserved(self) -> None:
        """Conflict surface (already had its own markup-off treatment
        before this PR - guard it now with a rendering test so a
        future maintainer cannot accidentally collapse the two-line
        treatment back into a single ``f"... {conflict}"`` print).
        """
        from ..commands import InstallReport

        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.CONFLICT,
            torch_config_conflicts=[
                '[[tool.uv.index]] entry name="pytorch-cu130" url-mismatch'
            ],
        )
        out = self._render(report)
        assert "[[tool.uv.index]]" in out
        assert 'name="pytorch-cu130"' in out

    def test_skipped_eof_action_renders_yellow(self) -> None:
        """TEST-12 regression: the new ``skipped-eof`` action label
        must reach the colour map. A regression that dropped it would
        render the label in default-white instead of yellow.
        """
        from ..commands import InstallReport

        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.SKIPPED_EOF,
        )
        out = self._render(report)
        assert "PyTorch configuration: needs confirmation" in out

    def test_dry_run_uses_operator_language(self) -> None:
        from ..commands import InstallReport

        report = InstallReport(
            action="dry_run",
            target=Path("."),
            torch_config_action=TorchConfigAction.DRY_RUN,
            warnings=[
                "dry-run: core sync_provider not invoked (would propagate "
                "seeded files to .mcp.json and provider dirs)"
            ],
        )
        out = self._render(report)
        assert "PyTorch configuration: preview only" in out
        assert "Target: ." in out
        assert "Note: dry-run preview: would update tool integration files" in out
        assert "target:" not in out
        assert "note:" not in out
        assert "warning: dry-run preview" not in out
        for forbidden in (
            "torch-config:",
            "sync_provider",
            "provider dirs",
            "core sync",
        ):
            assert forbidden not in out

    def test_preserves_provider_outcomes_in_json_and_human_output(self) -> None:
        from vaultspec_core.core.types import (  # pyright: ignore[reportMissingTypeStubs]
            SyncResult,
        )

        from ..commands import InstallReport

        claude = SyncResult(
            added=1,
            unchanged=1,
            items=[("vaultspec-rag", "[ADD]")],
        )
        codex = SyncResult(
            updated=1,
            errored=1,
            errors=["native target malformed"],
            warnings=["managed entry drift repaired"],
            items=[("vaultspec-rag", "[UPDATE]")],
        )
        provider_result = SyncResult(per_tool={"claude": claude, "codex": codex})
        report = InstallReport(
            action="install",
            target=Path("."),
            sync_results=[provider_result],
            mcp_sync_results=[provider_result],
        )

        providers = report.to_dict()["sync_providers"]
        assert providers["claude"] == {
            "added": 1,
            "updated": 0,
            "unchanged": 1,
            "skipped": 0,
            "pruned": 0,
            "errored": 0,
            "errors": [],
            "warnings": [],
            "items": [["vaultspec-rag", "[ADD]"]],
        }
        assert providers["codex"]["updated"] == 1
        assert providers["codex"]["errored"] == 1
        assert providers["codex"]["errors"] == ["native target malformed"]
        assert providers["codex"]["warnings"] == ["managed entry drift repaired"]

        out = self._render(report)
        assert "Claude MCP: added 1, unchanged 1" in out
        assert "Codex MCP: updated 1, errored 1" in out
        assert "warning: managed entry drift repaired" in out
        assert "error: native target malformed" in out

    def test_preserves_unattributed_mcp_errors_in_json_and_human_output(self) -> None:
        from vaultspec_core.core.types import (  # pyright: ignore[reportMissingTypeStubs]
            SyncResult,
        )

        from ..commands import InstallReport

        report = InstallReport(
            action="install",
            target=Path("."),
            sync_results=[SyncResult(errored=1, errors=["ownership is malformed"])],
            mcp_sync_results=[SyncResult(errored=1, errors=["ownership is malformed"])],
        )

        data = report.to_dict()
        assert data["mcp_failed"] is True
        assert data["mcp_errors"] == ["ownership is malformed"]
        assert data["sync_providers"] == {}

        out = self._render(report)
        assert "MCP lifecycle error: ownership is malformed" in out


class TestRenderUninstallReport:
    """Symmetric guard rail for the uninstall renderer."""

    @staticmethod
    def _render(report: object) -> str:
        import io

        from rich.console import Console

        from .. import cli as cli_mod

        buf = io.StringIO()
        original = cli_mod.console
        cli_mod.console = Console(
            file=buf, force_terminal=False, color_system=None, width=200
        )
        try:
            cli_mod._render_uninstall_report(report)
        finally:
            cli_mod.console = original
        return buf.getvalue()

    def test_warning_with_literal_toml_keys_preserved(self) -> None:
        from ..commands import UninstallReport

        report = UninstallReport(
            action="uninstall",
            target=Path("."),
            warnings=[
                "no .vaultspec/ at /tmp/foo; "
                "torch-config block in [tool.uv.sources] left intact"
            ],
        )
        out = self._render(report)
        assert "[tool.uv.sources]" in out

    def test_error_action_renders(self) -> None:
        """INSTALL-08 follow-up: uninstall now has ``error`` in its
        colour map. Just verify the label reaches the renderer.
        """
        from ..commands import UninstallReport

        report = UninstallReport(
            action="uninstall",
            target=Path("."),
            torch_config_action=TorchConfigAction.ERROR,
        )
        out = self._render(report)
        assert "PyTorch configuration: error" in out

    def test_mcp_extra_result_is_preserved_in_json_and_human_output(self) -> None:
        from ..commands import UninstallReport

        report = UninstallReport(
            action="uninstall",
            target=Path("."),
            mcp_extra_action="removed",
            mcp_extra_location="[project].dependencies",
        )

        data = report.to_dict()
        assert data["mcp_extra_action"] == "removed"
        assert data["mcp_extra_location"] == "[project].dependencies"
        out = self._render(report)
        assert "MCP optional dependency: removed ([project].dependencies)" in out

    def test_dry_run_uses_operator_language(self) -> None:
        from ..commands import UninstallReport

        report = UninstallReport(
            action="dry_run",
            target=Path("."),
            removed=[".vaultspec/rules/vaultspec-rag.builtin.md"],
            torch_config_action=TorchConfigAction.DRY_RUN,
            torch_direct_dep_action="dry_run",
            warnings=[
                "dry-run: core sync_provider not invoked (would propagate "
                "removal to .mcp.json and provider dirs)"
            ],
        )
        out = self._render(report)
        assert "would remove 1 bundled source file" in out
        assert "removed 1 bundled source file" not in out
        assert "PyTorch configuration: preview only" in out
        assert "PyTorch dependency: preview only" in out
        assert "Target: ." in out
        assert "Note: dry-run preview: would remove tool integration files" in out
        assert "target:" not in out
        assert "note:" not in out
        assert "warning: dry-run preview" not in out
        for forbidden in (
            "torch-config:",
            "torch direct dependency:",
            "sync_provider",
            "provider dirs",
            "core sync",
        ):
            assert forbidden not in out

    def test_preserves_provider_prunes_in_json_and_human_output(self) -> None:
        from vaultspec_core.core.types import (  # pyright: ignore[reportMissingTypeStubs]
            SyncResult,
        )

        from ..commands import UninstallReport

        provider_result = SyncResult(
            pruned=2,
            per_tool={
                "claude": SyncResult(pruned=1, items=[("vaultspec-rag", "[DELETE]")]),
                "codex": SyncResult(pruned=1, items=[("vaultspec-rag", "[DELETE]")]),
            },
        )
        report = UninstallReport(
            action="uninstall",
            target=Path("."),
            sync_results=[provider_result],
            mcp_sync_results=[provider_result],
        )

        providers = report.to_dict()["sync_providers"]
        assert providers["claude"]["pruned"] == 1
        assert providers["codex"]["pruned"] == 1
        assert providers["codex"]["items"] == [["vaultspec-rag", "[DELETE]"]]

        out = self._render(report)
        assert "Claude MCP: pruned 1" in out
        assert "Codex MCP: pruned 1" in out


class TestInstallExitCodes:
    """CLI3-01 regression: install exits non-zero on the torch-config
    terminal states the user did not opt into. Issue #83 finding 3
    "Bonus" item.
    """

    @staticmethod
    def _make_pyproject(tmp_path: Path, body: str) -> Path:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(body, encoding="utf-8", newline="")
        return ws

    def test_install_exit_zero_on_applied(self, tmp_path: Path) -> None:
        ws = self._make_pyproject(
            tmp_path,
            '[project]\nname = "demo"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag", "torch>=2.4"]\n',
        )
        result = runner.invoke(app, ["install", "--target", str(ws), "--yes"])
        assert result.exit_code == 0, result.output

    def test_install_exit_nonzero_on_skipped_non_tty(self, tmp_path: Path) -> None:
        """Non-TTY without ``--yes`` / ``--force``: torch-config skipped,
        exit code 2 so CI fails loudly.
        """
        ws = self._make_pyproject(
            tmp_path,
            '[project]\nname = "demo"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag"]\n',
        )
        # CliRunner's stdin is not a TTY, so confirm_fn=None - emulates
        # the non-interactive harness path.
        result = runner.invoke(app, ["install", "--target", str(ws)])
        assert result.exit_code == 2, result.output

    def test_install_exit_nonzero_on_error(self, tmp_path: Path) -> None:
        """Corrupt pyproject → torch_config_action=TorchConfigAction.ERROR → exit 2."""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(
            "[project\nname = ", encoding="utf-8"
        )  # malformed
        result = runner.invoke(app, ["install", "--target", str(ws), "--yes"])
        assert result.exit_code == 2, result.output

    def test_install_exit_nonzero_on_mcp_extra_parse_error(
        self, tmp_path: Path
    ) -> None:
        ws = self._make_pyproject(tmp_path, "[project\nname =")
        result = runner.invoke(
            app,
            ["install", "--target", str(ws), "--no-torch-config", "--mcp"],
        )
        assert result.exit_code == 2, result.output

    def test_install_exit_zero_on_conflict(self, tmp_path: Path) -> None:
        """CUSTOMISED block - user-state, not a runtime failure.
        Conflict exits 0; the warning is the signal, not the exit code.
        """
        ws = self._make_pyproject(
            tmp_path,
            '[project]\nname = "demo"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag"]\n'
            "\n[[tool.uv.index]]\n"
            'name = "pytorch-cu130"\n'
            'url = "https://download.pytorch.org/whl/cu121"\n'  # wrong url
            "explicit = true\n",
        )
        result = runner.invoke(app, ["install", "--target", str(ws), "--yes"])
        assert result.exit_code == 0, result.output

    def test_install_exit_zero_when_no_torch_config(self, tmp_path: Path) -> None:
        """``--no-torch-config`` opts out - exits 0 even on a non-TTY."""
        ws = self._make_pyproject(
            tmp_path,
            '[project]\nname = "demo"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag"]\n',
        )
        result = runner.invoke(
            app, ["install", "--target", str(ws), "--no-torch-config"]
        )
        assert result.exit_code == 0, result.output


class TestInstallTargetValidation:
    """CLI3-02 regression: per-command ``--target`` must reject
    regular files (matching the global ``--target`` validator).
    """

    def test_per_command_target_rejects_file(self, tmp_path: Path) -> None:
        """Pointing ``install --target`` at a regular file used to slip
        past validation; now correctly rejected by typer's
        ``file_okay=False``.
        """
        f = tmp_path / "not-a-dir.txt"
        f.write_text("hi", encoding="utf-8")
        result = runner.invoke(app, ["install", "--target", str(f)])
        assert result.exit_code != 0, result.output
        assert "is a file" in result.output or "directory" in result.output.lower()

    def test_per_command_target_accepts_dir(self, tmp_path: Path) -> None:
        """Negative pair: a real directory still validates."""
        d = tmp_path / "real-dir"
        d.mkdir()
        result = runner.invoke(
            app, ["install", "--target", str(d), "--no-torch-config"]
        )
        assert result.exit_code == 0, result.output


class TestJsonOutputMode:
    """Every command supports --json envelope output."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    @staticmethod
    def _parse_envelope(output: str) -> dict[str, typing.Any]:
        """Parse the single JSON document a --json invocation should emit."""
        stripped = output.strip()
        # Tolerate platform-specific trailing whitespace; the contract is
        # one JSON document per invocation.
        return typing.cast("dict[str, typing.Any]", json.loads(stripped))

    def test_search_json_filter_mismatch_envelope(self):
        """Filter on wrong --type yields ok=false envelope with exit 2."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "vault",
                "--function-name",
                "foo",
                "--json",
            ],
        )
        assert result.exit_code == 2
        env = self._parse_envelope(result.output)
        assert env["ok"] is False
        assert env["command"] == "search"
        assert env["error"] == "invalid_filter_for_search_type"
        assert "--function-name" in env["message"]

    def test_search_json_glob_with_vault_envelope(self):
        """Glob + --type vault yields the same envelope shape."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "vault",
                "--include-path",
                "src/**",
                "--json",
            ],
        )
        assert result.exit_code == 2
        env = self._parse_envelope(result.output)
        assert env["ok"] is False
        assert env["error"] == "invalid_filter_for_search_type"

    def test_search_json_port_unreachable_envelope(self, tmp_path: Path) -> None:
        """--port unreachable yields port_unreachable envelope, exit 1."""
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "anything",
                "--port",
                "1",
                "--json",
            ],
        )
        assert result.exit_code == 1
        env = self._parse_envelope(result.output)
        assert env["ok"] is False
        assert env["error"] == "port_unreachable"
        assert env["port"] == 1
        assert "remediation" in env
        assert "one local user only" in env["message"]
        assert "single-agent" not in env["message"]
        assert "Qdrant lock" not in env["message"]
        assert "in-process" not in env["message"]

    def test_service_status_json_stopped_envelope(self, tmp_path: Path):
        """No service.json: exit 3 + ok=false envelope with error=stopped."""
        # Isolate STATUS_DIR to an empty dir so the assertion does not depend
        # on the developer machine's ambient ~/.vaultspec-rag/ service state;
        # a running service would otherwise return exit 0 here.
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        reset_base_config()
        reset_rag_config()
        try:
            result = runner.invoke(
                app,
                ["server", "status", "--json"],
            )
            assert result.exit_code == 3
            env = self._parse_envelope(result.output)
            assert env["ok"] is False
            assert env["command"] == "service.status"
            assert env["error"] == "stopped"
            assert env["data"]["service_json_present"] is False
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)
            reset_base_config()
            reset_rag_config()

    def test_service_status_json_crashed_envelope(self, tmp_path: Path):
        """File present + dead PID: exit 4 + ok=false + state=crashed_*."""
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=99999999, port=8766)
            result = runner.invoke(app, ["server", "status", "--json"])
            assert result.exit_code == 4
            env = self._parse_envelope(result.output)
            assert env["ok"] is False
            assert env["command"] == "service.status"
            assert env["data"]["state"].startswith("crashed_")
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_clean_json_requires_yes(self, tmp_path: Path):
        """--json without --yes yields json_requires_yes envelope, exit 2."""
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "clean", "vault", "--json"],
        )
        assert result.exit_code == 2
        env = self._parse_envelope(result.output)
        assert env["ok"] is False
        assert env["error"] == "json_requires_yes"
        message = str(env["message"])
        assert "--yes" in message
        assert "one JSON result" in message
        assert "interactive confirmation prompt" in message
        assert "stdin" not in message
        assert "corrupt" not in message

    def test_envelope_is_pure_stdout_no_rich_bytes(self, tmp_path: Path) -> None:
        """Output is a single parseable JSON document, no Rich box chars."""
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "anything",
                "--type",
                "vault",
                "--function-name",
                "foo",  # forces fast usage-error branch
                "--json",
            ],
        )
        # Trim a possible single trailing newline.
        text = result.output.rstrip("\n")
        # The Rich box-drawing block ─ │ ┌ ┐ └ ┘ must not appear in --json
        # mode; an envelope is plain ASCII JSON.
        for forbidden in ("─", "│", "┌", "┐", "└", "┘"):
            assert forbidden not in text, (
                f"Rich box-drawing leaked into --json stdout: {forbidden!r}"
            )
        # Exactly one JSON document.
        env = json.loads(text)
        assert env["ok"] is False


class TestTqdmSuppression:
    """gh #128: prove tqdm progress-bar bytes never leak to stdout."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_help_subprocess_stdout_has_no_bare_carriage_return(self):
        """Importing the package + emitting --help leaks no bare ``\\r``.

        tqdm rewrites lines via bare ``\\r`` (NOT ``\\r\\n``). A
        clean ``--help`` run proves no import-time side-effect
        (e.g. a stray ``tqdm.write`` in a third-party constructor)
        reaches the user's terminal. Windows ``\\r\\n`` line
        endings are normalised before the check so the assertion
        is platform-independent.
        """
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "vaultspec_rag", "--help"],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"--help exited {result.returncode}; stderr={result.stderr!r}"
        )
        normalised = result.stdout.replace(b"\r\n", b"\n")
        assert b"\r" not in normalised, (
            "bare carriage-return bytes leaked into --help stdout - "
            "a tqdm-like progress writer is escaping suppression"
        )


class TestJsonStdoutPurityAcrossCommands:
    """gh #128: ``--json`` envelope is parseable + Rich-free everywhere."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    # (id, argv-after-binary, expected_exit_code_predicate)
    _SCENARIOS: typing.ClassVar = [
        # service status with no daemon - exit 3, ok=false envelope
        ("service-status-stopped", ["server", "status", "--json"]),
        # search filter mismatch - exit 2, ok=false envelope
        (
            "search-filter-mismatch",
            [
                "search",
                "x",
                "--type",
                "vault",
                # Literal pattern with no glob meta-chars to avoid
                # Windows argv-globbing surprises in subprocess.
                "--include-path",
                "nonexistent/file.py",
                "--json",
            ],
        ),
        # search port unreachable - exit 1, ok=false envelope
        (
            "search-port-unreachable",
            ["search", "x", "--port", "1", "--json"],
        ),
    ]

    _FORBIDDEN_CHARS: typing.ClassVar = (
        "─",
        "│",
        "┌",
        "┐",
        "└",
        "┘",
        "╭",
        "╮",
        "╰",
        "╯",
    )

    @pytest.mark.parametrize(
        ("scenario_id", "argv"),
        _SCENARIOS,
        ids=[s[0] for s in _SCENARIOS],
    )
    def test_envelope_is_pure_json(
        self, scenario_id: str, argv: list[str], tmp_path: Path
    ) -> None:
        """Every --json invocation: parseable JSON, no Rich glyphs, no ANSI."""
        import subprocess
        import sys

        (tmp_path / ".vaultspec").mkdir()
        (tmp_path / ".vault").mkdir()
        full_argv: list[str] = [
            sys.executable,
            "-m",
            "vaultspec_rag",
            "--target",
            str(tmp_path),
            *argv,
        ]
        result = subprocess.run(
            full_argv,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "NO_COLOR": "1",
                "FORCE_COLOR": "0",
            },
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        text = stdout.strip()
        assert text, (
            f"{scenario_id}: empty stdout - exit={result.returncode} "
            f"stderr={result.stderr!r}"
        )
        # ANSI escape sequences (`\x1b[`) must not appear.
        assert "\x1b[" not in text, (
            f"{scenario_id}: ANSI escape leaked into --json stdout"
        )
        for forbidden in self._FORBIDDEN_CHARS:
            assert forbidden not in text, (
                f"{scenario_id}: Rich box char {forbidden!r} leaked into --json stdout"
            )
        # The contract is one JSON document per invocation.
        env = json.loads(text)
        assert "ok" in env, f"{scenario_id}: envelope missing 'ok' key"


class TestAutoDelegation:
    """Verify auto-delegation against real isolated discovery state."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    @staticmethod
    def _run_resolution_probe(tmp_path: Path, mode: str) -> dict[str, object]:
        """Run real discovery and search routing in a fresh interpreter."""
        import subprocess
        import sys

        code = r"""
import json
import os
import socket
import sys
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

from vaultspec_rag.config import reset_config

reset_config()


from vaultspec_rag._machine_lock import (
    acquire_machine_lock,
    machine_discovery_path,
    release_machine_lock,
)

machine_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
fallback_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
machine_lock_acquired = False

try:
    machine_socket.bind(("127.0.0.1", 0))
    fallback_socket.bind(("127.0.0.1", 0))
    machine_port = int(machine_socket.getsockname()[1])
    fallback_port = int(fallback_socket.getsockname()[1])
    assert machine_port != fallback_port

    (status_dir / "service.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "port": fallback_port,
                "service_token": "fallback-token",
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
                }
            ),
            encoding="utf-8",
        )

    expected = machine_port if mode == "machine" else fallback_port

    from vaultspec_rag.cli._index import _default_service_port as index_port
    from vaultspec_rag.cli._search import _default_service_port as search_port

    assert search_port() == expected
    assert index_port() == expected

    from typer.testing import CliRunner
    from vaultspec_rag.cli import app

    result = CliRunner().invoke(
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
    envelope = json.loads(result.output)
    assert result.exit_code == 1, result.output
    assert envelope["error"] == "port_unreachable", envelope
    assert envelope["port"] == expected, envelope

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
    print(
        json.dumps(
            {
                "mode": mode,
                "expected": expected,
                "machine_port": machine_port,
                "fallback_port": fallback_port,
                "error": envelope["error"],
                "heavy": heavy,
            }
        )
    )
finally:
    if machine_lock_acquired:
        release_machine_lock()
    fallback_socket.close()
    machine_socket.close()
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path), mode],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return typing.cast("dict[str, object]", json.loads(result.stdout))

    def test_auto_delegation_prefers_machine_global_resolution(
        self, tmp_path: Path
    ) -> None:
        """A valid machine-global service outranks a conflicting status hint."""
        evidence = self._run_resolution_probe(tmp_path, "machine")
        assert evidence["expected"] == evidence["machine_port"]
        assert evidence["expected"] != evidence["fallback_port"]
        assert evidence["error"] == "port_unreachable"
        assert evidence["heavy"] == []

    def test_auto_delegation_uses_status_fallback_without_machine_service(
        self, tmp_path: Path
    ) -> None:
        """The real status file is used only when machine resolution is absent."""
        evidence = self._run_resolution_probe(tmp_path, "fallback")
        assert evidence["expected"] == evidence["fallback_port"]
        assert evidence["expected"] != evidence["machine_port"]
        assert evidence["error"] == "port_unreachable"
        assert evidence["heavy"] == []


class TestWarmingStatusState:
    """The daemon-stamped ``phase`` field turns the warmup window into a
    distinct ``warming`` state (exit 5) instead of "stopped"/"crashed".

    Pure-function coverage: the state computers and the phase reader are
    exercised directly (a live-and-ours pid cannot be faked without mocks).
    """

    def test_service_phase_reads_the_field(self):
        from vaultspec_rag.cli._service_status import _service_phase

        assert _service_phase({"phase": "warming"}) == "warming"
        assert _service_phase({"phase": "running"}) == "running"

    def test_service_phase_absent_or_invalid_is_none(self):
        from vaultspec_rag.cli._service_status import _service_phase

        assert _service_phase(None) is None
        assert _service_phase({}) is None
        assert _service_phase({"phase": ""}) is None
        assert _service_phase({"phase": 7}) is None

    def test_compute_state_warming_beats_port_and_heartbeat_signals(self):
        from vaultspec_rag.cli._service_lifecycle import _compute_state

        state, label, exit_code = _compute_state(
            True, True, False, True, phase="warming"
        )
        assert state == "warming"
        assert "warming" in label
        assert exit_code == 5

    def test_compute_state_absent_phase_keeps_crashed_semantics(self):
        from vaultspec_rag.cli._service_lifecycle import _compute_state

        state, _label, exit_code = _compute_state(True, True, False, True)
        assert state == "crashed_port_silent"
        assert exit_code == 4

    def test_compute_state_dead_pid_wins_over_warming(self):
        from vaultspec_rag.cli._service_lifecycle import _compute_state

        state, _label, exit_code = _compute_state(
            False, False, False, True, phase="warming"
        )
        assert state == "crashed_pid_dead"
        assert exit_code == 4

    def test_explicit_port_state_warming_needs_a_live_owned_pid(self):
        from vaultspec_rag.cli._service_lifecycle import _explicit_port_state

        warming = _explicit_port_state(
            False, None, phase="warming", pid_alive=True, pid_is_ours=True
        )
        assert warming[0] == "warming"
        assert warming[2] == 5
        dead = _explicit_port_state(
            False, None, phase="warming", pid_alive=False, pid_is_ours=False
        )
        assert dead[0] == "stopped"
        assert dead[2] == 3
        reused = _explicit_port_state(
            False, None, phase="warming", pid_alive=True, pid_is_ours=False
        )
        assert reused[0] == "stopped"
        assert reused[2] == 3

    def test_explicit_port_state_absent_phase_is_unchanged(self):
        from vaultspec_rag.cli._service_lifecycle import _explicit_port_state

        assert _explicit_port_state(False, None)[0] == "stopped"
        assert _explicit_port_state(True, None)[0] == "unreachable"
        assert _explicit_port_state(True, {"status": "ready"})[0] == "running"

    def test_next_action_for_warming_says_retry(self):
        from vaultspec_rag.cli._service_lifecycle import _status_next_action

        action = _status_next_action("warming", None, {})
        assert "server status" in action
        assert "retry" in action

    def test_daemon_phase_stamp_merges_and_skips_absent(self, tmp_path: Path):
        import json

        from vaultspec_rag.server._lifespan import _stamp_service_phase

        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            # Absent file: the stamp is skipped, nothing is created.
            _stamp_service_phase("warming")
            sf = tmp_path / "service.json"
            assert not sf.exists()

            _write_service_status(pid=4242, port=8766)
            _stamp_service_phase("warming")
            data = json.loads(sf.read_text(encoding="utf-8"))
            assert data["phase"] == "warming"
            assert data["pid"] == 4242

            _stamp_service_phase("running")
            data = json.loads(sf.read_text(encoding="utf-8"))
            assert data["phase"] == "running"
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)
