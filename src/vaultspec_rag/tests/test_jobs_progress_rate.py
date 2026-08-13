"""Unit tests for the job progress-rate window and completion estimate.

The estimate exists to answer "how much longer", and the only dishonest
answer is a confident one. These tests are mostly about the cases where the
service must decline: too few samples, too short a span, no advance, a step
change that resets the per-unit cost, and a resumed attempt replaying units.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from .._job_progress import record_progress
from ..job_models import JobSource
from ..jobs import record_start, reset, snapshot

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@dataclass(frozen=True, slots=True)
class _Cadence:
    """One replayed reporting cadence: a step advancing at a fixed rate."""

    step: str
    advances_per_second: float
    count: int
    start_at: float


class TestProgressRateWindow:
    """The completion estimate declines to guess rather than guessing."""

    @pytest.fixture(autouse=True)
    def _own_status_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Iterator[None]:
        from ..config._settings import reset_config

        monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
        reset_config()
        reset()
        yield
        reset()
        reset_config()

    def _window(self, *samples: tuple[float, int]) -> deque[tuple[float, int]]:
        return deque(samples, maxlen=16)

    def test_one_sample_measures_no_interval(self) -> None:
        from .._job_progress import _window_rate

        assert _window_rate(self._window((100.0, 5))) is None

    def test_span_below_the_minimum_is_refused(self) -> None:
        from .._job_progress import _window_rate

        # Two samples 10ms apart would report 500/s from a 5-unit advance.
        assert _window_rate(self._window((100.0, 5), (100.01, 10))) is None

    def test_flat_count_over_a_real_span_is_refused(self) -> None:
        from .._job_progress import _window_rate

        assert _window_rate(self._window((100.0, 5), (160.0, 5))) is None

    def test_steady_advance_yields_the_arithmetic_rate(self) -> None:
        from .._job_progress import _window_rate

        # 90 units across 45 seconds is exactly 2/s.
        rate = _window_rate(self._window((100.0, 10), (145.0, 100)))
        assert rate == pytest.approx(2.0)

    def test_step_change_discards_the_window(self) -> None:
        from .._job_progress import _sample_progress, _window_rate

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
        from .._job_progress import _sample_progress, _window_rate

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

        # Reported at injected moments rather than slept out. The estimate is
        # a count divided by an interval, so an interval read from the host's
        # clock measures the host: the published projection is rounded to a
        # tenth of a second, and a fast host's projection is small enough
        # that the rounding alone exceeds any relative tolerance worth
        # asserting. Injected, the span is exactly 3s - past the window's
        # minimum - and 600 units across it is exactly 200/s.
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        record_progress(job_id, "embed", completed=0, total=1000, now=0.0)
        record_progress(job_id, "embed", completed=600, total=1000, now=3.0)

        record = next(e for e in snapshot() if e["id"] == job_id)
        shaped = _job_with_liveness(record, now=3.0)

        rate = shaped["progress_rate_per_second"]
        remaining = shaped["estimated_remaining_seconds"]
        assert isinstance(rate, float) and rate > 0
        assert isinstance(remaining, float)
        assert rate == pytest.approx(200.0)
        # 400 units left at 200/s is 2s, and both sides land on the published
        # tenth exactly, so no tolerance is owed to a clock the test controls.
        assert remaining == pytest.approx(400.0 / rate)

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

    def test_unsampled_job_reports_no_estimate(self) -> None:
        from ..server._routes_jobs import _job_with_liveness

        # No sampling window exists for this id, so there is no measurement
        # to report - neither a rate nor a projection.
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


# Measured against this tree: chunk production reports once per file and
# emits ~390 advances/second (median inter-advance gap 1.8ms) over the 483
# source files, because the producer chunks far faster than the GPU drains.
# A burst ends when the segment queue fills and the producer blocks on the
# GPU draining it, which measures a few tenths of a second.
# These are the numbers the replays below run at.
_PRODUCTION_ADVANCES_PER_SECOND = 390.0
_PRODUCTION_FILE_COUNT = 483
_PRODUCTION_QUEUE_BLOCK_SECONDS = 0.3


class TestRealisticProgressCadence:
    """The estimate must survive the cadence real indexing actually emits.

    A window bounded only by sample count holds ~40ms of history at the
    measured rate, which can never satisfy the one-second span guard. The
    result is an estimator that declines in every real run - a defect, not
    honesty. These replays drive the production functions at the measured
    cadence and assert an answer arrives.
    """

    @pytest.fixture(autouse=True)
    def _own_status_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Iterator[None]:
        from ..config._settings import reset_config

        monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
        reset_config()
        reset()
        yield
        reset()
        reset_config()

    def _replay(
        self,
        record: dict[str, object],
        cadence: _Cadence,
        *,
        first_completed: int = 0,
    ) -> float:
        """Drive ``_sample_progress`` at a fixed cadence; return the last time."""
        from .._job_progress import _sample_progress

        step = cadence.step
        count = cadence.count
        start_at = cadence.start_at
        interval = 1.0 / cadence.advances_per_second
        at = start_at
        _sample_progress(
            record,
            step=step,
            previous_step=record.get("_replay_step"),
            completed=first_completed,
            at=at,
        )
        record["_replay_step"] = step
        for offset in range(1, count + 1):
            at = start_at + offset * interval
            _sample_progress(
                record,
                step=step,
                previous_step=step,
                completed=first_completed + offset,
                at=at,
            )
        return at

    def _window(self, record: dict[str, object]) -> deque[tuple[float, int]]:
        return cast("deque[tuple[float, int]]", record["progress_window"])

    def test_per_file_chunk_cadence_still_yields_a_rate(self) -> None:
        from .._job_progress import _window_rate

        # Mutation check: making ``_sample_progress`` append every report
        # unconditionally (dropping the coalescing) makes this fail on the
        # ``rate is not None`` assertion below, not on an import - the
        # 16-sample window then spans 0.039s and the span guard refuses.
        record: dict[str, object] = {"id": "j1"}
        self._replay(
            record,
            _Cadence(
                step="chunk + embed",
                advances_per_second=_PRODUCTION_ADVANCES_PER_SECOND,
                count=_PRODUCTION_FILE_COUNT,
                start_at=1000.0,
            ),
        )
        rate = _window_rate(self._window(record))
        assert rate is not None
        assert rate == pytest.approx(_PRODUCTION_ADVANCES_PER_SECOND, rel=0.05)

    def test_the_window_stays_bounded_under_a_fast_step(self) -> None:
        record: dict[str, object] = {"id": "j1"}
        self._replay(
            record,
            _Cadence(
                step="chunk + embed",
                advances_per_second=_PRODUCTION_ADVANCES_PER_SECOND,
                count=_PRODUCTION_FILE_COUNT,
                start_at=1000.0,
            ),
        )
        window = self._window(record)
        # Coalescing must bound memory, not grow one sample per report.
        assert window.maxlen is not None
        assert len(window) <= window.maxlen

    def test_the_rate_tracks_a_slowdown_rather_than_the_step_average(self) -> None:
        from .._job_progress import _window_rate

        # Mutation check: comparing the coalescing interval against
        # ``samples[-1]`` instead of ``samples[-2]`` holds the oldest sample
        # forever, so the window becomes a whole-step average and this fails
        # on the ``rate < 50`` assertion below.
        record: dict[str, object] = {"id": "j1"}
        last_at = self._replay(
            record,
            _Cadence(
                step="chunk + embed",
                advances_per_second=_PRODUCTION_ADVANCES_PER_SECOND,
                count=780,
                start_at=1000.0,
            ),
        )
        # The GPU consumer fills its queue and the producer drops to the
        # drain rate. An operator watching now needs the current throughput.
        self._replay(
            record,
            _Cadence(
                step="chunk + embed",
                advances_per_second=10.0,
                count=40,
                start_at=last_at,
            ),
            first_completed=781,
        )
        rate = _window_rate(self._window(record))
        assert rate is not None
        # The whole-step average is ~135/s; recent throughput is ~10/s.
        assert rate < 50.0

    def test_the_whole_chain_answers_at_production_cadence(self) -> None:
        from ..server._routes_jobs import _job_with_liveness

        # The whole chain, in the shape a real run emits: the producer chunks
        # a burst of files at full speed, blocks on the full segment queue
        # while the GPU drains it, then bursts again. One burst alone fills a
        # 16-sample window in 41ms, which is precisely why a count-bounded
        # window can never answer here.
        #
        # The cadence is replayed at injected moments rather than slept out.
        # Slept out, what the window ends up spanning is the loop's own
        # overshoot rather than the cadence: the trailing block lands after
        # the last report, so a host that got through one burst fewer left the
        # window spanning 0.92s, the span guard rightly refused, and the test
        # failed on how fast the host was.
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        record_progress(job_id, "chunk + embed", 0, _PRODUCTION_FILE_COUNT, now=0.0)
        interval = 1.0 / _PRODUCTION_ADVANCES_PER_SECOND
        at = 0.0
        last_report_at = 0.0
        units = 0
        for _burst in range(6):
            for _advance in range(16):
                units += 1
                record_progress(
                    job_id,
                    "chunk + embed",
                    units,
                    _PRODUCTION_FILE_COUNT,
                    now=at,
                )
                last_report_at = at
                at += interval
            at += _PRODUCTION_QUEUE_BLOCK_SECONDS

        record = next(e for e in snapshot() if e["id"] == job_id)
        shaped = _job_with_liveness(record, now=at)
        rate = shaped["progress_rate_per_second"]
        remaining = shaped["estimated_remaining_seconds"]
        assert isinstance(rate, float) and rate > 0
        assert isinstance(remaining, float) and remaining > 0
        # The window spans the whole replay, so the rate is every unit over
        # every second of it - the property the overshoot above destroyed.
        # Published to three decimals, which is all the slack this needs.
        assert rate == pytest.approx(units / last_report_at, rel=1e-4)
        # The projection is published to a tenth of a second; that quantum is
        # the only slack left once the clock is the test's to choose.
        assert remaining == pytest.approx(
            (_PRODUCTION_FILE_COUNT - units) / rate, abs=0.1
        )

    def test_a_step_without_a_total_reports_a_rate_and_no_estimate(self) -> None:
        from ..server._routes_jobs import _job_with_liveness

        # Document embedding publishes a count with no total. Throughput is
        # a measurement and is reported; there is no completion point to
        # project onto, so the remaining time stays unknown.
        job_id = record_start(JobSource.DOCUMENT, "tool", command="reindex_documents")
        record_progress(job_id, "embed + upsert document chunks", 0, None, now=0.0)
        record_progress(job_id, "embed + upsert document chunks", 600, None, now=3.0)

        record = next(e for e in snapshot() if e["id"] == job_id)
        shaped = _job_with_liveness(record, now=3.0)
        assert isinstance(shaped["progress_rate_per_second"], float)
        assert shaped["progress_rate_per_second"] > 0
        assert shaped["progress_rate_per_second"] == pytest.approx(200.0)
        assert shaped["estimated_remaining_seconds"] is None
