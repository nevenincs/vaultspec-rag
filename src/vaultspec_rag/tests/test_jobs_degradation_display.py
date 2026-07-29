"""The CLI renders the service's degradation verdict, never its own verdict.

The stall reading used to be recomputed in the CLI from a local threshold,
which is exactly how the TUI and the service came to disagree about the same
job. The service verdict is now authoritative wherever it is published; the
local heuristic survives only for daemons that predate the field, mirroring
how the completion estimate reads absent-versus-null.

No mocks, patches, or fakes: the real renderer writes to the real console and
the assertions read what it printed.
"""

from __future__ import annotations

import pytest

from ..cli._service_jobs_presentation import (
    degradation_evidence_lines,
    degradation_verdict,
    human_progress,
    render_job_detail,
    stale_progress_label,
)

pytestmark = [pytest.mark.unit]


def _evidence(
    *,
    in_flight: bool = True,
    forward_age: float = 92.0,
    backend_alive: object = True,
) -> dict[str, object]:
    return {
        "forward": {
            "in_flight": in_flight,
            "age_seconds": forward_age,
            "slice_ordinal": 3,
            "items": 64,
            "thread_alive": True,
        },
        "gpu": {
            "available": True,
            "utilization_percent": 100.0,
            "memory_used_mb": 15486.0,
            "memory_total_mb": 16376.0,
        },
        "backend": {
            "alive": backend_alive,
            "latency_seconds": 0.004 if backend_alive is True else None,
            "detail": None if backend_alive is True else "no response within 2.0s",
        },
    }


def _job(
    *,
    degradation: str | None,
    evidence: dict[str, object] | None = None,
    stalled: object = False,
    age: float = 90.0,
) -> dict[str, object]:
    job: dict[str, object] = {
        "id": "aaaaaaaa",
        "source": "vault",
        "phase": "running",
        "started_at": 1_000.0,
        "runtime_seconds": 120.0,
        "last_progress_age_seconds": age,
        "stalled": stalled,
        "progress": {
            "step": "embed + upsert documents",
            "completed": 192,
            "total": 4609,
        },
        "initiator": {"command": "reindex_vault", "project_root": "/w/demo"},
    }
    if degradation is not None:
        job["degradation"] = degradation
        job["degradation_evidence"] = evidence
    return job


class TestVerdictIsAuthoritative:
    def test_a_degraded_verdict_is_rendered_with_its_cause(self) -> None:
        label = stale_progress_label(_job(degradation="degraded", evidence=_evidence()))
        assert label.startswith("degraded: ")
        assert "no progress for" in label
        assert "GPU forward pass running" in label

    def test_a_healthy_verdict_silences_the_local_heuristic(self) -> None:
        # The payload contradicts itself on purpose: the service says healthy
        # while the legacy flag and age scream stalled. The service must win.
        # Mutation check: removing the verdict branch from
        # ``stale_progress_label`` makes this fail on the empty-label
        # assertion below, because the fallback then re-derives a stall from
        # the ``stalled`` flag.
        job = _job(degradation="healthy", evidence=None, stalled=True, age=400.0)
        assert stale_progress_label(job) == ""

    def test_a_stalled_verdict_is_rendered_as_stalled(self) -> None:
        label = stale_progress_label(
            _job(degradation="stalled", evidence=_evidence(), age=320.0)
        )
        assert label.startswith("stalled: ")
        assert "no progress for" in label

    def test_an_older_daemon_keeps_the_fallback_reading(self) -> None:
        # No ``degradation`` key at all: the daemon predates the verdict, and
        # absent is not the same answer as present. The stalled flag, then the
        # local threshold, carry the reading exactly as before.
        job = _job(degradation=None, stalled=True, age=400.0)
        assert degradation_verdict(job) is None
        assert stale_progress_label(job) == "no progress for 6 minutes 40 seconds"
        quiet = _job(degradation=None, stalled=False, age=400.0)
        assert stale_progress_label(quiet) == ""


class TestEvidenceRendering:
    def test_every_finding_is_rendered_verbatim(self) -> None:
        lines = degradation_evidence_lines(
            _job(degradation="degraded", evidence=_evidence())
        )
        assert len(lines) == 3
        encode, gpu, backend = lines
        assert "GPU forward pass running" in encode
        assert "slice 3, 64 items" in encode
        assert "100% busy" in gpu
        assert "answered in" in backend

    def test_an_unanswered_backend_probe_is_named_not_hidden(self) -> None:
        lines = degradation_evidence_lines(
            _job(degradation="degraded", evidence=_evidence(backend_alive=None))
        )
        assert any("no response within 2.0s" in line for line in lines)

    def test_the_detail_view_prints_the_verdict_and_evidence(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        render_job_detail(_job(degradation="degraded", evidence=_evidence()))
        out = capsys.readouterr().out
        assert "Health: degraded" in out
        assert "GPU forward pass running" in out
        assert "Backend: answered in" in out

    def test_a_healthy_job_prints_no_health_section(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        render_job_detail(_job(degradation="healthy", evidence=None))
        out = capsys.readouterr().out
        assert "Health:" not in out


def _cpu_phase_evidence(
    *,
    expected: object = False,
    cpu: dict[str, object] | None = None,
) -> dict[str, object]:
    """Evidence as the service samples it during a CPU-bound phase."""
    forward: dict[str, object] = {
        "in_flight": False,
        "age_seconds": None,
        "slice_ordinal": None,
        "items": None,
        "thread_alive": None,
        "expected": expected,
    }
    evidence: dict[str, object] = {
        "forward": forward,
        "gpu": {
            "available": True,
            "utilization_percent": 2.0,
            "memory_used_mb": 4915.0,
            "memory_total_mb": 16376.0,
        },
        "backend": {"alive": True, "latency_seconds": 0.4, "detail": None},
    }
    if cpu is not None:
        evidence["cpu"] = cpu
    return evidence


class TestPhaseAwareEvidenceRendering:
    def test_a_cpu_phase_names_the_absent_forward_as_expected(self) -> None:
        """The hashing-phase incident line must stop reading as a finding.

        Mutation check: dropping the ``expected is False`` branch from
        ``_encode_evidence_line`` falls back to "no forward pass observed"
        and this fails on the exact-phrase assertion below; restoring the
        branch returns it to green.
        """
        lines = degradation_evidence_lines(
            _job(degradation="degraded", evidence=_cpu_phase_evidence())
        )
        assert "Encode: no forward pass expected in this phase" in lines

    def test_an_unclassified_phase_keeps_the_conservative_reading(self) -> None:
        # ``expected`` null (or absent, from an older daemon): silence stays
        # reportable rather than being suppressed on no information.
        lines = degradation_evidence_lines(
            _job(degradation="degraded", evidence=_cpu_phase_evidence(expected=None))
        )
        assert "Encode: no forward pass observed" in lines

    def test_the_cpu_reading_is_rendered_beside_the_others(self) -> None:
        lines = degradation_evidence_lines(
            _job(
                degradation="degraded",
                evidence=_cpu_phase_evidence(
                    cpu={"available": True, "utilization_percent": 101.3}
                ),
            )
        )
        assert "Process CPU: 101% of one core" in lines

    def test_a_warming_cpu_probe_renders_no_line(self) -> None:
        lines = degradation_evidence_lines(
            _job(
                degradation="degraded",
                evidence=_cpu_phase_evidence(
                    cpu={"available": True, "utilization_percent": None}
                ),
            )
        )
        assert not any(line.startswith("Process CPU:") for line in lines)

    def test_an_unmeasurable_cpu_probe_is_named_not_hidden(self) -> None:
        lines = degradation_evidence_lines(
            _job(
                degradation="degraded",
                evidence=_cpu_phase_evidence(
                    cpu={"available": False, "utilization_percent": None}
                ),
            )
        )
        assert "Process CPU: not measurable from the service process" in lines


def _collapse_evidence(
    *,
    encode: dict[str, object] | None = None,
    rate: dict[str, object] | None = None,
) -> dict[str, object]:
    """Evidence for a run whose throughput collapsed against its own median.

    The recency findings are healthy-looking on purpose: the forward exited
    moments ago and progress is fresh, which is exactly the shape in which
    only the throughput comparison has anything to say.
    """
    evidence = _evidence(in_flight=False, forward_age=2.0)
    if encode is not None:
        evidence["encode"] = encode
    if rate is not None:
        evidence["rate"] = rate
    return evidence


class TestEncodeBudgetRendering:
    def test_the_encode_batch_bounds_are_rendered_from_the_payload(self) -> None:
        lines = degradation_evidence_lines(
            _job(
                degradation="degraded",
                evidence=_collapse_evidence(
                    encode={
                        "token_budget": 16384,
                        "bucket_items": 6,
                        "oom_count": 3,
                    }
                ),
            )
        )
        assert (
            "Encode batch: 16384 tokens per batch, 6 items in the last batch, "
            "3 GPU memory retries" in lines
        )

    def test_a_single_retry_is_not_pluralised(self) -> None:
        lines = degradation_evidence_lines(
            _job(
                degradation="degraded",
                evidence=_collapse_evidence(
                    encode={"token_budget": 8192, "bucket_items": None, "oom_count": 1}
                ),
            )
        )
        assert "Encode batch: 8192 tokens per batch, 1 GPU memory retry" in lines

    def test_a_run_with_no_retries_says_nothing_about_them(self) -> None:
        # A zero is not a finding; naming it would spend the line an operator
        # needs on the numbers that do bound the batch.
        lines = degradation_evidence_lines(
            _job(
                degradation="degraded",
                evidence=_collapse_evidence(
                    encode={"token_budget": 8192, "bucket_items": 24, "oom_count": 0}
                ),
            )
        )
        assert (
            "Encode batch: 8192 tokens per batch, 24 items in the last batch" in lines
        )

    def test_a_job_that_never_encoded_renders_no_budget_line(self) -> None:
        lines = degradation_evidence_lines(
            _job(degradation="degraded", evidence=_collapse_evidence())
        )
        assert not any(line.startswith("Encode batch:") for line in lines)

    def test_the_sub_slice_climb_is_rendered_as_a_fraction(self) -> None:
        """The climb through a slice reads as a fraction, not as a size.

        The forward line above it names the slice's own 512 items, so the
        two numbers have to be told apart on sight.

        Mutation check: rendering only the numerator - dropping the ``of
        {total:g}`` half of the phrase in ``_encode_budget_line`` - makes
        this fail on the ``64 of 512 items encoded`` assertion below, and
        restoring the denominator returns it to green.
        """
        lines = degradation_evidence_lines(
            _job(
                degradation="degraded",
                evidence=_collapse_evidence(
                    encode={
                        "token_budget": 16384,
                        "bucket_items": 6,
                        "items_done": 64,
                        "items_total": 512,
                        "oom_count": 0,
                    }
                ),
            )
        )
        assert (
            "Encode batch: 16384 tokens per batch, 6 items in the last batch, "
            "64 of 512 items encoded" in lines
        )

    def test_a_climb_without_its_denominator_is_not_rendered(self) -> None:
        # A lone completed count is the ambiguity this line exists to avoid:
        # rendered bare it reads as a size, so it is not rendered at all.
        lines = degradation_evidence_lines(
            _job(
                degradation="degraded",
                evidence=_collapse_evidence(
                    encode={
                        "token_budget": 8192,
                        "bucket_items": None,
                        "items_done": 64,
                        "items_total": None,
                        "oom_count": 0,
                    }
                ),
            )
        )
        assert "Encode batch: 8192 tokens per batch" in lines

    def test_an_older_daemon_renders_the_budget_line_unchanged(self) -> None:
        # An encode block from before the pair existed carries neither key,
        # and must render exactly the line it always rendered.
        lines = degradation_evidence_lines(
            _job(
                degradation="degraded",
                evidence=_collapse_evidence(
                    encode={"token_budget": 8192, "bucket_items": 24, "oom_count": 2}
                ),
            )
        )
        assert (
            "Encode batch: 8192 tokens per batch, 24 items in the last batch, "
            "2 GPU memory retries" in lines
        )


class TestThroughputRendering:
    def test_the_collapse_is_rendered_as_the_service_measured_it(self) -> None:
        lines = degradation_evidence_lines(
            _job(
                degradation="degraded",
                evidence=_collapse_evidence(
                    rate={
                        "recent_per_second": 1.9,
                        "median_per_second": 13.3,
                        "ratio": 0.143,
                    }
                ),
            )
        )
        assert (
            "Throughput: 1.9 per second against a 13.3 per second run median "
            "(14% of it)" in lines
        )

    def test_the_row_summary_names_the_collapse_not_the_progress_gap(self) -> None:
        """A fresh progress stamp must not be offered as the cause.

        Mutation check: dropping the throughput part from
        ``_unhealthy_summary`` makes this fail on the ``against a`` assertion
        below, leaving the row claiming a two-second gap explains a degraded
        verdict.
        """
        label = stale_progress_label(
            _job(
                degradation="degraded",
                age=2.0,
                evidence=_collapse_evidence(
                    rate={
                        "recent_per_second": 1.9,
                        "median_per_second": 13.3,
                        "ratio": 0.143,
                    }
                ),
            )
        )
        assert label.startswith("degraded: ")
        assert "1.9 per second against a 13.3 per second run median" in label

    def test_an_unmeasured_baseline_renders_no_throughput_line(self) -> None:
        lines = degradation_evidence_lines(
            _job(
                degradation="degraded",
                evidence=_collapse_evidence(
                    rate={
                        "recent_per_second": 1.9,
                        "median_per_second": None,
                        "ratio": None,
                    }
                ),
            )
        )
        assert not any(line.startswith("Throughput:") for line in lines)


class TestProgressLabels:
    def test_the_code_pipeline_label_names_completed_work(self) -> None:
        # The counter behind "chunk + embed" counts files whose chunks were
        # encoded and durably written, so the label must not claim it counts
        # files being prepared.
        job: dict[str, object] = {
            "source": "code",
            "progress": {"step": "chunk + embed", "completed": 3, "total": 10},
        }
        assert human_progress(job) == "embedding and writing files 3 of 10"
