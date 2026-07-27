"""CLI tests for automatic index update subcommands.

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
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

import pytest
from typer.testing import CliRunner

from ..cli import app
from ._http_stubs import QuietHandler

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

runner = CliRunner()

pytestmark = [pytest.mark.unit]

# A port with nothing listening: _try_http_admin gets connection-refused
# and returns None -> the command reports service-not-running (exit 3).
_DEAD_PORT = "59231"

# The watcher CLI resolves every project argument through
# Path(project).expanduser().resolve() before round-tripping it into the
# admin request body and the rendered "Path:" line. A hardcoded drive-letter
# literal is absolute (and therefore resolve()-idempotent) only on a host
# whose current drive happens to match; on POSIX it is a plain relative path
# component, so resolve() rewrites it against the runner's cwd and breaks
# every exact round-trip assertion below. os.path.abspath(os.path.join(...))
# is genuinely absolute - and therefore resolve()-idempotent - on whichever
# platform runs the test.
_TEST_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.sep, "projects", "code-worktrees", "feature-server-supervision")
)


@dataclass(frozen=True, slots=True)
class _ProjectCommandCase:
    argv: list[str]
    payload: dict[str, object]
    expected_status: str
    request_path: str
    request_extra: dict[str, object]


class _UpdatesHTTPHandler(QuietHandler):
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


class _SlowUpdatesHTTPHandler(QuietHandler):
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
            r"C:\projects\code-worktrees\feature-server-supervision",
            r"C:\projects\sample-project\main",
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
    assert r"  Path: C:\projects\code-worktrees\feature-server-supervision" in (
        result.output
    )
    assert "- Project: main" in result.output
    assert r"  Path: C:\projects\sample-project\main" in (result.output)
    assert (
        r"- C:\projects\code-worktrees\feature-server-supervision" not in result.output
    )


def test_updates_start_output_uses_project_block() -> None:
    project = _TEST_PROJECT_ROOT
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
            # The client stops waiting after its 0.05s deadline, but the
            # request it sent is recorded by the server's own thread, and
            # leaving this block shuts that server down. Assert on the record
            # only once it exists: otherwise the test asks whether the host
            # scheduled that thread inside a 50ms window, which is a property
            # of the machine and not of the code under test. A request that
            # never arrives still fails the assertion below, just later.
            deadline = time.monotonic() + 5.0
            while not _SlowUpdatesHTTPHandler.requests:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
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
    "case",
    [
        _ProjectCommandCase(
            ["server", "updates", "start", "."],
            {"started": True, "watch_enabled": True},
            "started",
            "/watcher/start",
            {},
        ),
        _ProjectCommandCase(
            ["server", "updates", "stop", "."],
            {"stopped": True},
            "stopped",
            "/watcher/stop",
            {},
        ),
        _ProjectCommandCase(
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
    case: _ProjectCommandCase,
) -> None:
    project = str(tmp_path.resolve())
    previous_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with _updates_http_server(case.payload) as (_server, port):
            result = runner.invoke(app, [*case.argv, "--port", str(port)])
    finally:
        os.chdir(previous_cwd)

    assert result.exit_code == 0, result.output
    body = {"root": project, **case.request_extra}
    assert _UpdatesHTTPHandler.requests == [
        {"method": "POST", "path": case.request_path, "body": body}
    ]
    labels = _label_values(result.output)
    assert labels["Automatic index updates"] == case.expected_status
    assert labels["Project"] == tmp_path.name
    assert labels["Path"] == project
    assert "Project: ." not in result.output
    assert "Path: ." not in result.output


def test_updates_start_already_running_is_success() -> None:
    """An already-satisfied start is success, so a broker can start blindly."""
    payload: dict[str, object] = {
        "started": True,
        "status": "already_running",
        "watch_enabled": True,
    }
    with _updates_http_server(payload) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "updates", "start", _TEST_PROJECT_ROOT, "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    assert _label_values(result.output)["Automatic index updates"] == "already running"


@pytest.mark.parametrize("status", ["queued_behind_drain", "pending"])
def test_updates_start_not_yet_running_exits_non_zero(status: str) -> None:
    """A start the service only recorded must not read as success.

    Mutation this catches: treating a recorded-but-unhonoured start as
    achieved. The exit code is the assertion - a zero exit here is exactly
    the failure that leaves a project silently unindexed.
    """
    payload: dict[str, object] = {
        "started": False,
        "status": status,
        "watch_enabled": True,
    }
    with _updates_http_server(payload) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "updates", "start", _TEST_PROJECT_ROOT, "--port", str(port)],
        )

    assert result.exit_code == 1, result.output
    assert _label_values(result.output)["Automatic index updates"] == "not started"
    joined = " ".join(line.strip() for line in result.output.splitlines())
    assert "queued behind it" in joined
    assert f"vaultspec-rag server updates status --port {port}" in result.output


@pytest.mark.parametrize("status", ["queued_behind_drain", "pending"])
def test_updates_start_not_yet_running_json_exits_non_zero(status: str) -> None:
    payload: dict[str, object] = {
        "started": False,
        "status": status,
        "watch_enabled": True,
    }
    with _updates_http_server(payload) as (_server, port):
        result = runner.invoke(
            app,
            [
                "server",
                "updates",
                "start",
                _TEST_PROJECT_ROOT,
                "--port",
                str(port),
                "--json",
            ],
        )

    assert result.exit_code == 1, result.output
    # One envelope on this exit path, so a whole-stdout parse must succeed.
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["command"] == "service.updates.start"
    assert envelope["error"] == "updates_pending"
    assert envelope["data"]["status"] == status


def test_updates_start_disabled_exits_non_zero_with_enable_action() -> None:
    payload: dict[str, object] = {
        "started": False,
        "status": "disabled",
        "watch_enabled": False,
    }
    with _updates_http_server(payload) as (_server, port):
        human = runner.invoke(
            app,
            ["server", "updates", "start", _TEST_PROJECT_ROOT, "--port", str(port)],
        )
    with _updates_http_server(payload) as (_server, port):
        json_mode = runner.invoke(
            app,
            [
                "server",
                "updates",
                "start",
                _TEST_PROJECT_ROOT,
                "--port",
                str(port),
                "--json",
            ],
        )

    assert human.exit_code == 1, human.output
    assert "vaultspec-rag server start --updates" in human.output
    assert json_mode.exit_code == 1, json_mode.output
    envelope = json.loads(json_mode.stdout)
    assert envelope["ok"] is False
    assert envelope["error"] == "updates_disabled"


def test_updates_timing_not_yet_applied_exits_non_zero() -> None:
    payload: dict[str, object] = {
        "restarted": False,
        "status": "queued_behind_drain",
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
                _TEST_PROJECT_ROOT,
                "--update-delay-ms",
                "500",
                "--port",
                str(port),
                "--json",
            ],
        )

    assert result.exit_code == 1, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["command"] == "service.updates.timing"
    assert envelope["error"] == "updates_pending"


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
    project = _TEST_PROJECT_ROOT
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
    # The MCP surface is kind-parametric: for each indexed content kind it
    # carries one search verb and one index-refresh verb, plus the union
    # conveniences, the search-adjacent file reader, index-readiness, and the
    # destructive index-cleaning counterparts. Lifecycle and operational
    # administration (watcher control, service state, jobs, logs, storage
    # survey, project eviction, start/stop/warmup) stay CLI-only.
    #
    # This is the authorised surface, not a floor: the guard is an exact set
    # so unratified growth turns it red. When a new content kind is indexed,
    # extend `kinds` below - do not append names loosely - and confirm the
    # decision that admits it. `analyze_feature` is a prompt, not a tool, so
    # it is deliberately absent from the tool listing.
    import asyncio

    from ..mcp import mcp

    kinds = ("vault", "codebase", "documents")
    expected = {
        *(f"search_{kind}" for kind in kinds),
        *(f"reindex_{kind}" for kind in kinds),
        "search_combined",
        "reindex_all",
        "get_code_file",
        "get_index_status",
        "clean_documents",
        "clean_all",
    }

    tools = {t.name for t in asyncio.run(mcp.list_tools())}
    assert tools == expected
    help_result = runner.invoke(app, ["server", "updates", "--help"])
    assert help_result.exit_code == 0
    assert _help_command_names(help_result.stdout) == [
        "status",
        "start",
        "stop",
        "timing",
    ]
