"""Client and job-presentation parity for canonical controller envelopes."""

from __future__ import annotations

import pytest

from ..cli._service_jobs_presentation import render_job_detail
from ..serviceclient._transport import _resolve_admin_call

pytestmark = pytest.mark.unit


def test_watcher_transport_forwards_only_supported_bounds_and_filters() -> None:
    resolved = _resolve_admin_call(
        "get_watcher_state",
        {
            "root": "/work/project",
            "source": "code",
            "state": "ready",
            "limit": 24,
            "ignored": "no",
        },
    )

    assert resolved == (
        "/watcher?root=%2Fwork%2Fproject&source=code&state=ready&limit=24",
        None,
    )


def test_job_detail_labels_embedded_controller_facts_unchanged(
    capsys: pytest.CaptureFixture[str],
) -> None:
    controller = {
        "state": "refused",
        "reason": "full_reindex_required",
        "pending_count": 4,
        "oldest_age_seconds": 11.25,
        "next_decision_at": None,
        "freshness_deadline": 90.0,
        "backpressure": ["storage_unavailable"],
        "measurement": {"storage_available": False},
        "last_transition": {"reason": "full_reindex_required"},
        "remediation": "Request an explicit rebuild.",
    }

    render_job_detail(
        {
            "id": "job-1",
            "operation": "index",
            "source": "code",
            "phase": "running",
            "runtime_seconds": 1.0,
            "controller": controller,
        }
    )

    output = capsys.readouterr().out
    assert "Controller: refused (full_reindex_required)" in output
    assert "Controller pending: 4; oldest age: 11.25 seconds" in output
    assert "Controller backpressure: ['storage_unavailable']" in output
    assert "Controller remediation: Request an explicit rebuild." in output
