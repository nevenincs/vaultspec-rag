"""Unit tests for the job progress-rate window and completion estimate.

The estimate exists to answer "how much longer", and the only dishonest
answer is a confident one. These tests are mostly about the cases where the
service must decline: too few samples, too short a span, no advance, a step
change that resets the per-unit cost, and a resumed attempt replaying units.
"""

from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING, cast

import pytest

from ..job_models import JobSource
from ..jobs import (
    record_progress,
    record_start,
    reset,
    snapshot,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestProgressRateWindow:
    """The completion estimate declines to guess rather than guessing."""

    @pytest.fixture(autouse=True)
    def _own_status_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Iterator[None]:
        from ..config import reset_config

        monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
        reset_config()
        reset()
        yield
        reset()
        reset_config()

    def _window(self, *samples: tuple[float, int]) -> deque[tuple[float, int]]:
        return deque(samples, maxlen=16)

    def test_one_sample_measures_no_interval(self) -> None:
        from ..jobs import _window_rate

        assert _window_rate(self._window((100.0, 5))) is None

    def test_span_below_the_minimum_is_refused(self) -> None:
        from ..jobs import _window_rate

        # Two samples 10ms apart would report 500/s from a 5-unit advance.
        assert _window_rate(self._window((100.0, 5), (100.01, 10))) is None

    def test_flat_count_over_a_real_span_is_refused(self) -> None:
        from ..jobs import _window_rate

        assert _window_rate(self._window((100.0, 5), (160.0, 5))) is None

    def test_steady_advance_yields_the_arithmetic_rate(self) -> None:
        from ..jobs import _window_rate

        # 90 units across 45 seconds is exactly 2/s.
        rate = _window_rate(self._window((100.0, 10), (145.0, 100)))
        assert rate == pytest.approx(2.0)

    def test_step_change_discards_the_window(self) -> None:
        from ..jobs import _sample_progress, _window_rate

        record: dict[str, object] = {"id": "j1"}
        _sample_progress(
            record, step="chunk", previous_step=None, completed=0, at=100.0
        )
        _sample_progress(
            record, step="chunk", previous_step="chunk", completed=400, at=140.0
        )
        window = cast("deque[tuple[float, int]]", record["progress_window"])
        assert _window_rate(window) == pytest.approx(10.0)

        # Embedding is far slower per unit than chunking; carrying the
        # chunk rate into it would promise a finish that cannot happen.
        _sample_progress(
            record, step="embed", previous_step="chunk", completed=0, at=141.0
        )
        window = cast("deque[tuple[float, int]]", record["progress_window"])
        assert list(window) == [(141.0, 0)]
        assert _window_rate(window) is None

    def test_count_moving_backwards_discards_the_window(self) -> None:
        from ..jobs import _sample_progress, _window_rate

        record: dict[str, object] = {"id": "j1"}
        _sample_progress(
            record, step="embed", previous_step=None, completed=500, at=100.0
        )
        _sample_progress(
            record, step="embed", previous_step="embed", completed=900, at=140.0
        )
        # A resumed attempt replays committed units.
        _sample_progress(
            record, step="embed", previous_step="embed", completed=120, at=180.0
        )
        window = cast("deque[tuple[float, int]]", record["progress_window"])
        assert list(window) == [(180.0, 120)]
        assert _window_rate(window) is None

    def test_sampling_state_never_reaches_a_snapshot(self) -> None:
        # Mutation check: removing the ``item.pop`` in ``jobs.snapshot``
        # makes this fail on the key assertion below, not on an import.
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        record_progress(job_id, "embed", completed=1, total=10)

        entries = snapshot()
        assert entries
        assert all("progress_window" not in entry for entry in entries)

    def test_the_whole_chain_estimates_from_real_progress(self) -> None:
        from ..server._routes_jobs import _job_with_liveness

        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        record_progress(job_id, "embed", completed=0, total=1000)
        # The window must span a real interval before it will answer.
        time.sleep(1.2)
        record_progress(job_id, "embed", completed=600, total=1000)

        record = next(e for e in snapshot() if e["id"] == job_id)
        shaped = _job_with_liveness(record, now=time.time())

        rate = shaped["progress_rate_per_second"]
        remaining = shaped["estimated_remaining_seconds"]
        assert isinstance(rate, float) and rate > 0
        assert isinstance(remaining, float)
        # 400 units left at the measured rate, within timing tolerance.
        assert remaining == pytest.approx(400.0 / rate, rel=0.01)

    def test_waiting_job_reports_no_estimate(self) -> None:
        from ..server._routes_jobs import _job_with_liveness

        record: dict[str, object] = {
            "id": "j1",
            "phase": "running",
            "started_at": 100.0,
            "finished_at": None,
            "progress": {
                "step": "queued",
                "completed": 0,
                "total": 500,
                "last_updated": 140.0,
            },
        }
        shaped = _job_with_liveness(record, now=150.0)
        assert shaped["progress_rate_per_second"] is None
        assert shaped["estimated_remaining_seconds"] is None

    def test_step_without_a_total_reports_no_estimate(self) -> None:
        from ..server._routes_jobs import _job_with_liveness

        record: dict[str, object] = {
            "id": "j1",
            "phase": "running",
            "started_at": 100.0,
            "finished_at": None,
            "progress": {
                "step": "discover",
                "completed": 42,
                "total": None,
                "last_updated": 140.0,
            },
        }
        shaped = _job_with_liveness(record, now=150.0)
        assert shaped["progress_rate_per_second"] is None
        assert shaped["estimated_remaining_seconds"] is None

    def test_finished_job_reports_no_estimate(self) -> None:
        from ..server._routes_jobs import _job_with_liveness

        record: dict[str, object] = {
            "id": "j1",
            "phase": "done",
            "started_at": 100.0,
            "finished_at": 200.0,
            "progress": {
                "step": "embed",
                "completed": 400,
                "total": 1000,
                "last_updated": 190.0,
            },
        }
        shaped = _job_with_liveness(record, now=250.0)
        assert shaped["progress_rate_per_second"] is None
        assert shaped["estimated_remaining_seconds"] is None
