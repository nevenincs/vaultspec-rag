"""CLI coverage for the service daemon status helpers and summaries."""

from __future__ import annotations

import contextlib
import http.server
import json
import os
import threading
import time
from typing import TYPE_CHECKING, Any, cast

import pytest

from ..serviceclient._transport import _try_http_health
from ._cli_helpers import (
    _assert_default_status_summary,
    _assert_verbose_status_summary,
    _find_free_port,
    _is_our_service,
    _is_pid_alive,
    _isolated_status_dir,
    _label_values,
    _plain_lines,
    _read_service_status,
    _running_service_record,
    _serving,
    _status_contract_server,
    _write_service_status,
    app,
    runner,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

#: A full-length job id, so the rendered prose (short prefix) and the rendered
#: command (full id, which is what the log filter needs) stay distinguishable.
_FAILED_JOB_ID = "e8f8ac43-438e-42de-8037-3d83e7fc9e3e"

#: Chosen to land mid-minute so the rendered age cannot flip a minute boundary
#: while the test runs.
_FAILURE_AGE_SECONDS = 5 * 3600 + 46 * 60 + 30
_FAILURE_AGE_TEXT = "5 hours 46 minutes"


def _jobs_payload(*, done: int = 191, failed: int = 45) -> dict[str, object]:
    return {
        "ok": True,
        "jobs": [],
        "total": done + failed,
        "returned": 0,
        "summary": {"running": 0, "phases": {"done": done, "error": failed}},
    }


def _idle_jobs_payload() -> dict[str, object]:
    """The jobs report of a service with no history and nothing running."""
    return {
        "ok": True,
        "jobs": [],
        "total": 0,
        "returned": 0,
        "summary": {"running": 0, "phases": {}},
    }


def _ready_health_payload() -> dict[str, object]:
    """A minimal healthy report, for tests whose subject is not the health."""
    return {
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


def _last_failed_record() -> dict[str, object]:
    return {
        "id": _FAILED_JOB_ID,
        "error_kind": "other",
        "finished_at": time.time() - _FAILURE_AGE_SECONDS,
    }


def _health_payload(
    *,
    status: str = "degraded",
    reasons: list[str] | None = None,
    jobs: dict[str, object] | None = None,
    **extra: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "degraded_reasons": [] if reasons is None else reasons,
        "cuda": True,
        "models_loaded": True,
        "reranker_loaded": True,
        "project_count": 3,
        "uptime_s": 850.0,
        "jobs": {"running": 0, "queued": 0, "stalled": 0} | (jobs or {}),
    }
    payload.update(extra)
    return payload


@contextlib.contextmanager
def _live_status_service(
    status_dir: Path,
    contract_server: tuple[Any, Any],
    *,
    drop: tuple[str, ...] = (),
) -> Generator[int]:
    """Serve the shared status contract behind a live-looking service record.

    Takes the already-constructed server so each caller keeps its own typed
    ``_status_contract_server`` arguments, and owns the teardown of both the
    server thread and the status-directory isolation.
    """
    server, thread = contract_server
    try:
        with _running_service_record(status_dir, server.server_address[1], drop=drop):
            yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _status_against(
    tmp_path: Path,
    health: dict[str, object],
    *args: str,
    jobs: dict[str, object] | None = None,
) -> Any:
    """Run ``server status`` against a service reporting the given health."""
    with _live_status_service(
        tmp_path,
        _status_contract_server(
            health=health, jobs=_jobs_payload() if jobs is None else jobs
        ),
    ):
        return runner.invoke(app, ["server", "status", *args])


class TestDegradedStatusExplainsItself:
    """A degraded service must report its cause and a runnable remediation.

    The health payload already carries both - the reasons and the structured
    signals behind them - so a summary that prints the severity word alone is
    discarding what the operator needs. Each test below pins one reason family
    to the verb that inspects it.
    """

    def test_failed_indexing_job_names_the_job_and_the_log_command(
        self, tmp_path: Path
    ) -> None:
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=["the latest indexing job failed: other"],
                jobs={"last_failed": _last_failed_record()},
            ),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "Degraded because:" in lines
        assert "- the latest indexing job failed: other" in lines
        assert f"job e8f8ac43, {_FAILURE_AGE_TEXT} ago" in lines
        assert f"vaultspec-rag server logs --job-id {_FAILED_JOB_ID}" in lines
        # The concrete remediation replaces the generic re-run-with-more-rows.
        next_action = lines[lines.index("Next action:") + 1]
        assert next_action == f"vaultspec-rag server logs --job-id {_FAILED_JOB_ID}"
        assert "--verbose" not in result.output

    def test_failed_job_count_carries_the_failed_jobs_view(
        self, tmp_path: Path
    ) -> None:
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=["the latest indexing job failed: other"],
                jobs={"last_failed": _last_failed_record()},
            ),
        )

        assert result.exit_code == 0, result.output
        labels = _label_values(result.output)
        assert (
            labels["Processed jobs"] == "191 finished, 0 active, 0 waiting, 45 failed"
        )
        assert labels["Review failures"] == "vaultspec-rag server jobs --failed"
        # The degraded block already named this job; naming it twice is noise.
        assert "Last failure" not in labels

    def test_stalled_jobs_point_at_the_active_jobs_view(self, tmp_path: Path) -> None:
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=["2 indexing job(s) are stalled"],
                jobs={"stalled": 2},
            ),
            jobs=_jobs_payload(failed=0),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "- 2 indexing job(s) are stalled" in lines
        assert "vaultspec-rag server jobs --state active" in lines
        assert lines[lines.index("Next action:") + 1] == (
            "vaultspec-rag server jobs --state active"
        )

    def test_unloaded_models_point_at_the_readiness_check(self, tmp_path: Path) -> None:
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=["embedding models are not loaded"],
                models_loaded=False,
            ),
            jobs=_jobs_payload(failed=0),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "- embedding models are not loaded" in lines
        assert "run server warmup when the model files are missing" in lines
        assert lines[lines.index("Next action:") + 1] == "vaultspec-rag server doctor"

    def test_dead_vector_service_points_at_the_qdrant_view(
        self, tmp_path: Path
    ) -> None:
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=["the configured vector service is not live"],
                qdrant={"mode": "server", "alive": False, "port": 6333},
            ),
            jobs=_jobs_payload(failed=0),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "- the configured vector service is not live" in lines
        assert lines[lines.index("Next action:") + 1] == (
            "vaultspec-rag server qdrant status"
        )

    def test_every_reason_is_rendered_when_several_are_reported(
        self, tmp_path: Path
    ) -> None:
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=[
                    "embedding models are not loaded",
                    "3 indexing job(s) are stalled",
                ],
                models_loaded=False,
                jobs={"stalled": 3},
            ),
            jobs=_jobs_payload(failed=0),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "- embedding models are not loaded" in lines
        assert "- 3 indexing job(s) are stalled" in lines
        assert "vaultspec-rag server doctor" in lines
        assert "vaultspec-rag server jobs --state active" in lines

    def test_verbose_detail_also_explains_the_degradation(self, tmp_path: Path) -> None:
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=["the latest indexing job failed: other"],
                jobs={"last_failed": _last_failed_record()},
            ),
            "--verbose",
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert lines[lines.index("Requests: degraded") + 1] == "Degraded because:"
        assert f"vaultspec-rag server logs --job-id {_FAILED_JOB_ID}" in lines

    def test_json_envelope_carries_the_structured_findings(
        self, tmp_path: Path
    ) -> None:
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=["the latest indexing job failed: other"],
                jobs={"last_failed": _last_failed_record()},
            ),
            "--json",
        )

        assert result.exit_code == 0, result.output
        operational = json.loads(result.stdout)["data"]["operational"]
        findings = cast("list[dict[str, str]]", operational["degraded"])
        assert [finding["cause"] for finding in findings] == [
            "the latest indexing job failed: other"
        ]
        assert findings[0]["family"] == "failed_job"
        assert findings[0]["command"] == (
            f"vaultspec-rag server logs --job-id {_FAILED_JOB_ID}"
        )
        assert operational["failure"]["command"] == "vaultspec-rag server jobs --failed"


class TestReasonsSurviveRewording:
    """A reason this build cannot recognise must still reach the operator.

    The reasons are prose owned by the service, so any pairing between a reason
    and a remediation is a guess that can go stale. Both directions of that
    staleness are guarded here: an unrecognised reason is still rendered, and a
    recognised problem still gets its command even when no reason claimed it.
    """

    def test_unrecognised_reason_is_rendered_beside_a_recognised_one(
        self, tmp_path: Path
    ) -> None:
        """An unmappable reason is reported even with no remediation to offer.

        The recognised reason is here so the block still renders when the
        unrecognised one is dropped: that isolates the failure to the verbatim
        line, which is the property under test. Asserting the exact raw text is
        deliberate - a looser match would pass on a paraphrase, and a paraphrase
        of a reason this build does not understand is a fabrication.

        Verified to fail for the right reason: dropping the unpaired reason
        instead of recording it (the ``stem is None`` branch of the finding
        walk) fails this test on the verbatim line while every other assertion
        here still passes; restoring the branch returns it to green.
        """
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=[
                    "embedding models are not loaded",
                    "the storage volume is nearly full",
                ],
                models_loaded=False,
            ),
            jobs=_jobs_payload(failed=0),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "Degraded because:" in lines
        assert "- the storage volume is nearly full" in lines

    def test_degradation_nothing_recognises_falls_back_to_the_logs(
        self, tmp_path: Path
    ) -> None:
        result = _status_against(
            tmp_path,
            _health_payload(reasons=["the storage volume is nearly full"]),
            jobs=_jobs_payload(failed=0),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "- the storage volume is nearly full" in lines
        # Nothing specific applies, so the logs beat re-running status verbose.
        assert lines[lines.index("Next action:") + 1] == (
            "vaultspec-rag server logs --limit 80"
        )
        assert "--verbose" not in result.output

    def test_reworded_reason_keeps_the_remediation_for_its_signal(
        self, tmp_path: Path
    ) -> None:
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=["the most recent index run did not complete"],
                jobs={"last_failed": _last_failed_record()},
            ),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "- the most recent index run did not complete" in lines
        # Unclaimed by any reason, the proven signal still reports itself.
        assert "- an indexing job failed: other" in lines
        assert f"vaultspec-rag server logs --job-id {_FAILED_JOB_ID}" in lines


class TestOneRendererServesEverySurface:
    """Degradation is rendered in one place, for every payload that reports it.

    Two payloads report degradation in different shapes - the service health
    payload in prose, the project index payload in structured per-domain records
    - and both reach operators through the same renderer. The shapes are covered
    here because a second renderer for either one is how the wording, the
    remediation, and the never-drop guarantee drift apart.
    """

    def test_structured_index_records_render_a_cause_not_a_container(self) -> None:
        from ..cli._status import _status_diagnostics

        lines = _status_diagnostics(
            {
                "degraded_reasons": [
                    {
                        "source": "code",
                        "job_id": _FAILED_JOB_ID,
                        "reason": "failed",
                        "error_kind": "other",
                    },
                    {"source": "vault", "job_id": "abc12345-0000", "reason": "stalled"},
                ]
            }
        )

        assert lines == [
            "Degraded because:",
            "  - the code index job failed: other",
            "    job e8f8ac43",
            f"    vaultspec-rag server logs --job-id {_FAILED_JOB_ID}",
            "  - the vault index job is stalled",
            "    job abc12345",
            "    vaultspec-rag server jobs --state active",
        ]
        # The defect this replaced: a list of records interpolated into one
        # line, printing Python syntax at an operator.
        assert not any(("{" in line or "'" in line) for line in lines)

    def test_unphrasable_index_record_is_flattened_not_repred(self) -> None:
        from ..cli._status import _status_diagnostics

        lines = _status_diagnostics(
            {"degraded_reasons": [{"source": "code", "detail": "disk full"}]}
        )

        assert lines == ["Degraded because:", "  - source: code, detail: disk full"]

    def test_index_status_without_degradation_says_nothing(self) -> None:
        from ..cli._status import _status_diagnostics

        assert _status_diagnostics({"degraded_reasons": []}) == []
        assert _status_diagnostics({}) == []

    def test_compact_shape_lists_causes_without_remediation(self) -> None:
        from ..cli._status_labels import render_degradation

        payload = _health_payload(
            reasons=[
                "embedding models are not loaded",
                "the latest indexing job failed: other",
            ],
            models_loaded=False,
            jobs={"last_failed": _last_failed_record()},
        )

        assert render_degradation(
            payload,
            header="Serving, with warnings:",
            remediation=False,
        ) == [
            "Serving, with warnings:",
            "  - embedding models are not loaded",
            "  - the latest indexing job failed: other",
        ]

    def test_port_qualifier_reaches_every_rendered_command(self) -> None:
        from ..cli._status_labels import render_degradation

        lines = render_degradation(
            _health_payload(
                reasons=["the latest indexing job failed: other"],
                jobs={"last_failed": _last_failed_record()},
            ),
            header="Degraded because:",
            port_arg=" --port 8123",
        )

        assert lines[-1] == (
            f"    vaultspec-rag server logs --job-id {_FAILED_JOB_ID} --port 8123"
        )


class TestHealthyServiceStaysQuiet:
    """Nothing above is allowed to add noise to a service with no problem."""

    def test_healthy_summary_has_no_degraded_block(self, tmp_path: Path) -> None:
        with _live_status_service(tmp_path, _status_contract_server()) as port:
            result = runner.invoke(app, ["server", "status"])

            assert result.exit_code == 0, result.output
            _assert_default_status_summary(result.output, port)
            assert "Degraded because" not in result.output
            assert "Review failures" not in result.output
            assert "Last failure" not in result.output

    def test_historical_failure_is_reported_without_declaring_degradation(
        self, tmp_path: Path
    ) -> None:
        """A failure the service did not degrade over is history, not a verdict.

        It is still worth naming - the failed count above it is otherwise a dead
        end - but it belongs beside the count, not in a degradation block the
        service never reported.
        """
        result = _status_against(
            tmp_path,
            _health_payload(
                status="ready",
                jobs={"last_failed": _last_failed_record()},
            ),
        )

        assert result.exit_code == 0, result.output
        labels = _label_values(result.output)
        assert labels["Requests"] == "ready for requests"
        assert "Degraded because" not in result.output
        assert (
            labels["Last failure"] == f"job e8f8ac43 (other), {_FAILURE_AGE_TEXT} ago"
        )
        assert labels["Review failures"] == "vaultspec-rag server jobs --failed"
        lines = _plain_lines(result.output)
        assert lines[lines.index("Next action:") + 1].startswith("vaultspec-rag search")


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
        with _isolated_status_dir(tmp_path):
            _write_service_status(pid=12345, port=9999)
            data = _read_service_status()
            assert data is not None
            assert data["pid"] == 12345
            assert data["port"] == 9999
            assert "started_at" in data

    def test_write_creates_valid_json(self, tmp_path: Path):
        """Status file must be valid JSON with expected keys."""
        with _isolated_status_dir(tmp_path):
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

    def test_read_status_missing_file(self, tmp_path: Path):
        """Reading a nonexistent file should return None."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with _isolated_status_dir(empty_dir):
            assert _read_service_status() is None

    def test_read_status_invalid_json(self, tmp_path: Path):
        """Invalid JSON in status file should return None."""
        sf = tmp_path / "service.json"
        sf.write_text("not json", encoding="utf-8")
        with _isolated_status_dir(tmp_path):
            assert _read_service_status() is None

    def test_read_status_missing_pid_key(self, tmp_path: Path):
        """Status JSON without a pid key should return None."""
        sf = tmp_path / "service.json"
        sf.write_text('{"port": 8766}', encoding="utf-8")
        with _isolated_status_dir(tmp_path):
            assert _read_service_status() is None

    def test_service_stop_stale_pid(self, tmp_path: Path):
        """service_stop with a dead PID cleans up the status file."""
        with _isolated_status_dir(tmp_path):
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

    def test_service_status_stale_pid(self, tmp_path: Path):
        """service_status with a dead PID exits 4 and cleans the file.

        Divergent/crashed states exit 4 so scripts can branch on
        "known-bad" without parsing prose.
        """
        with _isolated_status_dir(tmp_path):
            _write_service_status(pid=99999999, port=8766)
            sf = tmp_path / "service.json"
            assert sf.exists()

            result = runner.invoke(app, ["server", "status"])
            assert result.exit_code == 4
            lower = result.output.lower()
            assert "crashed" in lower or "stale" in lower
            assert not sf.exists()

    def test_service_status_stale_pid_verbose_uses_condition_language(
        self, tmp_path: Path
    ):
        with _isolated_status_dir(tmp_path):
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

    def test_health_probe_nonlistening_port(self):
        """Health probe on a port with no listener should return None."""
        assert _try_http_health(1) is None

    def test_health_probe_non_json_response(self):
        """Health probe returns None when server sends non-JSON."""

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
            result = _try_http_health(port)
            assert result is None
        finally:
            server.server_close()
            t.join(timeout=5)

    def test_service_status_default_human_output_is_plain_summary(self, tmp_path: Path):
        """service status renders the plain operator summary by default."""
        with _live_status_service(
            tmp_path,
            _status_contract_server(),
        ) as port:
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

    def test_service_status_lists_multiple_active_jobs(self, tmp_path: Path):
        with _live_status_service(
            tmp_path,
            _status_contract_server(extra_running_job=True),
        ):
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

    def test_service_status_summary_reports_failed_jobs(self, tmp_path: Path):
        with _live_status_service(
            tmp_path,
            _status_contract_server(failed_jobs=2),
        ):
            result = runner.invoke(app, ["server", "status"])

            assert result.exit_code == 0, result.output
            labels = _label_values(result.output)
            assert (
                labels["Processed jobs"] == "2 finished, 1 active, 0 waiting, 2 failed"
            )
            assert "recent jobs" not in result.output
            assert "Jobs:" not in result.output

    def test_service_status_omits_missing_current_job_project(self, tmp_path: Path):
        with _live_status_service(
            tmp_path,
            _status_contract_server(omit_project=True),
        ):
            result = runner.invoke(app, ["server", "status"])

            assert result.exit_code == 0, result.output
            lines = _plain_lines(result.output)
            assert "Current job:" in lines
            assert "Operation: code index operation" in lines
            assert not any(line.startswith("Project:") for line in lines)
            assert "project not reported" not in result.output
            assert "project unknown" not in result.output

    def test_service_status_missing_start_times_use_reported_absence_language(
        self, tmp_path: Path
    ):
        with _live_status_service(
            tmp_path,
            _status_contract_server(omit_job_started_at=True),
            drop=("started_at",),
        ):
            result = runner.invoke(app, ["server", "status", "--verbose"])

            assert result.exit_code == 0, result.output
            labels = _label_values(result.output)
            assert labels["Started"] == "not reported by local record"
            assert labels["Runtime"] == "not reported by service"
            assert "unknown" not in result.output.lower()

    def _service_status_current_job_output(
        self,
        tmp_path: Path,
        *,
        last_progress_age_seconds: float,
    ) -> str:
        with _live_status_service(
            tmp_path,
            _status_contract_server(
                last_progress_age_seconds=last_progress_age_seconds,
            ),
        ):
            result = runner.invoke(app, ["server", "status"])

            assert result.exit_code == 0, result.output
            return " ".join(result.output.split())

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
        with (
            _isolated_status_dir(tmp_path),
            _serving(
                _status_contract_server(
                    health=_ready_health_payload(), jobs=_idle_jobs_payload()
                )
            ) as port,
        ):
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

    def test_service_status_sparse_health_uses_reported_absence_language(
        self, tmp_path: Path
    ):
        with (
            _isolated_status_dir(tmp_path),
            _serving(
                _status_contract_server(
                    health={"status": "ready"}, jobs=_idle_jobs_payload()
                )
            ) as port,
        ):
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

    def test_service_status_missing_health_status_is_reported_absence(
        self, tmp_path: Path
    ) -> None:
        with (
            _isolated_status_dir(tmp_path),
            _serving(
                _status_contract_server(
                    health={"uptime_s": 12}, jobs=_idle_jobs_payload()
                )
            ) as port,
        ):
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

    def test_service_status_jobs_error_is_reported_absence(
        self, tmp_path: Path
    ) -> None:
        with (
            _isolated_status_dir(tmp_path),
            _serving(
                _status_contract_server(
                    health={"status": "ready", "uptime_s": 60},
                    jobs={
                        "ok": False,
                        "error": "jobs_unavailable",
                        "message": "Job summary is not available.",
                    },
                    jobs_status_code=503,
                )
            ) as port,
        ):
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

    def test_service_status_port_only_verbose_uses_network_language(
        self, tmp_path: Path
    ) -> None:
        """Port-only verbose output should not expose raw yes/no socket labels."""
        with _isolated_status_dir(tmp_path):
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

    def test_service_status_port_ignores_stale_service_json(self, tmp_path: Path):
        """server status --port ignores stale service.json."""
        import json

        with (
            _isolated_status_dir(tmp_path),
            _serving(
                _status_contract_server(
                    health=_ready_health_payload(), jobs=_idle_jobs_payload()
                )
            ) as port,
        ):
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


class TestUnreachableStaysASentinelNotAnEscape:
    """Repointing the health call must not turn unreachability into an exception.

    The health owner returns a sentinel rather than raising precisely because
    these two verbs are broker-facing: each must emit exactly one structured
    outcome on every exit path. If an exception escaped the probe, a supervising
    caller would see a crash instead of an envelope, so this asserts the
    property at the verb rather than at the function.
    """

    def _one_envelope(self, output: str) -> dict[str, object]:
        payloads = [
            json.loads(line)
            for line in output.splitlines()
            if line.strip().startswith("{")
        ]
        assert len(payloads) == 1, f"expected exactly one envelope, got {payloads}"
        return payloads[0]

    def test_stop_against_a_dead_port_emits_one_success_envelope(
        self, tmp_path: Path
    ) -> None:
        with _isolated_status_dir(tmp_path):
            port = _find_free_port()
            result = runner.invoke(
                app, ["server", "stop", "--port", str(port), "--json"]
            )
            envelope = self._one_envelope(result.output)

        # Nothing was listening, so the probe returned its sentinel and the verb
        # treated it as an ordinary branch: an idempotent success, exit 0.
        assert result.exit_code == 0
        assert envelope["ok"] is True
        data = envelope["data"]
        assert isinstance(data, dict)
        typed_data = cast("dict[str, object]", data)
        assert typed_data["status"] == "already_stopped"

    def test_status_against_a_dead_port_emits_one_envelope(
        self, tmp_path: Path
    ) -> None:
        with _isolated_status_dir(tmp_path):
            port = _find_free_port()
            result = runner.invoke(
                app, ["server", "status", "--port", str(port), "--json"]
            )
            envelope = self._one_envelope(result.output)

        # Whatever the verdict, it is a rendered envelope rather than a
        # traceback: the unreachable probe did not escape as an exception.
        assert isinstance(envelope, dict)
        assert "Traceback" not in result.output
