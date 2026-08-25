"""The real-service harness the search-diagnostics scenarios share.

Every diagnostics scenario talks to one live service the same way: post a
search on the wire and read the whole response, poll a job by exact id,
pull the correlated log line back out of the structured log route, and -
when something fails - gather bounded evidence from health, jobs, and
metrics so the failure names the state of the service rather than only
the assertion that tripped.

That harness lives here. The scenario-specific probes and assertions stay
with the behaviour that drives them.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from ...serviceclient._transport import _do_http_call

if TYPE_CHECKING:
    from http.client import HTTPResponse
    from pathlib import Path

__all__ = [
    "RawSearchPayloads",
    "RawSearchResponse",
    "SearchProbeContext",
    "assert_empty_search_phase_timing",
    "assert_request_id",
    "bounded_failure_evidence",
    "exact_job_snapshot",
    "live_service_token",
    "raw_search",
    "search_with_failure_evidence",
    "submit_clean_vault_rebuild",
    "wait_for_running_job",
    "wait_for_search_log_line",
    "wait_for_succeeded_job",
]

type RawSearchResponse = tuple[int, dict[str, str], dict[str, object]]
type RawSearchPayloads = tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]


@dataclass(frozen=True, slots=True)
class SearchProbeContext:
    """One service job and its latest truth for concurrent probe failures."""

    port: int
    token: str
    job_id: str
    last_job: dict[str, object]


def assert_empty_search_phase_timing(
    result: dict[str, object],
) -> dict[str, object]:
    timing = cast("dict[str, object]", result["timing"])
    for key in (
        "search_seconds",
        "index_state_seconds",
        "model_load_seconds",
        "project_lease_seconds",
        "queue_wait_seconds",
    ):
        assert isinstance(timing[key], float)
    phases = cast("dict[str, object]", timing["phases"])
    assert phases == {
        "indexed_count": 0,
        "model_load_seconds": 0.0,
        "project_lease_seconds": 0.0,
    }
    for key in (
        "embedding_seconds",
        "qdrant_seconds",
        "rerank_seconds",
        "postprocess_seconds",
    ):
        assert timing[key] is None
    assert timing["timing_scope"] == "server_route"
    return timing


def assert_request_id(result: dict[str, object]) -> str:
    request_id = result["request_id"]
    assert isinstance(request_id, str)
    assert len(request_id) == 32
    return request_id


def wait_for_search_log_line(port: int, request_id: str) -> str:
    deadline = time.monotonic() + 5.0
    last_logs: object = None
    while time.monotonic() < deadline:
        last_logs = _do_http_call(
            port,
            f"/logs/json?contains={request_id}",
            None,
            timeout=5,
        )
        matching_line = _matching_search_log_line(last_logs, request_id)
        if matching_line is not None:
            return matching_line
        time.sleep(0.1)
    pytest.fail(
        "service.search log line did not become queryable via /logs/json: "
        f"request_id={request_id} logs={last_logs!r}"
    )


def _matching_search_log_line(logs: object, request_id: str) -> str | None:
    """Find one correlated service-search event in a structured log payload."""
    if not isinstance(logs, dict):
        return None
    raw_groups = cast("dict[str, object]", logs).get("groups")
    if not isinstance(raw_groups, list):
        return None
    for raw_group in cast("list[object]", raw_groups):
        if not isinstance(raw_group, dict):
            continue
        group = cast("dict[str, object]", raw_group)
        if group.get("source") != "service":
            continue
        raw_lines = group.get("lines")
        if not isinstance(raw_lines, list):
            continue
        for raw_line in cast("list[object]", raw_lines):
            line = str(raw_line)
            if request_id in line and "service.search" in line:
                return line
    return None


def exact_job_snapshot(port: int, job_id: str) -> dict[str, object] | None:
    result = _do_http_call(
        port,
        f"/jobs?job_id={job_id}&limit=8",
        None,
        timeout=5,
    )
    if not isinstance(result, dict):
        return None
    raw_jobs = result.get("jobs")
    if not isinstance(raw_jobs, list):
        return None
    for raw_job in cast("list[object]", raw_jobs):
        if isinstance(raw_job, dict):
            job = cast("dict[str, object]", raw_job)
            if job.get("id") == job_id:
                return job
    return None


def raw_search(
    port: int,
    token: str,
    payload: dict[str, object],
    *,
    timeout: float,
) -> RawSearchResponse:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with cast(
            "HTTPResponse", urllib.request.urlopen(request, timeout=timeout)
        ) as response:
            status = int(response.status)
            headers = {
                name.lower(): value.strip() for name, value in response.headers.items()
            }
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        headers = {name.lower(): value.strip() for name, value in exc.headers.items()}
        raw = exc.read()
    parsed = cast("object", json.loads(raw.decode("utf-8")))
    if not isinstance(parsed, dict):
        msg = f"search response body is not an object: {parsed!r}"
        raise TypeError(msg)
    return status, headers, cast("dict[str, object]", parsed)


def bounded_failure_evidence(
    port: int,
    token: str,
    job_id: str,
    *,
    last_job: dict[str, object] | None = None,
    last_response: RawSearchResponse | None = None,
) -> str:
    try:
        health: object = _do_http_call(port, "/health", None, timeout=5)
        if isinstance(health, dict):
            health = dict(health)
            if "service_token" in health:
                health["service_token"] = "<redacted>"
    except Exception as exc:  # diagnostics must not mask the primary failure
        health = f"{exc.__class__.__name__}: {exc}"
    try:
        jobs: object = _do_http_call(
            port,
            f"/jobs?job_id={job_id}&limit=8",
            None,
            timeout=5,
        )
    except Exception as exc:  # diagnostics must not mask the primary failure
        jobs = f"{exc.__class__.__name__}: {exc}"
    metrics_request = urllib.request.Request(
        f"http://127.0.0.1:{port}/metrics",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with cast(
            "HTTPResponse", urllib.request.urlopen(metrics_request, timeout=5)
        ) as response:
            metrics: object = {
                "status": int(response.status),
                "body": response.read(8192).decode("utf-8", errors="replace"),
            }
    except Exception as exc:  # diagnostics must not mask the primary failure
        metrics = f"{exc.__class__.__name__}: {exc}"
    rendered = json.dumps(
        {
            "health": health,
            "jobs": jobs,
            "metrics": metrics,
            "last_job": last_job,
            "last_response": last_response,
        },
        default=str,
        indent=2,
    )
    return rendered[:24000]


def _job_running_handshake(job: dict[str, object]) -> bool:
    if "spec" in job:
        resources = job.get("resources")
        if not isinstance(resources, dict):
            return False
        resource_map = cast("dict[str, object]", resources)
        return (
            job.get("state") == "running"
            and resource_map.get("project_lease_held") is True
        )
    progress = job.get("progress")
    if not isinstance(progress, dict):
        return False
    progress_map = cast("dict[str, object]", progress)
    step = progress_map.get("step")
    return job.get("phase") == "running" and isinstance(step, str) and step != "queued"


def _job_terminal_state(job: dict[str, object]) -> str | None:
    if "spec" in job:
        state = job.get("state")
        if state in {"cancelled", "succeeded", "failed", "interrupted"}:
            return cast("str", state)
        return None
    phase = job.get("phase")
    if phase in {"cancelled", "done", "error", "failed", "interrupted"}:
        return cast("str", phase)
    return None


def wait_for_running_job(
    port: int,
    token: str,
    job_id: str,
) -> dict[str, object]:
    deadline = time.monotonic() + 10.0
    last_job: dict[str, object] | None = None
    while time.monotonic() < deadline:
        try:
            last_job = exact_job_snapshot(port, job_id)
        except Exception as exc:
            pytest.fail(
                f"failed to poll running job {job_id}: {exc}\n"
                + bounded_failure_evidence(
                    port,
                    token,
                    job_id,
                    last_job=last_job,
                )
            )
        if last_job is not None:
            if _job_running_handshake(last_job):
                return last_job
            terminal = _job_terminal_state(last_job)
            if terminal is not None:
                pytest.fail(
                    f"job {job_id} became {terminal} before the running handshake\n"
                    + bounded_failure_evidence(
                        port,
                        token,
                        job_id,
                        last_job=last_job,
                    )
                )
        time.sleep(0.05)
    pytest.fail(
        f"job {job_id} did not enter the running handshake within 10 seconds\n"
        + bounded_failure_evidence(
            port,
            token,
            job_id,
            last_job=last_job,
        )
    )


def wait_for_succeeded_job(
    port: int,
    token: str,
    job_id: str,
    *,
    last_response: RawSearchResponse | None = None,
) -> dict[str, object]:
    deadline = time.monotonic() + 300.0
    last_job: dict[str, object] | None = None
    while time.monotonic() < deadline:
        try:
            last_job = exact_job_snapshot(port, job_id)
        except Exception as exc:
            pytest.fail(
                f"failed to poll terminal job {job_id}: {exc}\n"
                + bounded_failure_evidence(
                    port,
                    token,
                    job_id,
                    last_job=last_job,
                    last_response=last_response,
                )
            )
        if last_job is not None:
            terminal = _job_terminal_state(last_job)
            if terminal in {"succeeded", "done"}:
                return last_job
            if terminal is not None:
                pytest.fail(
                    f"job {job_id} terminated as {terminal}\n"
                    + bounded_failure_evidence(
                        port,
                        token,
                        job_id,
                        last_job=last_job,
                        last_response=last_response,
                    )
                )
        time.sleep(0.1)
    pytest.fail(
        f"job {job_id} did not succeed within 300 seconds\n"
        + bounded_failure_evidence(
            port,
            token,
            job_id,
            last_job=last_job,
            last_response=last_response,
        )
    )


def submit_clean_vault_rebuild(
    port: int,
    token: str,
    root: Path,
    *,
    label: str,
) -> str:
    try:
        response = _do_http_call(
            port,
            "/reindex",
            {"type": "vault", "clean": True, "project_root": str(root)},
            timeout=30,
        )
    except Exception as exc:
        pytest.fail(
            f"{label} submission failed: {exc}\n"
            + bounded_failure_evidence(
                port,
                token,
                f"{label}-not-submitted",
            )
        )
    evidence = (
        bounded_failure_evidence(
            port,
            token,
            f"{label}-not-submitted",
        )[:16000]
        + "\nsubmission_response="
        + json.dumps(response, default=str)[:8000]
    )
    if not isinstance(response, dict) or response.get("ok") is not True:
        pytest.fail(f"{label} submission was rejected\n{evidence}")
    job_id = response.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        pytest.fail(f"{label} submission omitted its job ID\n{evidence}")
    return job_id


def search_with_failure_evidence(
    context: SearchProbeContext,
    payload: dict[str, object],
    *,
    label: str,
    last_response: RawSearchResponse | None = None,
) -> RawSearchResponse:
    try:
        return raw_search(context.port, context.token, payload, timeout=300)
    except Exception as exc:
        pytest.fail(
            f"{label} failed: {exc}\n"
            + bounded_failure_evidence(
                context.port,
                context.token,
                context.job_id,
                last_job=context.last_job,
                last_response=last_response,
            )
        )


def live_service_token(port: int) -> str:
    health = _do_http_call(port, "/health", None, timeout=5)
    assert isinstance(health, dict), health
    token = health.get("service_token")
    assert isinstance(token, str) and token, health
    return token
