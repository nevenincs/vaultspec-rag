"""CLI coverage for how a degraded service status explains itself."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, cast

import pytest

from .._operator_commands import _shell_argument
from ..operator_state._service import DegradationReason
from ._cli_helpers import (
    _assert_default_status_summary,
    _features_payload,
    _label_values,
    _live_status_service,
    _plain_lines,
    _status_contract_server,
    app,
    runner,
)

if TYPE_CHECKING:
    from pathlib import Path

    from typer.testing import Result

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


def _failed_record() -> dict[str, object]:
    return {
        "id": _FAILED_JOB_ID,
        "source": "code",
        "error_kind": "other",
        "finished_at": time.time() - _FAILURE_AGE_SECONDS,
    }


def _failing(*records: dict[str, object], degrading: bool = True) -> dict[str, object]:
    """The service's failing-project rollup naming *records*, in order."""
    entries = [record | {"degrading": degrading} for record in records]
    return {
        "failing": {
            "total": len(entries),
            "degrading": len(entries) if degrading else 0,
            "entries": entries,
        }
    }


#: The code the service emits beside each detail these fixtures report. A
#: detail with no entry stands for a newer service's code this build does not
#: know, which must still be rendered.
_CODES = {
    "1 project index run failed: /w/demo (code: other)": "job_failed",
    "1 project index run failed: /w/demo (vault: full_reindex_required)": "job_failed",
    "2 indexing job(s) are stalled": "jobs_stalled",
    "1 indexing job(s) are stalled": "jobs_stalled",
    "1 queued indexing job(s) have nothing to start them": "jobs_undispatched",
    "embedding models are not loaded": "models_not_loaded",
    "the configured vector service is not live": "vector_service_unavailable",
}


def _coded(detail: str) -> dict[str, str]:
    """One degradation entry as the service emits it."""
    return {
        "reason": _CODES.get(detail, "not_a_code_this_build_knows"),
        "detail": detail,
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
        "degradations": [_coded(reason) for reason in reasons or []],
        "models_loaded": True,
        "features": _features_payload(),
        "project_count": 3,
        "uptime_s": 850.0,
        "jobs": {"running": 0, "queued": 0, "stalled": 0} | (jobs or {}),
    }
    payload.update(extra)
    return payload


def _status_against(
    tmp_path: Path,
    health: dict[str, object],
    *args: str,
    jobs: dict[str, object] | None = None,
) -> Result:
    """Run ``server status`` against a service reporting the given health."""
    with _live_status_service(
        tmp_path,
        _status_contract_server(
            tmp_path, health=health, jobs=_jobs_payload() if jobs is None else jobs
        ),
    ):
        return runner.invoke(app, ["server", "status", *args])


def _index_degradation(payload: dict[str, object]) -> list[str]:
    """Render an index payload's degradation as project status does."""
    from ..cli._status_labels import render_degradation

    return render_degradation(payload, header="Degraded because:")


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
                reasons=["1 project index run failed: /w/demo (code: other)"],
                jobs=_failing(_failed_record()),
            ),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "Degraded because:" in lines
        assert "- 1 project index run failed: /w/demo (code: other)" in lines
        assert f"job e8f8ac43, {_FAILURE_AGE_TEXT} ago" in lines
        assert f"vaultspec-rag server logs --job-id {_FAILED_JOB_ID}" in lines
        # The concrete remediation replaces the generic re-run-with-more-rows.
        next_action = lines[lines.index("Next action:") + 1]
        assert next_action == f"vaultspec-rag server logs --job-id {_FAILED_JOB_ID}"
        assert "--verbose" not in result.output

    def test_a_refused_incremental_names_the_rebuild_of_its_own_project(
        self, tmp_path: Path
    ) -> None:
        project = tmp_path / "other project"
        refused = _failed_record() | {
            "source": "vault",
            "project_root": str(project),
            "error_kind": "full_reindex_required",
        }
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=[
                    "1 project index run failed: /w/demo (vault: full_reindex_required)"
                ],
                jobs=_failing(refused),
            ),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        # The job's logs only restate the refusal; the rebuild is the remedy.
        # The service serves every project, so the command names the one the
        # refused job belongs to rather than whichever the operator stands in.
        next_action = lines[lines.index("Next action:") + 1]
        assert next_action == (
            f"vaultspec-rag --target {_shell_argument(str(project))} "
            "index --rebuild --type vault"
        )
        assert f"vaultspec-rag server logs --job-id {_FAILED_JOB_ID}" not in lines

    def test_a_refusal_with_no_known_project_points_at_its_logs(
        self, tmp_path: Path
    ) -> None:
        refused = _failed_record() | {
            "source": "vault",
            "error_kind": "full_reindex_required",
        }
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=[
                    "1 project index run failed: /w/demo (vault: full_reindex_required)"
                ],
                jobs=_failing(refused),
            ),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        # An unscoped rebuild would act on the operator's own project, which
        # need not be the one refused.
        next_action = lines[lines.index("Next action:") + 1]
        assert next_action == f"vaultspec-rag server logs --job-id {_FAILED_JOB_ID}"

    def test_failed_job_count_carries_the_failed_jobs_view(
        self, tmp_path: Path
    ) -> None:
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=["1 project index run failed: /w/demo (code: other)"],
                jobs=_failing(_failed_record()),
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

    def test_undispatched_jobs_point_at_the_unfiltered_jobs_view(
        self, tmp_path: Path
    ) -> None:
        """Queued work has no state filter, so the command must carry none.

        Mutation it catches: pointing the finding at the default active view,
        which lists running work only and hides the queued job it names.
        """
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=["1 queued indexing job(s) have nothing to start them"],
                jobs={"undispatched": 1},
            ),
            jobs=_jobs_payload(failed=0),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "- 1 queued indexing job(s) have nothing to start them" in lines
        assert "the service dispatches queued work again when it restarts" in lines
        assert lines[lines.index("Next action:") + 1] == "vaultspec-rag server jobs"

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

    def test_dead_vector_service_names_the_stop_and_the_start(
        self, tmp_path: Path
    ) -> None:
        """A dead server needs a new service, and the refusal is its cause.

        The service restarts a dead server once on its own, so one still
        reported dead is past that. The remedy is a stop and then a start;
        the stop is the command offered to run, and the sentence above it
        names both, with why the restart started nothing when it did not.

        Mutation check: with the finding pointing at an inspection verb
        again, the next action is that verb and the last assertion fails;
        with the refusal dropped from the finding, the ``cannot be read``
        assertion fails. Restoring each passes.
        """
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=["the configured vector service is not live"],
                qdrant={
                    "mode": "server",
                    "alive": False,
                    "port": 6333,
                    "restart_refusal": "the binary cannot be read",
                },
            ),
            jobs=_jobs_payload(failed=0),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "- the configured vector service is not live" in lines
        assert (
            "its restart started nothing: the binary cannot be read; run "
            "`vaultspec-rag server stop`, then `vaultspec-rag server start`"
        ) in " ".join(lines)
        assert lines[lines.index("Next action:") + 1] == "vaultspec-rag server stop"

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
                reasons=["1 project index run failed: /w/demo (code: other)"],
                jobs=_failing(_failed_record()),
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
                reasons=["1 project index run failed: /w/demo (code: other)"],
                jobs=_failing(_failed_record()),
            ),
            "--json",
        )

        assert result.exit_code == 0, result.output
        envelope = cast("dict[str, object]", json.loads(result.stdout))
        data = cast("dict[str, object]", envelope["data"])
        operational = cast("dict[str, object]", data["operational"])
        findings = cast("list[dict[str, str]]", operational["degraded"])
        assert [finding["cause"] for finding in findings] == [
            "1 project index run failed: /w/demo (code: other)"
        ]
        assert findings[0]["family"] == DegradationReason.JOB_FAILED
        assert findings[0]["command"] == (
            f"vaultspec-rag server logs --job-id {_FAILED_JOB_ID}"
        )
        failure = cast("dict[str, object]", operational["failure"])
        assert failure["command"] == "vaultspec-rag server jobs --failed"


class TestFailingProjectIndexes:
    """The CLI renders the service's failing list and derives nothing.

    MUTATION PROOF, one uninterrupted sequence each:

    - Dropping the ``degrading is True`` filter in ``_failed_job_finding``
      fails ``test_a_listed_failure_past_the_window_explains_no_degradation``
      on its ``not in lines`` assertion: the stale entry is promoted to a
      cause beside a reason it does not explain.
    - Reading the first listed entry instead of the first degrading one fails
      ``test_the_finding_names_the_first_degrading_entry_and_counts_the_rest``
      on its job-id command assertion.

    Restoring each returns the class to green.
    """

    def test_the_finding_names_the_first_degrading_entry_and_counts_the_rest(
        self, tmp_path: Path
    ) -> None:
        stale = _failed_record() | {"id": "0" * 32, "project_root": "/w/old"}
        live = _failed_record() | {"project_root": "/w/demo"}
        other = _failed_record() | {"id": "1" * 32, "project_root": "/w/next"}
        payload = _health_payload(
            reasons=["1 project index run failed: /w/demo (code: other)"],
            jobs={
                "failing": {
                    "total": 3,
                    "degrading": 2,
                    "entries": [
                        stale | {"degrading": False},
                        live | {"degrading": True},
                        other | {"degrading": True},
                    ],
                }
            },
        )
        result = _status_against(tmp_path, payload)

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert f"vaultspec-rag server logs --job-id {_FAILED_JOB_ID}" in lines
        assert (
            f"job e8f8ac43, {_FAILURE_AGE_TEXT} ago in /w/demo; 1 more failing"
        ) in lines

    def test_a_listed_failure_past_the_window_explains_no_degradation(
        self, tmp_path: Path
    ) -> None:
        """A stale entry is history even while something unexplained degrades."""
        result = _status_against(
            tmp_path,
            _health_payload(
                reasons=["the storage volume is nearly full"],
                jobs=_failing(_failed_record(), degrading=False),
            ),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "- the storage volume is nearly full" in lines
        assert "- a project's index run failed: other" not in lines
        labels = _label_values(result.output)
        assert (
            labels["Last failure"] == f"job e8f8ac43 (other), {_FAILURE_AGE_TEXT} ago"
        )


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
        instead of recording it (the unknown-code branch of the finding
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
                jobs=_failing(_failed_record()),
            ),
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert "- the most recent index run did not complete" in lines
        # Unclaimed by any reason, the proven signal still reports itself.
        assert "- a project's index run failed: other" in lines
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
        lines = _index_degradation(
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

    def test_a_refused_incremental_names_the_rebuild_for_its_source(self) -> None:
        lines = _index_degradation(
            {
                "degraded_reasons": [
                    {
                        "source": "vault",
                        "job_id": _FAILED_JOB_ID,
                        "reason": "failed",
                        "error_kind": "full_reindex_required",
                    },
                ]
            }
        )

        assert lines == [
            "Degraded because:",
            "  - the vault index job failed: full_reindex_required",
            "    job e8f8ac43",
            "    vaultspec-rag index --rebuild --type vault",
        ]

    def test_unphrasable_index_record_is_flattened_not_repred(self) -> None:
        lines = _index_degradation(
            {"degraded_reasons": [{"source": "code", "detail": "disk full"}]}
        )

        assert lines == ["Degraded because:", "  - source: code, detail: disk full"]

    def test_index_status_without_degradation_says_nothing(self) -> None:
        assert _index_degradation({"degraded_reasons": []}) == []
        assert _index_degradation({}) == []

    def test_compact_shape_lists_causes_without_remediation(self) -> None:
        from ..cli._status_labels import render_degradation

        payload = _health_payload(
            reasons=[
                "embedding models are not loaded",
                "1 project index run failed: /w/demo (code: other)",
            ],
            models_loaded=False,
            jobs=_failing(_failed_record()),
        )

        assert render_degradation(
            payload,
            header="Serving, with warnings:",
            remediation=False,
        ) == [
            "Serving, with warnings:",
            "  - embedding models are not loaded",
            "  - 1 project index run failed: /w/demo (code: other)",
        ]

    def test_port_qualifier_reaches_every_rendered_command(self) -> None:
        from ..cli._status_labels import render_degradation

        lines = render_degradation(
            _health_payload(
                reasons=["1 project index run failed: /w/demo (code: other)"],
                jobs=_failing(_failed_record()),
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
        with _live_status_service(tmp_path, _status_contract_server(tmp_path)) as port:
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
                jobs=_failing(_failed_record(), degrading=False),
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

    def test_a_historical_failure_is_not_a_cause_of_a_live_degradation(
        self, tmp_path: Path
    ) -> None:
        """A degraded service lists only what the service said degraded it.

        The renderer derives remediation from structured signals, and a failed
        job leaves one behind forever. Promoting that signal to a cause whenever
        anything else degrades the service would put a failure from a previous
        daemon generation under "Degraded because" - which is exactly the verdict
        the service withholds by bounding job-history degradation to the current
        generation. Observed live before this was fixed: the service reported one
        reason and the status view printed two.

        The failure is not suppressed, only relocated: it still appears beside
        the failed count with the command that inspects it.
        """
        result = _status_against(
            tmp_path,
            _health_payload(
                status="degraded",
                reasons=["1 indexing job(s) are stalled"],
                jobs={"stalled": 1} | _failing(_failed_record(), degrading=False),
            ),
        )

        assert result.exit_code == 0, result.output
        degraded = [
            line for line in _plain_lines(result.output) if line.startswith("- ")
        ]
        assert degraded == ["- 1 indexing job(s) are stalled"], result.output
        labels = _label_values(result.output)
        assert (
            labels["Last failure"] == f"job e8f8ac43 (other), {_FAILURE_AGE_TEXT} ago"
        )


class TestDegradedFamilyRegistryHasOneEntryPerBehaviour:
    """One remediation per behaviour, and every entry reachable.

    A merge that lands two implementations of one signal is invisible here
    otherwise: Python keeps the last definition, the shadowed one becomes dead
    code, and the linter says nothing. Both duplicates then sit in the registry
    pointing at whichever function survived.
    """

    def test_every_degradation_code_has_a_remedy_or_is_named_remedyless(
        self,
    ) -> None:
        """A code with no evidence builder reaches the operator with no command.

        Mutation it catches: removing a code's entry from the evidence registry,
        which leaves that degradation reported with nothing to run.
        """
        from ..cli._status_labels import _EVIDENCE
        from ..operator_state._service import DegradationReason

        remedyless = set(DegradationReason) - set(_EVIDENCE)

        assert remedyless == {DegradationReason.JOBS_DEGRADED}

    def test_no_finding_function_is_registered_twice(self) -> None:
        """Two codes on one function means one behaviour grew two names.

        Mutation it catches: registering a second code against an existing
        finding, which is what a shadowed duplicate definition produces - both
        registry entries bind to the surviving function.
        """
        from ..cli._status_labels import _EVIDENCE

        names = [
            getattr(finding, "__name__", repr(finding))
            for finding in _EVIDENCE.values()
        ]

        assert len(names) == len(set(names)), f"duplicate findings: {names}"

    def test_the_index_family_is_not_a_service_code(self) -> None:
        """A per-domain index record must not be filtered as a service code.

        Mutation it catches: renaming the index family to a degradation code's
        value, which would merge an index problem into a service problem for
        every caller that filters findings by family.
        """
        from ..cli._status_labels import DOMAIN_INDEX_FAMILY
        from ..operator_state._service import DegradationReason

        assert DOMAIN_INDEX_FAMILY not in {code.value for code in DegradationReason}
