"""CLI tests for automatic index update subcommands (plan P04).

Verifies the CLI plumbing for the automatic-index-update parity surface: the
service-unreachable path (exit code 3 + JSON envelope) for every
subcommand, and CLI<->MCP structural parity. No mocks: commands run
through the real Typer app against a dead port so ``_try_http_admin``
genuinely fails to connect.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import os
import threading
import time
from typing import TYPE_CHECKING, ClassVar

import pytest
from typer.testing import CliRunner

from ..cli import app

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

runner = CliRunner()

# A port with nothing listening: _try_http_admin gets connection-refused
# and returns None -> the command reports service-not-running (exit 3).
_DEAD_PORT = "59231"


class _UpdatesHTTPHandler(http.server.BaseHTTPRequestHandler):
    payloads: ClassVar[list[dict[str, object]]] = []
    requests: ClassVar[list[dict[str, object]]] = []

    def do_GET(self) -> None:
        self.requests.append({"method": "GET", "path": self.path})
        self._send_payload()

    def do_POST(self) -> None:
        body_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(body_length).decode("utf-8")
        body: dict[str, object] = json.loads(raw_body) if raw_body else {}
        self.requests.append({"method": "POST", "path": self.path, "body": body})
        self._send_payload()

    def _send_payload(self) -> None:
        payload = self.payloads[0]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        _ = format, args


class _SlowUpdatesHTTPHandler(http.server.BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, object]]] = []
    delay_seconds: ClassVar[float] = 0.5

    def do_POST(self) -> None:
        body_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(body_length).decode("utf-8")
        body: dict[str, object] = json.loads(raw_body) if raw_body else {}
        self.requests.append({"method": "POST", "path": self.path, "body": body})
        time.sleep(self.delay_seconds)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        with contextlib.suppress(OSError):
            self.wfile.write(json.dumps({"started": True}).encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        _ = format, args


@contextlib.contextmanager
def _updates_http_server(
    payload: dict[str, object],
) -> Generator[tuple[http.server.HTTPServer, int]]:
    _UpdatesHTTPHandler.payloads = [payload]
    _UpdatesHTTPHandler.requests = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _UpdatesHTTPHandler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextlib.contextmanager
def _slow_updates_http_server(
    delay_seconds: float = 0.5,
) -> Generator[tuple[http.server.HTTPServer, int]]:
    _SlowUpdatesHTTPHandler.requests = []
    _SlowUpdatesHTTPHandler.delay_seconds = delay_seconds
    server = http.server.HTTPServer(("127.0.0.1", 0), _SlowUpdatesHTTPHandler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


_UPDATES_COMMANDS = [
    ["server", "updates", "status"],
    ["server", "updates", "start", "/tmp/x"],
    ["server", "updates", "stop", "/tmp/x"],
    ["server", "updates", "timing", "/tmp/x"],
]

_UPDATES_COMMAND_IDS = {
    "status": "service.updates.status",
    "start": "service.updates.start",
    "stop": "service.updates.stop",
    "timing": "service.updates.timing",
}


def _help_command_names(output: str) -> list[str]:
    names: list[str] = []
    in_commands = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line == "Commands:":
            in_commands = True
            continue
        if not in_commands or not line:
            continue
        names.append(line.split()[0])
    return names


def _label_values(output: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if ": " not in line:
            continue
        label, value = line.split(": ", 1)
        pairs[label] = value
    return pairs


@pytest.mark.parametrize("argv", _UPDATES_COMMANDS)
def test_updates_command_not_running_json(argv: list[str]) -> None:
    result = runner.invoke(app, [*argv, "--port", _DEAD_PORT, "--json"])
    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    command_name = argv[2]
    assert payload["ok"] is False
    assert payload["command"] == _UPDATES_COMMAND_IDS[command_name]
    assert payload["error"] == "service_not_running"
    assert "watcher" not in payload["command"]


@pytest.mark.parametrize("argv", _UPDATES_COMMANDS)
def test_updates_command_not_running_prose(argv: list[str]) -> None:
    result = runner.invoke(app, [*argv, "--port", _DEAD_PORT])
    assert result.exit_code == 3
    assert f"Address: http://127.0.0.1:{_DEAD_PORT}" in result.stdout
    assert "not running" in result.stdout.lower()


def test_updates_subcommands_registered() -> None:
    result = runner.invoke(app, ["server", "updates", "--help"])
    assert result.exit_code == 0
    assert _help_command_names(result.stdout) == [
        "status",
        "start",
        "stop",
        "timing",
    ]
    assert "automatic index update" in result.stdout.lower()
    assert "active roots" not in result.stdout.lower()


@pytest.mark.parametrize(
    "argv",
    [
        ["server", "updates", "status", "--help"],
        ["server", "updates", "start", "--help"],
        ["server", "updates", "stop", "--help"],
        ["server", "updates", "timing", "--help"],
    ],
)
def test_updates_help_uses_script_json_language(argv: list[str]) -> None:
    result = runner.invoke(app, argv)
    assert result.exit_code == 0
    assert "Emit JSON for scripts" in result.stdout
    assert "JSON envelope" not in result.stdout


def test_updates_status_help_uses_project_language() -> None:
    result = runner.invoke(app, ["server", "updates", "status", "--help"])
    assert result.exit_code == 0
    assert "settings and projects" in result.stdout
    assert "active roots" not in result.stdout.lower()


@pytest.mark.parametrize(
    "argv",
    [
        ["server", "updates", "start", "--help"],
        ["server", "updates", "stop", "--help"],
        ["server", "updates", "timing", "--help"],
    ],
)
def test_updates_project_argument_uses_project_language(argv: list[str]) -> None:
    result = runner.invoke(app, argv)
    assert result.exit_code == 0
    # Typer renders a required positional as ``{name}`` in the usage line,
    # so the argument reads as the project it names, never as a root.
    assert "{project}" in result.stdout
    assert " ROOT" not in result.stdout
    assert "{root}" not in result.stdout
    assert "Project root" not in result.stdout


def test_updates_status_empty_output_uses_project_language() -> None:
    payload: dict[str, object] = {
        "watch_enabled": True,
        "debounce_ms": 2000,
        "cooldown_s": 30.0,
        "watching": [],
    }
    with _updates_http_server(payload) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "updates", "status", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    labels = _label_values(result.output)
    assert labels["File changes"] == "wait 2 seconds before updating."
    assert (
        labels["Repeat updates"] == "wait 30 seconds before updating a project again."
    )
    assert "No projects currently have automatic index updates." in result.output
    assert "No roots" not in result.output
    assert "debounce=" not in result.output
    assert "cooldown=" not in result.output


def test_updates_status_lists_projects_as_blocks() -> None:
    payload: dict[str, object] = {
        "watch_enabled": True,
        "debounce_ms": 2000,
        "cooldown_s": 30.0,
        "watching": [
            r"Y:\code\vaultspec-rag-worktrees\feature-server-supervision",
            r"Y:\code\sample-project\main",
        ],
    }
    with _updates_http_server(payload) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "updates", "status", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    assert "Projects updating automatically: 2" in result.output
    assert "- Project: feature-server-supervision" in result.output
    assert r"  Path: Y:\code\vaultspec-rag-worktrees\feature-server-supervision" in (
        result.output
    )
    assert "- Project: main" in result.output
    assert r"  Path: Y:\code\sample-project\main" in (result.output)
    assert (
        r"- Y:\code\vaultspec-rag-worktrees\feature-server-supervision"
        not in result.output
    )


def test_updates_start_output_uses_project_block() -> None:
    project = r"Y:\code\vaultspec-rag-worktrees\feature-server-supervision"
    payload: dict[str, object] = {
        "started": True,
        "watch_enabled": True,
    }
    with _updates_http_server(payload) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "updates", "start", project, "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    assert _UpdatesHTTPHandler.requests == [
        {"method": "POST", "path": "/watcher/start", "body": {"root": project}}
    ]
    labels = _label_values(result.output)
    assert labels["Address"] == f"http://127.0.0.1:{port}"
    assert labels["Automatic index updates"] == "started"
    assert labels["Project"] == "feature-server-supervision"
    assert labels["Path"] == project
    assert "started for:" not in result.output.lower()


def test_updates_start_times_out_with_next_actions(tmp_path: Path) -> None:
    project = str(tmp_path.resolve())
    previous = os.environ.get("VAULTSPEC_RAG_ADMIN_TIMEOUT")
    os.environ["VAULTSPEC_RAG_ADMIN_TIMEOUT"] = "0.05"
    try:
        with _slow_updates_http_server() as (_server, port):
            result = runner.invoke(
                app,
                ["server", "updates", "start", project, "--port", str(port)],
            )
    finally:
        if previous is None:
            os.environ.pop("VAULTSPEC_RAG_ADMIN_TIMEOUT", None)
        else:
            os.environ["VAULTSPEC_RAG_ADMIN_TIMEOUT"] = previous

    assert result.exit_code == 1, result.output
    assert _SlowUpdatesHTTPHandler.requests == [
        {"method": "POST", "path": "/watcher/start", "body": {"root": project}}
    ]
    labels = _label_values(result.output)
    assert labels["Address"] == f"http://127.0.0.1:{port}"
    lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    joined = " ".join(lines)
    assert (
        f"Automatic index updates: The service on port {port} "
        "did not answer within 0.05 seconds."
    ) in joined
    assert labels["Project"] == tmp_path.name
    assert labels["Path"] == project
    assert "Next actions:" in result.output
    assert f"vaultspec-rag server status --port {port}" in result.output
    assert f"vaultspec-rag server logs --limit 200 --port {port}" in result.output


def test_updates_start_timeout_uses_singular_second(tmp_path: Path) -> None:
    project = str(tmp_path.resolve())
    previous = os.environ.get("VAULTSPEC_RAG_ADMIN_TIMEOUT")
    os.environ["VAULTSPEC_RAG_ADMIN_TIMEOUT"] = "1"
    try:
        with _slow_updates_http_server(delay_seconds=1.5) as (_server, port):
            result = runner.invoke(
                app,
                ["server", "updates", "start", project, "--port", str(port)],
            )
    finally:
        if previous is None:
            os.environ.pop("VAULTSPEC_RAG_ADMIN_TIMEOUT", None)
        else:
            os.environ["VAULTSPEC_RAG_ADMIN_TIMEOUT"] = previous

    assert result.exit_code == 1, result.output
    lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    joined = " ".join(lines)
    assert (
        f"Automatic index updates: The service on port {port} "
        "did not answer within 1 second."
    ) in joined
    assert "1 seconds" not in result.output


@pytest.mark.parametrize(
    ("argv", "payload", "expected_status", "request_path", "request_extra"),
    [
        (
            ["server", "updates", "start", "."],
            {"started": True, "watch_enabled": True},
            "started",
            "/watcher/start",
            {},
        ),
        (
            ["server", "updates", "stop", "."],
            {"stopped": True},
            "stopped",
            "/watcher/stop",
            {},
        ),
        (
            [
                "server",
                "updates",
                "timing",
                ".",
                "--update-delay-ms",
                "500",
                "--repeat-update-delay-s",
                "2",
            ],
            {"restarted": True, "debounce_ms": 500, "cooldown_s": 2.0},
            "timing updated",
            "/watcher/reconfigure",
            {"debounce_ms": 500, "cooldown_s": 2.0},
        ),
    ],
)
def test_updates_project_commands_resolve_relative_project(
    tmp_path: Path,
    argv: list[str],
    payload: dict[str, object],
    expected_status: str,
    request_path: str,
    request_extra: dict[str, object],
) -> None:
    project = str(tmp_path.resolve())
    previous_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with _updates_http_server(payload) as (_server, port):
            result = runner.invoke(app, [*argv, "--port", str(port)])
    finally:
        os.chdir(previous_cwd)

    assert result.exit_code == 0, result.output
    body = {"root": project, **request_extra}
    assert _UpdatesHTTPHandler.requests == [
        {"method": "POST", "path": request_path, "body": body}
    ]
    labels = _label_values(result.output)
    assert labels["Automatic index updates"] == expected_status
    assert labels["Project"] == tmp_path.name
    assert labels["Path"] == project
    assert "Project: ." not in result.output
    assert "Path: ." not in result.output


def test_updates_timing_help_uses_user_facing_timing_flags() -> None:
    result = runner.invoke(app, ["server", "updates", "timing", "--help"])
    assert result.exit_code == 0
    assert "--update-delay-ms" in result.stdout
    assert "--repeat-update-delay-s" in result.stdout
    assert "--same-project-delay-s" not in result.stdout
    assert "--same-source-delay-s" not in result.stdout
    assert "--debounce-ms" not in result.stdout
    assert "--cooldown-s" not in result.stdout


@pytest.mark.parametrize(
    "argv",
    [
        [
            "server",
            "updates",
            "timing",
            "/tmp/x",
            "--update-delay-ms",
            "500",
            "--repeat-update-delay-s",
            "2",
        ],
    ],
)
def test_updates_timing_flags_parse(argv: list[str]) -> None:
    result = runner.invoke(app, [*argv, "--port", _DEAD_PORT, "--json"])
    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["command"] == "service.updates.timing"
    assert payload["error"] == "service_not_running"


def test_updates_timing_output_uses_project_block() -> None:
    project = r"Y:\code\vaultspec-rag-worktrees\feature-server-supervision"
    payload: dict[str, object] = {
        "restarted": True,
        "debounce_ms": 500,
        "cooldown_s": 2.0,
    }
    with _updates_http_server(payload) as (_server, port):
        result = runner.invoke(
            app,
            [
                "server",
                "updates",
                "timing",
                project,
                "--update-delay-ms",
                "500",
                "--repeat-update-delay-s",
                "2",
                "--port",
                str(port),
            ],
        )

    assert result.exit_code == 0, result.output
    assert _UpdatesHTTPHandler.requests == [
        {
            "method": "POST",
            "path": "/watcher/reconfigure",
            "body": {"root": project, "debounce_ms": 500, "cooldown_s": 2.0},
        }
    ]
    labels = _label_values(result.output)
    assert labels["Address"] == f"http://127.0.0.1:{port}"
    assert labels["Automatic index updates"] == "timing updated"
    assert labels["Project"] == "feature-server-supervision"
    assert labels["Path"] == project
    assert labels["File changes"] == "wait 500 milliseconds before updating."
    assert labels["Repeat updates"] == "wait 2 seconds before updating a project again."
    assert "reconfigured for:" not in result.output.lower()


@pytest.mark.parametrize(
    "argv",
    [
        ["server", "updates", "reconfigure", "/tmp/x"],
        [
            "server",
            "updates",
            "timing",
            "/tmp/x",
            "--same-project-delay-s",
            "2",
        ],
        [
            "server",
            "updates",
            "timing",
            "/tmp/x",
            "--same-source-delay-s",
            "2",
        ],
        [
            "server",
            "updates",
            "timing",
            "/tmp/x",
            "--debounce-ms",
            "500",
            "--cooldown-s",
            "2",
        ],
    ],
)
def test_updates_removed_legacy_forms_are_not_supported(argv: list[str]) -> None:
    result = runner.invoke(app, [*argv, "--port", _DEAD_PORT])
    assert result.exit_code != 0
    assert "not running" not in result.stdout.lower()


def test_watcher_alias_removed_from_user_facing_cli() -> None:
    server_help = runner.invoke(app, ["server", "--help"])
    assert server_help.exit_code == 0
    assert "updates" in server_help.stdout
    assert "watcher" not in server_help.stdout.lower()

    updates = runner.invoke(app, ["server", "updates", "status", "--port", _DEAD_PORT])
    assert updates.exit_code == 3
    assert "not running" in updates.stdout.lower()

    legacy = runner.invoke(app, ["server", "watcher", "status", "--port", _DEAD_PORT])
    assert legacy.exit_code != 0
    assert "No such command" in legacy.output


def test_cli_mcp_control_parity() -> None:
    # The MCP surface is deliberately narrowed to the five search/read/reindex
    # tools (mcp-search-scope ADR); watcher control lives on the CLI, exposed
    # with human-facing "updates" language.
    import asyncio

    from ..mcp import mcp

    tools = sorted(t.name for t in asyncio.run(mcp.list_tools()))
    assert tools == [
        "get_code_file",
        "reindex_codebase",
        "reindex_vault",
        "search_codebase",
        "search_vault",
    ]
    help_result = runner.invoke(app, ["server", "updates", "--help"])
    assert help_result.exit_code == 0
    assert _help_command_names(help_result.stdout) == [
        "status",
        "start",
        "stop",
        "timing",
    ]
