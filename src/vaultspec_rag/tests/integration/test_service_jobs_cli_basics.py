"""Focused real-behavior coverage for the managed service jobs surface."""

from __future__ import annotations

import json
import urllib.parse

import pytest

from vaultspec_rag.cli import app

from ._service_jobs_support import (
    _DEAD_PORT,
    _jobs_http_server,
    _JobsHTTPHandler,
    _plain_lines,
    runner,
)


@pytest.mark.unit
def test_jobs_not_running_json() -> None:
    result = runner.invoke(
        app,
        ["server", "jobs", "--port", _DEAD_PORT, "--json"],
    )
    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "service.jobs"
    assert payload["error"] == "service_not_running"


@pytest.mark.unit
def test_jobs_not_running_prose() -> None:
    result = runner.invoke(app, ["server", "jobs", "--port", _DEAD_PORT])
    assert result.exit_code == 3
    assert f"Address: http://127.0.0.1:{_DEAD_PORT}" in result.stdout
    assert "not running" in result.stdout.lower()


@pytest.mark.unit
def test_jobs_subcommand_registered() -> None:
    result = runner.invoke(app, ["server", "jobs", "--help"])
    assert result.exit_code == 0
    expected_flags = (
        "--state",
        "--index",
        "--query",
        "--failed",
        "--job-id",
        "--started-by",
        "--since",
        "--watch",
        "--interval",
        "--refresh-count",
    )
    missing = [flag for flag in expected_flags if flag not in result.stdout]
    assert not missing, f"missing flags in help: {missing}"
    assert "--phase" not in result.stdout
    assert "--source" not in result.stdout
    assert "--trigger" not in result.stdout
    assert "--running" not in result.stdout


@pytest.mark.unit
def test_jobs_help_uses_operator_language() -> None:
    result = runner.invoke(app, ["server", "jobs", "--help"])
    assert result.exit_code == 0
    normalized = " ".join(result.stdout.split())
    expected_phrases = (
        "Filter by job state",
        "job id, outcome, or progress",
        "automatic updates",
        "manual requests",
        "index update activity",
        "Show only failed jobs",
        "Continuously refresh the human jobs view",
        "Stop --watch after this many refreshes",
        "active, waiting, finished, failed, or cancelled",
    )
    missing = [phrase for phrase in expected_phrases if phrase not in normalized]
    assert not missing, f"missing operator phrasing: {missing}"
    forbidden_phrases = (
        "job id, result, or progress",
        "--source",
        "--trigger",
        "'watcher'",
        "index/reindex",
        "failed/error",
        "running, done, or failed",
    )
    leaked = [phrase for phrase in forbidden_phrases if phrase in normalized]
    assert not leaked, f"internal phrasing leaked into help: {leaked}"


@pytest.mark.unit
def test_jobs_filter_summary_uses_operator_language() -> None:
    from ...cli._service_jobs_presentation import _filters_label

    rendered = _filters_label(
        {
            "filters": {
                "phase": "running",
                "trigger": "watcher",
                "source": "code",
                "failed": True,
            }
        }
    )

    assert rendered == (
        " Filtered by state active or waiting; index code; "
        "started by automatic updates; failed only."
    )
    assert "phase=" not in rendered
    assert "state=" not in rendered
    assert "trigger=" not in rendered
    assert "started by=" not in rendered
    assert "watcher" not in rendered


@pytest.mark.unit
def test_jobs_filter_summary_humanizes_finished_state() -> None:
    from ...cli._service_jobs_presentation import _filters_label

    rendered = _filters_label({"filters": {"phase": "done", "limit": 5}})

    assert rendered == " Filtered by state finished."
    assert "state=done" not in rendered
    assert "state=" not in rendered


@pytest.mark.unit
def test_jobs_index_filter_is_operator_facing_cli_alias() -> None:
    with _jobs_http_server(
        [
            {
                "jobs": [],
                "filters": {"limit": 20, "source": "code"},
                "total": 0,
                "returned": 0,
            }
        ]
    ) as (
        _server,
        port,
    ):
        result = runner.invoke(
            app,
            [
                "server",
                "jobs",
                "--index",
                "code",
                "--port",
                str(port),
            ],
        )

    assert result.exit_code == 0, result.output
    request = urllib.parse.urlparse(_JobsHTTPHandler.paths[0])
    query = urllib.parse.parse_qs(request.query)
    assert request.path == "/jobs"
    assert query["source"] == ["code"]
    assert "No jobs matched these filters." in result.output
    assert "--source" not in result.output


@pytest.mark.unit
def test_jobs_started_by_filter_is_operator_facing_cli_alias() -> None:
    with _jobs_http_server(
        [
            {
                "jobs": [],
                "filters": {"limit": 20, "trigger": "watcher"},
                "total": 0,
                "returned": 0,
            }
        ]
    ) as (
        _server,
        port,
    ):
        result = runner.invoke(
            app,
            [
                "server",
                "jobs",
                "--started-by",
                "automatic",
                "--port",
                str(port),
            ],
        )

    assert result.exit_code == 0, result.output
    request = urllib.parse.urlparse(_JobsHTTPHandler.paths[0])
    query = urllib.parse.parse_qs(request.query)
    assert request.path == "/jobs"
    assert query["trigger"] == ["watcher"]
    assert "No jobs matched these filters." in result.output
    assert "--trigger" not in result.output


@pytest.mark.unit
@pytest.mark.parametrize(
    ("state", "phase", "filter_line", "empty_message"),
    [
        (
            "active",
            "running",
            "Filter: state active",
            "There are no active jobs.",
        ),
        (
            "waiting",
            "running",
            "Filter: state waiting",
            "There are no waiting jobs.",
        ),
        (
            "finished",
            "done",
            "Filter: state finished",
            "No jobs matched these filters.",
        ),
    ],
)
def test_jobs_state_filter_sends_service_phase(
    state: str,
    phase: str,
    filter_line: str,
    empty_message: str,
) -> None:
    with _jobs_http_server([{"jobs": [], "filters": {"phase": phase}, "total": 0}]) as (
        _server,
        port,
    ):
        result = runner.invoke(
            app,
            ["server", "jobs", "--port", str(port), "--state", state],
        )

    assert result.exit_code == 0, result.stdout
    request = urllib.parse.urlparse(_JobsHTTPHandler.paths[0])
    query = urllib.parse.parse_qs(request.query)
    assert query["phase"] == [phase]
    assert filter_line in result.stdout
    assert empty_message in result.stdout


@pytest.mark.unit
@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (
            ["server", "jobs", "--state", "bananas"],
            'Invalid --state "bananas". Use active, waiting, finished, failed, '
            "or cancelled.",
        ),
        (
            ["server", "jobs", "--index", "database"],
            'Invalid --index "database". Use vault or code.',
        ),
        (
            ["server", "jobs", "--started-by", "robot"],
            'Invalid --started-by "robot". Use manual or automatic.',
        ),
    ],
)
def test_jobs_rejects_invalid_filter_values(argv: list[str], message: str) -> None:
    result = runner.invoke(
        app,
        [*argv, "--port", _DEAD_PORT],
    )

    assert result.exit_code == 2
    assert message in result.stdout
    assert "not running" not in result.stdout.lower()


@pytest.mark.unit
def test_jobs_rejects_invalid_filter_values_as_json() -> None:
    result = runner.invoke(
        app,
        [
            "server",
            "jobs",
            "--state",
            "bananas",
            "--port",
            _DEAD_PORT,
            "--json",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "service.jobs"
    assert payload["error"] == "invalid_filter"
    assert 'Invalid --state "bananas"' in payload["message"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["server", "jobs", "--phase", "finished"],
        ["server", "jobs", "--source", "code"],
        ["server", "jobs", "--trigger", "automatic"],
    ],
)
def test_jobs_removed_legacy_filter_flags_are_not_supported(
    argv: list[str],
) -> None:
    result = runner.invoke(app, [*argv, "--port", _DEAD_PORT])

    assert result.exit_code != 0
    assert "not running" not in result.stdout.lower()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("result", "expected_message", "expected_filter"),
    [
        (
            {"jobs": [], "filters": {"limit": 5, "phase": "running"}},
            "There are no active or waiting jobs.",
            "Filter: state active or waiting",
        ),
        (
            {"jobs": [], "filters": {"limit": 5, "failed": True}},
            "There are no failed jobs.",
            "Filter: failed only",
        ),
        (
            {"jobs": [], "filters": {"limit": 5, "source": "code"}},
            "No jobs matched these filters.",
            "Filter: index code",
        ),
        (
            {"jobs": [], "filters": {"limit": 5}},
            "No jobs have been reported by this service yet.",
            None,
        ),
    ],
)
def test_empty_jobs_output_is_actionable(
    result: dict[str, object],
    expected_message: str,
    expected_filter: str | None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ...cli._service_jobs_presentation import render_jobs_result

    render_jobs_result(result, job_id=None, port=8766)

    output = capsys.readouterr().out
    lines = _plain_lines(output)
    expected_present = [
        "Jobs",
        "Address: http://127.0.0.1:8766",
        "Displayed: 0 matching jobs" if expected_filter else "Displayed: 0 jobs",
        "Displayed jobs: 0 active, 0 waiting, 0 finished, 0 failed",
        "Order: latest job appears last",
        expected_message,
        "Next actions:",
        "vaultspec-rag server status --port 8766",
        "vaultspec-rag server logs --limit 20 --port 8766",
    ]
    if expected_filter is not None:
        expected_present.append(expected_filter)
    missing = [line for line in expected_present if line not in lines]
    assert not missing, f"missing actionable empty-jobs lines: {missing}"
    assert "No running jobs." not in output
    assert "No recent jobs." not in output
