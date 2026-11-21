"""Admission waits and the bounded job wait, end to end over real HTTP.

A real job manager holds the encode slot with one attempt and queues more
behind it; a real server answers the routes over loopback; the CLI and the
transport call it exactly as an operator does.

MUTATION PROOF, each run in one uninterrupted sequence:

- Moving the ``waiting`` filter after pagination (cutting the page, then
  filtering it) fails
  ``test_the_waiting_filter_runs_before_the_page_is_cut`` on its
  ``working`` assertion: the page holds the newest waiter, so the filtered
  page comes back empty.
- Letting ``server job wait`` exit 0 when the service answers
  ``reached: false`` fails ``test_an_expired_wait_exits_one_with_one_envelope``
  on its exit-code assertion.
- Emitting a second envelope on the invalid-input path fails
  ``test_invalid_wait_input_exits_two_with_one_envelope`` on its
  one-line assertion.

Restoring each returns the module to green.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from ... import jobs as _jobs
from ...cli import app
from ...job_models import JobSource
from ...jobs import get_job_manager
from ...serviceclient._transport import (
    _try_http_admin,
    _try_http_get_job,
    _try_http_wait_job,
)
from .._admission_queue import EncodeQueue
from .._state_fixtures import reset_limiters
from ._service_jobs_support import _DEAD_PORT, _canonical_resilience_server

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

runner = CliRunner()

pytestmark = [pytest.mark.unit]

_UNKNOWN_JOB = "0badc0de-0000-4000-8000-0000000000ff"


class _Served:
    """A held encode slot, two waiters, and the server that reports them."""

    def __init__(self, queue: EncodeQueue, port: int, token: str) -> None:
        self.queue = queue
        self.port = port
        self.token = token
        self.holder, self.first, self.second = queue.ids

    def get(self, job_id: str) -> dict[str, object]:
        result = _try_http_get_job(job_id, self.port, timeout=5.0)
        assert result is not None
        assert result["ok"] is True, result
        return cast("dict[str, object]", result["job"])

    def jobs(self, **filters: object) -> dict[str, object]:
        result = _try_http_admin("get_jobs", dict(filters), self.port)
        assert result is not None
        return result

    def wait(self, job_id: str, *, until: str, seconds: float) -> dict[str, object]:
        result = _try_http_wait_job(
            job_id, self.port, until=until, wait_seconds=seconds
        )
        assert result is not None
        return result

    def cli(self, *args: str) -> tuple[int, str]:
        invoked = runner.invoke(app, ["server", "job", "wait", *args])
        return invoked.exit_code, invoked.stdout


def _one_envelope(stdout: str) -> dict[str, object]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert len(lines) == 1, stdout
    envelope = json.loads(lines[0])
    assert isinstance(envelope, dict)
    return cast("dict[str, object]", envelope)


def _ids(page: dict[str, object]) -> list[str]:
    jobs = cast("list[dict[str, object]]", page["jobs"])
    return [str(job["id"]) for job in jobs]


@pytest.fixture(name="served")
async def _served(tmp_path: Path) -> AsyncIterator[_Served]:
    reset_limiters()
    with _canonical_resilience_server(tmp_path) as (port, token):
        queue = EncodeQueue(waiters=2, manager=get_job_manager())
        try:
            await queue.start()
            yield _Served(queue, port, token)
        finally:
            await queue.close()
    reset_limiters()


async def test_waiters_report_the_service_wait_verdict(served: _Served) -> None:
    holder = await asyncio.to_thread(served.get, served.holder)
    first = await asyncio.to_thread(served.get, served.first)
    second = await asyncio.to_thread(served.get, served.second)

    assert holder["state"] == "running"
    assert holder["phase"] == "running"
    assert holder["waiting_on"] is None
    assert holder["queue_position"] is None
    for job, position in ((first, 1), (second, 2)):
        assert job["state"] == "running"
        assert job["phase"] == "awaiting_admission"
        assert job["waiting_on"] == "admission"
        assert job["admission_slot"] == "encode"
        assert job["queue_position"] == position


async def test_the_waiting_filter_runs_before_the_page_is_cut(
    served: _Served,
) -> None:
    unfiltered = await asyncio.to_thread(served.jobs, limit=1)
    # Precondition: the one-job page is a waiter, so a filter applied after the
    # cut could not find the working job.
    assert _ids(unfiltered)[0] in {served.first, served.second}

    working = await asyncio.to_thread(
        served.jobs, limit=1, state="running", waiting=False
    )
    waiting = await asyncio.to_thread(
        served.jobs, limit=1, state="running", waiting=True
    )

    assert _ids(working) == [served.holder]
    assert working["matched"] == 1
    assert len(_ids(waiting)) == 1
    assert waiting["matched"] == 2
    summary = cast("dict[str, object]", waiting["summary"])
    assert summary["running"] == 3
    assert summary["working"] == 1
    assert summary["waiting"] == 2
    assert summary["awaiting_admission"] == 2


@pytest.mark.usefixtures("served")
async def test_the_health_rollup_counts_waiters_from_the_summary() -> None:
    from ...server._lifespan import _jobs_health

    rollup, _degradations = _jobs_health(now=time.time())

    assert rollup["running"] == 3
    assert rollup["working"] == 1
    assert rollup["waiting"] == 2
    assert rollup["awaiting_admission"] == 2


async def test_the_wait_is_bounded_and_answers_on_each_condition(
    served: _Served,
) -> None:
    started = time.monotonic()
    expired = await asyncio.to_thread(
        served.wait, served.first, until="admitted", seconds=0.3
    )
    assert expired["reached"] is False
    assert expired["until"] == "admitted"
    assert cast("float", expired["waited_seconds"]) >= 0.3
    assert time.monotonic() - started < 5.0
    assert cast("dict[str, object]", expired["job"])["phase"] == "awaiting_admission"

    already = await asyncio.to_thread(
        served.wait, served.holder, until="admitted", seconds=10.0
    )
    assert already["reached"] is True
    assert cast("float", already["waited_seconds"]) < 5.0

    pending = asyncio.create_task(
        asyncio.to_thread(served.wait, served.second, until="finished", seconds=30.0)
    )
    await asyncio.sleep(0.2)
    assert not pending.done()
    served.queue.release.set()
    finished = await pending
    assert finished["reached"] is True
    assert cast("dict[str, object]", finished["job"])["state"] == "succeeded"


async def test_the_wait_route_refuses_bad_requests(served: _Served) -> None:
    unknown = await asyncio.to_thread(
        served.wait, _UNKNOWN_JOB, until="finished", seconds=1.0
    )
    assert unknown["ok"] is False
    assert unknown["error"] == "job_not_found"

    bad_until = await asyncio.to_thread(
        served.wait, served.first, until="started", seconds=1.0
    )
    assert bad_until["ok"] is False
    assert bad_until["error"] == "invalid_wait"

    bad_timeout = await asyncio.to_thread(
        served.wait, served.first, until="finished", seconds=-1.0
    )
    assert bad_timeout["ok"] is False
    assert bad_timeout["error"] == "invalid_wait"


async def test_the_wait_route_requires_the_service_token(served: _Served) -> None:
    def status_without_token() -> int:
        url = f"http://127.0.0.1:{served.port}/jobs/{served.first}/wait"
        try:
            with urllib.request.urlopen(url, timeout=5.0) as response:
                return int(response.status)
        except urllib.error.HTTPError as denied:
            return denied.code

    assert await asyncio.to_thread(status_without_token) == 401


async def test_a_record_no_manager_owns_is_answered_from_its_snapshot(
    served: _Served,
) -> None:
    running = _jobs.record_start(JobSource.CODE, "watcher")
    started = time.monotonic()
    unfinished = await asyncio.to_thread(
        served.wait, running, until="finished", seconds=30.0
    )
    # Answered at once: the manager has nothing to wake it for this record.
    assert unfinished["reached"] is False
    assert unfinished["waited_seconds"] == 0.0
    assert time.monotonic() - started < 5.0

    _jobs.record_finish(running, result="done")
    finished = await asyncio.to_thread(
        served.wait, running, until="finished", seconds=30.0
    )
    assert finished["reached"] is True


async def test_an_expired_wait_exits_one_with_one_envelope(
    served: _Served,
) -> None:
    code, stdout = await asyncio.to_thread(
        served.cli,
        served.first,
        "--until",
        "admitted",
        "--timeout",
        "0.3",
        "--port",
        str(served.port),
        "--json",
    )

    assert code == 1
    envelope = _one_envelope(stdout)
    assert envelope["ok"] is False
    assert envelope["command"] == "server.job.wait"
    assert envelope["error"] == "wait_timeout"
    data = cast("dict[str, object]", envelope["data"])
    assert data["reached"] is False
    assert data["until"] == "admitted"
    assert cast("dict[str, object]", data["job"])["phase"] == "awaiting_admission"

    human_code, human = await asyncio.to_thread(
        served.cli,
        served.first[:8],
        "--until",
        "admitted",
        "--timeout",
        "0.3",
        "--port",
        str(served.port),
    )
    assert human_code == 1
    assert "Code: wait_timeout" in human
    assert "awaiting_admission" in human


async def test_a_reached_wait_exits_zero_with_one_envelope(
    served: _Served,
) -> None:
    code, stdout = await asyncio.to_thread(
        served.cli,
        served.holder,
        "--until",
        "admitted",
        "--port",
        str(served.port),
        "--json",
    )

    assert code == 0
    envelope = _one_envelope(stdout)
    assert envelope["ok"] is True
    assert envelope["command"] == "server.job.wait"
    data = cast("dict[str, object]", envelope["data"])
    assert data["status"] == "ok"
    assert data["reached"] is True
    assert cast("dict[str, object]", data["job"])["id"] == served.holder

    human_code, human = await asyncio.to_thread(
        served.cli,
        served.holder[:8],
        "--until",
        "admitted",
        "--port",
        str(served.port),
    )
    assert human_code == 0
    assert f"Job {served.holder} is admitted." in human


async def test_a_finished_job_satisfies_a_finish_wait_at_once(
    served: _Served,
) -> None:
    served.queue.release.set()
    code, stdout = await asyncio.to_thread(
        served.cli,
        served.second,
        "--timeout",
        "30",
        "--port",
        str(served.port),
        "--json",
    )

    assert code == 0
    data = cast("dict[str, object]", _one_envelope(stdout)["data"])
    assert data["until"] == "finished"
    assert cast("dict[str, object]", data["job"])["state"] == "succeeded"


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (["--until", "started"], "invalid_wait"),
        (["--timeout", "-1"], "invalid_wait"),
        (["--timeout", "nan"], "invalid_wait"),
    ],
)
async def test_invalid_wait_input_exits_two_with_one_envelope(
    served: _Served, args: list[str], error: str
) -> None:
    code, stdout = await asyncio.to_thread(
        served.cli, served.first, *args, "--port", str(served.port), "--json"
    )

    assert code == 2
    envelope = _one_envelope(stdout)
    assert envelope["ok"] is False
    assert envelope["error"] == error


async def test_an_unknown_job_exits_one_with_one_envelope(
    served: _Served,
) -> None:
    code, stdout = await asyncio.to_thread(
        served.cli, _UNKNOWN_JOB, "--port", str(served.port), "--json"
    )

    assert code == 1
    envelope = _one_envelope(stdout)
    assert envelope["ok"] is False
    assert envelope["error"] == "job_not_found"


def test_a_stopped_service_exits_three_with_one_envelope() -> None:
    result = runner.invoke(
        app,
        ["server", "job", "wait", _UNKNOWN_JOB, "--port", _DEAD_PORT, "--json"],
    )

    assert result.exit_code == 3
    envelope = _one_envelope(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"] == "service_not_running"
