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
