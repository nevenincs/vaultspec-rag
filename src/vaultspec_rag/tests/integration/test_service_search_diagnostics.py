"""Integration tests for service search diagnostics."""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta
from typing import TYPE_CHECKING, cast

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent

from ...cli._http_search import _do_http_call, _timeout_diagnostics, _try_http_search
from ...job_manager import JobManager
from ...job_models import JobInitiator, JobMode, JobOperation, JobSource, JobSpec
from ..corpus import build_synthetic_vault
from .conftest import _live_service_context

if TYPE_CHECKING:
    from pathlib import Path

type RawSearchResponse = tuple[int, dict[str, str], dict[str, object]]
type RawSearchPayloads = tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]
type ConcurrentProbeResponses = tuple[
    RawSearchResponse,
    RawSearchResponse,
    RawSearchResponse,
    dict[str, object],
    CallToolResult,
]
type RebuildProbeRun = tuple[str, dict[str, object], ConcurrentProbeResponses]


def _assert_empty_search_phase_timing(
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


def _assert_request_id(result: dict[str, object]) -> str:
    request_id = result["request_id"]
    assert isinstance(request_id, str)
    assert len(request_id) == 32
    return request_id


def _wait_for_search_log_line(port: int, request_id: str) -> str:
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
    raw_groups = logs.get("groups")
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


def _exact_job_snapshot(port: int, job_id: str) -> dict[str, object] | None:
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


def _raw_search(
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            headers = {
                name.lower(): value.strip() for name, value in response.headers.items()
            }
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        headers = {name.lower(): value.strip() for name, value in exc.headers.items()}
        raw = exc.read()
    parsed: object = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        msg = f"search response body is not an object: {parsed!r}"
        raise TypeError(msg)
    return status, headers, cast("dict[str, object]", parsed)


def _bounded_failure_evidence(
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
        with urllib.request.urlopen(metrics_request, timeout=5) as response:
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


def _wait_for_running_job(
    port: int,
    token: str,
    job_id: str,
) -> dict[str, object]:
    deadline = time.monotonic() + 10.0
    last_job: dict[str, object] | None = None
    while time.monotonic() < deadline:
        try:
            last_job = _exact_job_snapshot(port, job_id)
        except Exception as exc:
            pytest.fail(
                f"failed to poll running job {job_id}: {exc}\n"
                + _bounded_failure_evidence(
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
                    + _bounded_failure_evidence(
                        port,
                        token,
                        job_id,
                        last_job=last_job,
                    )
                )
        time.sleep(0.05)
    pytest.fail(
        f"job {job_id} did not enter the running handshake within 10 seconds\n"
        + _bounded_failure_evidence(
            port,
            token,
            job_id,
            last_job=last_job,
        )
    )


def _wait_for_succeeded_job(
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
            last_job = _exact_job_snapshot(port, job_id)
        except Exception as exc:
            pytest.fail(
                f"failed to poll terminal job {job_id}: {exc}\n"
                + _bounded_failure_evidence(
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
                    + _bounded_failure_evidence(
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
        + _bounded_failure_evidence(
            port,
            token,
            job_id,
            last_job=last_job,
            last_response=last_response,
        )
    )


def _submit_clean_vault_rebuild(
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
            + _bounded_failure_evidence(
                port,
                token,
                f"{label}-not-submitted",
            )
        )
    evidence = (
        _bounded_failure_evidence(
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


def _search_with_failure_evidence(
    port: int,
    token: str,
    job_id: str,
    payload: dict[str, object],
    *,
    label: str,
    last_job: dict[str, object],
    last_response: RawSearchResponse | None = None,
) -> RawSearchResponse:
    try:
        return _raw_search(port, token, payload, timeout=300)
    except Exception as exc:
        pytest.fail(
            f"{label} failed: {exc}\n"
            + _bounded_failure_evidence(
                port,
                token,
                job_id,
                last_job=last_job,
                last_response=last_response,
            )
        )


def _search_after_concurrent_admission(
    admission: threading.Barrier,
    port: int,
    token: str,
    job_id: str,
    payload: dict[str, object],
    *,
    label: str,
    last_job: dict[str, object],
) -> RawSearchResponse:
    _wait_for_concurrent_admission(
        admission,
        port,
        token,
        job_id,
        label=label,
        last_job=last_job,
    )
    return _search_with_failure_evidence(
        port,
        token,
        job_id,
        payload,
        label=label,
        last_job=last_job,
    )


def _wait_for_concurrent_admission(
    admission: threading.Barrier,
    port: int,
    token: str,
    job_id: str,
    *,
    label: str,
    last_job: dict[str, object],
) -> None:
    try:
        admission.wait(timeout=10)
    except threading.BrokenBarrierError as exc:
        pytest.fail(
            f"{label} did not reach concurrent admission: {exc}\n"
            + _bounded_failure_evidence(
                port,
                token,
                job_id,
                last_job=last_job,
            )
        )


def _shared_search_after_concurrent_admission(
    admission: threading.Barrier,
    port: int,
    token: str,
    job_id: str,
    query: str,
    root: Path,
    *,
    last_job: dict[str, object],
) -> dict[str, object]:
    label = "shared-client matching empty search request"
    _wait_for_concurrent_admission(
        admission,
        port,
        token,
        job_id,
        label=label,
        last_job=last_job,
    )
    try:
        result = _try_http_search(
            query,
            "vault",
            5,
            port,
            str(root),
            timeout=300,
        )
    except Exception as exc:
        pytest.fail(
            f"{label} failed: {exc}\n"
            + _bounded_failure_evidence(
                port,
                token,
                job_id,
                last_job=last_job,
            )
        )
    if not isinstance(result, dict):
        pytest.fail(
            f"{label} returned {result!r}\n"
            + _bounded_failure_evidence(
                port,
                token,
                job_id,
                last_job=last_job,
            )
        )
    return result


async def _mcp_search_after_concurrent_admission_async(
    admission: threading.Barrier,
    initialized: threading.Event,
    port: int,
    status_dir: Path,
    root: Path,
    query: str,
) -> CallToolResult:
    env = dict(os.environ)
    env.update(
        {
            "VAULTSPEC_RAG_PORT": str(port),
            "VAULTSPEC_RAG_ROOT": str(root),
            "VAULTSPEC_RAG_STATUS_DIR": str(status_dir),
        }
    )
    server = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from vaultspec_rag.server import main; main()"],
        env=env,
    )
    async with (
        stdio_client(server) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await asyncio.wait_for(session.initialize(), timeout=60)
        initialized.set()
        await asyncio.wait_for(
            asyncio.to_thread(admission.wait, 10),
            timeout=15,
        )
        return await asyncio.wait_for(
            session.call_tool(
                "search_vault",
                arguments={
                    "query": query,
                    "top_k": 5,
                    "project_root": str(root),
                },
                read_timeout_seconds=timedelta(seconds=300),
            ),
            timeout=310,
        )


def _mcp_search_after_concurrent_admission(
    admission: threading.Barrier,
    initialized: threading.Event,
    port: int,
    status_dir: Path,
    root: Path,
    query: str,
) -> CallToolResult:
    return asyncio.run(
        _mcp_search_after_concurrent_admission_async(
            admission,
            initialized,
            port,
            status_dir,
            root,
            query,
        )
    )


def _wait_for_mcp_initialization(
    initialized: threading.Event,
    mcp_future: Future[CallToolResult],
    port: int,
    token: str,
) -> None:
    if initialized.wait(timeout=65):
        return
    failure = "session initialization did not complete"
    if mcp_future.done():
        try:
            mcp_future.result()
        except Exception as exc:
            failure = f"session initialization failed: {exc}"
    pytest.fail(
        f"MCP {failure}\n"
        + _bounded_failure_evidence(
            port,
            token,
            "not-submitted",
        )
    )


def _run_concurrent_search_probes(
    executor: ThreadPoolExecutor,
    admission: threading.Barrier,
    mcp_future: Future[CallToolResult],
    port: int,
    token: str,
    job_id: str,
    root: Path,
    matching_empty_query: str,
    raw_payloads: RawSearchPayloads,
    *,
    last_job: dict[str, object],
) -> ConcurrentProbeResponses:
    (
        search_payload,
        unrelated_payload,
        unrelated_source_payload,
    ) = raw_payloads
    search_future = executor.submit(
        _search_after_concurrent_admission,
        admission,
        port,
        token,
        job_id,
        search_payload,
        label="matching empty search request",
        last_job=last_job,
    )
    unrelated_future = executor.submit(
        _search_after_concurrent_admission,
        admission,
        port,
        token,
        job_id,
        unrelated_payload,
        label="unrelated-root empty search request",
        last_job=last_job,
    )
    unrelated_source_future = executor.submit(
        _search_after_concurrent_admission,
        admission,
        port,
        token,
        job_id,
        unrelated_source_payload,
        label="unrelated-source empty search request",
        last_job=last_job,
    )
    shared_client_future = executor.submit(
        _shared_search_after_concurrent_admission,
        admission,
        port,
        token,
        job_id,
        matching_empty_query,
        root,
        last_job=last_job,
    )
    try:
        mcp_response = mcp_future.result(timeout=390)
    except Exception as exc:
        pytest.fail(
            f"MCP matching empty search request failed: {exc}\n"
            + _bounded_failure_evidence(
                port,
                token,
                job_id,
                last_job=last_job,
            )
        )
    return (
        search_future.result(timeout=330),
        unrelated_future.result(timeout=330),
        unrelated_source_future.result(timeout=330),
        shared_client_future.result(timeout=330),
        mcp_response,
    )


def _run_probes_during_matching_rebuild(
    port: int,
    token: str,
    status_dir: Path,
    root: Path,
    matching_empty_query: str,
    raw_payloads: RawSearchPayloads,
) -> RebuildProbeRun:
    admission = threading.Barrier(5)
    initialized = threading.Event()
    with ThreadPoolExecutor(max_workers=6) as executor:
        mcp_future = executor.submit(
            _mcp_search_after_concurrent_admission,
            admission,
            initialized,
            port,
            status_dir,
            root,
            matching_empty_query,
        )
        _wait_for_mcp_initialization(initialized, mcp_future, port, token)
        job_id = _submit_clean_vault_rebuild(
            port,
            token,
            root,
            label="matching-rebuild",
        )
        running_job = _wait_for_running_job(port, token, job_id)
        responses = _run_concurrent_search_probes(
            executor,
            admission,
            mcp_future,
            port,
            token,
            job_id,
            root,
            matching_empty_query,
            raw_payloads,
            last_job=running_job,
        )
    return job_id, running_job, responses


def _assert_unavailable_response_envelope(
    status: int,
    headers: dict[str, str],
    body: dict[str, object],
    *,
    root: Path,
    evidence: str,
) -> dict[str, object]:
    assert status == 503, evidence
    assert "retry-after" not in headers, evidence
    assert set(body) == {
        "ok",
        "error",
        "message",
        "request_id",
        "index_state",
        "remediation",
    }, evidence
    assert body["ok"] is False, evidence
    assert body["error"] == "index_unavailable", evidence
    assert body["message"] == (
        f"The vault index for {root} is changing; this empty search cannot "
        "establish that no matches exist."
    ), evidence
    request_id = body["request_id"]
    assert isinstance(request_id, str), evidence
    assert re.fullmatch(r"[0-9a-f]{32}", request_id), evidence

    raw_index_state = body["index_state"]
    assert isinstance(raw_index_state, dict), evidence
    return cast("dict[str, object]", raw_index_state)


def _assert_unavailable_index_identity(
    index_state: dict[str, object],
    *,
    root: Path,
    evidence: str,
) -> None:
    assert set(index_state) == {
        "source",
        "indexed_count",
        "indexed_target_root",
        "requested_target_root",
        "target_matches",
        "status",
        "matching_jobs",
        "matching_jobs_truncated",
    }, evidence
    assert index_state["source"] == "vault", evidence
    indexed_count = index_state["indexed_count"]
    assert isinstance(indexed_count, int) and not isinstance(indexed_count, bool), (
        evidence
    )
    assert indexed_count >= 0, evidence
    assert index_state["indexed_target_root"] == str(root), evidence
    assert index_state["requested_target_root"] == str(root), evidence
    assert index_state["target_matches"] is True, evidence


def _assert_matching_job_diagnostics(
    index_state: dict[str, object],
    *,
    job_id: str,
    evidence: str,
) -> None:
    raw_matching_jobs = index_state["matching_jobs"]
    assert isinstance(raw_matching_jobs, list), evidence
    matching_jobs = cast("list[object]", raw_matching_jobs)
    assert len(matching_jobs) <= 8, evidence
    assert index_state["matching_jobs_truncated"] is False, evidence
    submitted_job: dict[str, object] | None = None
    for raw_job in matching_jobs:
        assert isinstance(raw_job, dict), evidence
        job = cast("dict[str, object]", raw_job)
        assert set(job) == {"id", "state", "mode"}, evidence
        assert job["state"] in {
            "queued",
            "running",
            "pausing",
            "paused",
            "cancelling",
        }, evidence
        assert job["mode"] in {"incremental", "rebuild"}, evidence
        if job["id"] == job_id:
            submitted_job = job
    assert submitted_job is not None, evidence
    assert submitted_job["state"] == "running", evidence
    assert submitted_job["mode"] == "rebuild", evidence


def _assert_unavailable_search_response(
    response: RawSearchResponse,
    *,
    root: Path,
    port: int,
    job_id: str,
    evidence: str,
) -> None:
    status, headers, body = response
    index_state = _assert_unavailable_response_envelope(
        status,
        headers,
        body,
        root=root,
        evidence=evidence,
    )
    _assert_unavailable_index_identity(index_state, root=root, evidence=evidence)
    _assert_matching_job_diagnostics(
        index_state,
        job_id=job_id,
        evidence=evidence,
    )
    assert index_state["status"] == "rebuilding", evidence
    assert body["remediation"] == [
        f"vaultspec-rag server jobs --state active --index vault --port {port}",
        "Retry the search after the matching index job reaches a terminal state.",
    ], evidence


def _assert_stable_missing_index_response(
    response: RawSearchResponse,
    *,
    root: Path,
    source: str,
    evidence: str,
) -> None:
    status, _headers, body = response
    assert status == 200, evidence
    assert body.get("ok") is not False, evidence
    assert "error" not in body, evidence
    assert body["results"] == [], evidence

    raw_index_state = body["index_state"]
    assert isinstance(raw_index_state, dict), evidence
    index_state = cast("dict[str, object]", raw_index_state)
    assert set(index_state) == {
        "source",
        "indexed_count",
        "indexed_target_root",
        "requested_target_root",
        "target_matches",
        "status",
    }, evidence
    assert index_state["source"] == source, evidence
    assert index_state["indexed_count"] == 0, evidence
    assert index_state["indexed_target_root"] == str(root), evidence
    assert index_state["requested_target_root"] == str(root), evidence
    assert index_state["target_matches"] is True, evidence
    assert index_state["status"] == "missing", evidence

    raw_empty = body["empty"]
    assert isinstance(raw_empty, dict), evidence
    empty = cast("dict[str, object]", raw_empty)
    assert empty["reason"] == "index_missing", evidence


def _assert_matching_nonempty_response(
    response: RawSearchResponse,
    *,
    expected_doc_id: str,
    evidence: str,
) -> None:
    status, _headers, body = response
    assert status == 200, evidence
    assert "error" not in body, evidence
    raw_results = body["results"]
    assert isinstance(raw_results, list) and raw_results, evidence
    results = cast("list[object]", raw_results)
    assert any(
        isinstance(raw_result, dict)
        and cast("dict[str, object]", raw_result).get("id") == expected_doc_id
        for raw_result in results
    ), evidence


def _assert_shared_unavailable_response(
    body: dict[str, object],
    *,
    job_id: str,
    evidence: str,
) -> None:
    assert body["ok"] is False, evidence
    assert body["error"] == "index_unavailable", evidence
    assert "results" not in body, evidence
    raw_index_state = body["index_state"]
    assert isinstance(raw_index_state, dict), evidence
    index_state = cast("dict[str, object]", raw_index_state)
    raw_matching_jobs = index_state["matching_jobs"]
    assert isinstance(raw_matching_jobs, list), evidence
    matching_jobs = cast("list[object]", raw_matching_jobs)
    assert any(
        isinstance(raw_job, dict)
        and cast("dict[str, object]", raw_job).get("id") == job_id
        for raw_job in matching_jobs
    ), evidence


def _assert_mcp_unavailable_response(
    response: CallToolResult,
    *,
    evidence: str,
) -> None:
    assert response.isError is True, evidence
    text = " ".join(
        block.text for block in response.content if isinstance(block, TextContent)
    )
    assert "index_unavailable" in text, evidence
    assert "vaultspec-rag server jobs" in text, evidence
    structured = response.structuredContent
    assert structured is None or "results" not in structured, evidence


def _run_clean_rebuild_availability_phase(
    port: int,
    token: str,
    status_dir: Path,
    root: Path,
    unrelated_root: Path,
) -> None:
    matching_empty_query = "type:nonexistent availability authority probe"
    search_payload: dict[str, object] = {
        "query": matching_empty_query,
        "type": "vault",
        "top_k": 5,
        "project_root": str(root),
    }
    unrelated_payload = {**search_payload, "project_root": str(unrelated_root)}
    unrelated_source_payload: dict[str, object] = {
        "query": "availability authority probe",
        "type": "code",
        "top_k": 5,
        "project_root": str(root),
        "include_paths": ["__availability_no_match__/**"],
    }

    job_id, running_job, probe_responses = _run_probes_during_matching_rebuild(
        port,
        token,
        status_dir,
        root,
        matching_empty_query,
        (
            search_payload,
            unrelated_payload,
            unrelated_source_payload,
        ),
    )
    (
        search_response,
        unrelated_response,
        unrelated_source_response,
        shared_client_response,
        mcp_response,
    ) = probe_responses
    evidence = _bounded_failure_evidence(
        port,
        token,
        job_id,
        last_job=running_job,
        last_response=search_response,
    )
    _assert_unavailable_search_response(
        search_response,
        root=root,
        port=port,
        job_id=job_id,
        evidence=evidence,
    )
    unavailable_request_id = _assert_request_id(search_response[2])
    unavailable_log = _wait_for_search_log_line(port, unavailable_request_id)
    assert (
        "service.search event=unavailable status_code=503 error=index_unavailable"
    ) in unavailable_log, evidence
    assert f"request_id={unavailable_request_id}" in unavailable_log, evidence
    assert "source=vault" in unavailable_log, evidence
    assert "search_type=vault" in unavailable_log, evidence
    assert f"root={root}" in unavailable_log, evidence
    assert "results=0" in unavailable_log, evidence
    assert re.search(r"\btotal_seconds=\d+\.\d{3}\b", unavailable_log), evidence
    unrelated_evidence = _bounded_failure_evidence(
        port,
        token,
        job_id,
        last_job=running_job,
        last_response=unrelated_response,
    )
    _assert_stable_missing_index_response(
        unrelated_response,
        root=unrelated_root,
        source="vault",
        evidence=unrelated_evidence,
    )
    unrelated_source_evidence = _bounded_failure_evidence(
        port,
        token,
        job_id,
        last_job=running_job,
        last_response=unrelated_source_response,
    )
    _assert_stable_missing_index_response(
        unrelated_source_response,
        root=root,
        source="code",
        evidence=unrelated_source_evidence,
    )
    shared_client_evidence = (
        _bounded_failure_evidence(
            port,
            token,
            job_id,
            last_job=running_job,
        )[:12000]
        + "\nshared_client_response="
        + json.dumps(shared_client_response, default=str)[:12000]
    )
    _assert_shared_unavailable_response(
        shared_client_response,
        job_id=job_id,
        evidence=shared_client_evidence,
    )
    mcp_evidence = (
        _bounded_failure_evidence(
            port,
            token,
            job_id,
            last_job=running_job,
        )[:12000]
        + "\nmcp_response="
        + repr(mcp_response)[:12000]
    )
    _assert_mcp_unavailable_response(mcp_response, evidence=mcp_evidence)
    terminal_job = _wait_for_succeeded_job(
        port,
        token,
        job_id,
        last_response=search_response,
    )
    post_response = _search_with_failure_evidence(
        port,
        token,
        job_id,
        search_payload,
        label="post-convergence empty search request",
        last_job=terminal_job,
        last_response=search_response,
    )
    post_status, _post_headers, post_body = post_response
    post_evidence = _bounded_failure_evidence(
        port,
        token,
        job_id,
        last_job=terminal_job,
        last_response=post_response,
    )
    assert post_status == 200, post_evidence
    assert post_body["results"] == [], post_evidence
    raw_post_empty = post_body["empty"]
    assert isinstance(raw_post_empty, dict), post_evidence
    post_empty = cast("dict[str, object]", raw_post_empty)
    assert post_empty["reason"] == "no_match", post_evidence


def _live_service_token(port: int) -> str:
    health = _do_http_call(port, "/health", None, timeout=5)
    assert isinstance(health, dict), health
    token = health.get("service_token")
    assert isinstance(token, str) and token, health
    return token


def _persist_paused_matching_rebuild(state_path: Path, root: Path) -> str:
    assert state_path.is_file()
    manager = JobManager(state_path=state_path)
    restored = manager.restore_persisted()
    assert restored.code == "job_state_restored", restored.to_dict()
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            str(root),
            JobMode.REBUILD,
        ),
        JobInitiator("integration", "paused nonempty search probe", str(root)),
        start_paused=True,
    )
    assert created.job is not None, created.to_dict()
    assert created.job.state.value == "paused", created.to_dict()
    assert created.job.runtime.task_active is False, created.to_dict()
    assert created.job.runtime.worker_active is False, created.to_dict()
    return created.job.id


def _assert_paused_rebuild_snapshot(
    job: dict[str, object],
    *,
    job_id: str,
    root: Path,
) -> None:
    assert job["id"] == job_id, job
    assert job["state"] == "paused", job
    assert job["desired_state"] == "paused", job
    assert job["spec"] == {
        "operation": "index",
        "source": "vault",
        "project_root": str(root),
        "mode": "rebuild",
    }, job
    runtime = cast("dict[str, object]", job["runtime"])
    assert runtime["task_active"] is False, job
    assert runtime["worker_active"] is False, job
    resources = cast("dict[str, object]", job["resources"])
    assert resources["index_capacity_held"] is False, job
    assert resources["project_lease_held"] is False, job
    assert resources["writer_lock_held"] is False, job
    assert resources["pipeline_active"] is False, job


def _wait_for_paused_rebuild_job(
    port: int,
    token: str,
    job_id: str,
    root: Path,
) -> dict[str, object]:
    deadline = time.monotonic() + 10.0
    last_job: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last_job = _exact_job_snapshot(port, job_id)
        if last_job is not None and last_job.get("state") == "paused":
            _assert_paused_rebuild_snapshot(last_job, job_id=job_id, root=root)
            return last_job
        time.sleep(0.05)
    pytest.fail(
        f"job {job_id} did not remain paused after service restart\n"
        + _bounded_failure_evidence(
            port,
            token,
            job_id,
            last_job=last_job,
        )
    )


def _assert_nonempty_search_with_paused_rebuild(
    port: int,
    token: str,
    root: Path,
    *,
    job_id: str,
    known_doc_id: str,
    known_needle: str,
) -> None:
    paused_before = _wait_for_paused_rebuild_job(port, token, job_id, root)
    payload: dict[str, object] = {
        "query": known_needle,
        "type": "vault",
        "top_k": 5,
        "project_root": str(root),
    }
    response = _search_with_failure_evidence(
        port,
        token,
        job_id,
        payload,
        label="matching nonempty search with paused rebuild",
        last_job=paused_before,
    )
    evidence = _bounded_failure_evidence(
        port,
        token,
        job_id,
        last_job=paused_before,
        last_response=response,
    )
    _assert_matching_nonempty_response(
        response,
        expected_doc_id=known_doc_id,
        evidence=evidence,
    )
    request_id = _assert_request_id(response[2])
    completed_log = _wait_for_search_log_line(port, request_id)
    assert "service.search event=completed status_code=200" in completed_log, evidence
    assert f"request_id={request_id}" in completed_log, evidence
    assert "source=vault" in completed_log, evidence
    assert "search_type=vault" in completed_log, evidence
    assert f"root={root}" in completed_log, evidence
    assert re.search(r"\bresults=[1-9]\d*\b", completed_log), evidence
    assert "matching_index_jobs=1" in completed_log, evidence
    assert f"matching_index_job_ids={job_id}" in completed_log, evidence
    assert "matching_index_jobs_truncated=false" in completed_log, evidence
    paused_after = _wait_for_paused_rebuild_job(port, token, job_id, root)
    assert paused_after["revision"] == paused_before["revision"], evidence


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_search_index_unavailable_during_matching_rebuild(tmp_path: Path) -> None:
    manifest = build_synthetic_vault(
        tmp_path / "availability-authority-project",
        n_docs=256,
        seed=252,
    )
    root = manifest.root.resolve()
    unrelated_root = tmp_path / "availability-unrelated-project"
    (unrelated_root / ".vault").mkdir(parents=True)
    unrelated_root = unrelated_root.resolve()
    assert unrelated_root != root

    with _live_service_context(tmp_path) as (port, status_dir):
        token = _live_service_token(port)
        _run_clean_rebuild_availability_phase(
            port,
            token,
            status_dir,
            root,
            unrelated_root,
        )

    paused_job_id = _persist_paused_matching_rebuild(
        tmp_path / "jobs-state.json",
        root,
    )
    known_doc = manifest.docs[0]
    with _live_service_context(tmp_path) as (port, _status_dir):
        token = _live_service_token(port)
        _assert_nonempty_search_with_paused_rebuild(
            port,
            token,
            root,
            job_id=paused_job_id,
            known_doc_id=known_doc.doc_id,
            known_needle=known_doc.needle,
        )


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_empty_service_search_reports_missing_index(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    port, _status_dir = live_service
    root = tmp_path / "empty-project"
    (root / ".vault").mkdir(parents=True)

    result = _try_http_search(
        "nothing should match this empty workspace",
        "vault",
        3,
        port,
        str(root),
        timeout=120,
    )

    assert isinstance(result, dict)
    _assert_request_id(result)
    assert result["results"] == []
    _assert_empty_search_phase_timing(result)
    index_state = cast("dict[str, object]", result["index_state"])
    assert isinstance(index_state, dict)
    assert index_state["source"] == "vault"
    assert index_state["indexed_count"] == 0
    assert set(index_state) == {
        "source",
        "indexed_count",
        "indexed_target_root",
        "requested_target_root",
        "target_matches",
        "status",
    }
    assert index_state["requested_target_root"] == str(root)
    assert index_state["target_matches"] is True
    empty = cast("dict[str, object]", result["empty"])
    assert isinstance(empty, dict)
    assert empty["reason"] == "index_missing"
    remediation = cast("list[object]", empty["remediation"])
    assert isinstance(remediation, list)
    assert any("index --type vault" in str(item) for item in remediation)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_direct_http_code_search_reports_code_index_state(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    port, _status_dir = live_service
    root = tmp_path / "empty-code-project"
    (root / ".vault").mkdir(parents=True)

    result = _do_http_call(
        port,
        "/search",
        {
            "query": "nothing should match this empty code workspace",
            "type": "code",
            "top_k": 3,
            "project_root": str(root),
        },
        timeout=120,
    )

    assert isinstance(result, dict)
    _assert_request_id(result)
    assert result["results"] == []
    _assert_empty_search_phase_timing(result)
    index_state = cast("dict[str, object]", result["index_state"])
    assert isinstance(index_state, dict)
    assert index_state["source"] == "code"
    assert index_state["indexed_count"] == 0
    assert set(index_state) == {
        "source",
        "indexed_count",
        "indexed_target_root",
        "requested_target_root",
        "target_matches",
        "status",
    }
    empty = cast("dict[str, object]", result["empty"])
    assert isinstance(empty, dict)
    assert empty["reason"] == "index_missing"
    remediation = cast("list[object]", empty["remediation"])
    assert isinstance(remediation, list)
    assert any("index --type code" in str(item) for item in remediation)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_direct_http_search_type_contract(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    port, _status_dir = live_service
    root = tmp_path / "search-type-contract-project"
    (root / ".vault").mkdir(parents=True)
    health = _do_http_call(port, "/health", None, timeout=5)
    assert isinstance(health, dict), health
    token = health.get("service_token")
    assert isinstance(token, str) and token, health

    for invalid_type in ("all", ["code"]):
        status, _headers, body = _raw_search(
            port,
            token,
            {
                "query": "",
                "type": invalid_type,
                "project_root": str(tmp_path / "missing-project"),
            },
            timeout=5,
        )
        assert status == 400, body
        assert body["ok"] is False, body
        assert body["error"] == "bad_request", body
        message = str(body["message"])
        assert "'vault'" in message, body
        assert "'code'" in message, body
        assert "'codebase'" in message, body

    alias_status, _alias_headers, alias_body = _raw_search(
        port,
        token,
        {
            "query": "nothing should match this empty code workspace",
            "type": "codebase",
            "top_k": 3,
            "project_root": str(root),
        },
        timeout=120,
    )
    assert alias_status == 200, alias_body
    index_state = cast("dict[str, object]", alias_body["index_state"])
    assert index_state["source"] == "code", alias_body
    request_id = _assert_request_id(alias_body)
    alias_log = _wait_for_search_log_line(port, request_id)
    assert "source=code" in alias_log
    assert "search_type=code" in alias_log
    assert "search_type=codebase" not in alias_log


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_search_request_id_is_log_correlatable(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    port, _status_dir = live_service
    root = tmp_path / "request-id-project"
    (root / ".vault").mkdir(parents=True)

    result = _do_http_call(
        port,
        "/search",
        {
            "query": "correlate this search request",
            "type": "code",
            "top_k": 1,
            "project_root": str(root),
        },
        timeout=120,
    )

    assert isinstance(result, dict)
    request_id = _assert_request_id(result)
    completed_log = _wait_for_search_log_line(port, request_id)
    assert "service.search event=completed status_code=200" in completed_log
    assert f"request_id={request_id}" in completed_log
    assert "source=code" in completed_log
    assert "search_type=code" in completed_log
    assert f"root={root}" in completed_log
    assert "results=0" in completed_log
    assert re.search(r"\btotal_seconds=\d+\.\d{3}\b", completed_log)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_service_search_short_timeout_reports_operational_diagnostics(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    port, _status_dir = live_service
    root = tmp_path / "timeout-project"
    (root / ".vault").mkdir(parents=True)

    result = _try_http_search(
        "this request intentionally has an unrealistically short timeout",
        "vault",
        3,
        port,
        str(root),
        timeout=0.000001,
    )

    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["error"] == "http_search_timeout"
    assert result["timeout_seconds"] == 0.000001
    diagnostics = cast("dict[str, object]", result["diagnostics"])
    health = cast("dict[str, object]", diagnostics["health"])
    jobs = cast("dict[str, object]", diagnostics["jobs"])
    remediation = cast("list[object]", result["remediation"])
    assert health["status"] == "ready"
    assert jobs["available"] is True
    backpressure = cast("dict[str, object]", diagnostics["backpressure"])
    assert backpressure["active_indexing_conflict"] is False
    assert isinstance(remediation, list)
    assert f"vaultspec-rag server status --port {port}" in remediation
    assert any("server jobs --state active" in str(item) for item in remediation)


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_timeout_diagnostics_survive_unavailable_probe_port() -> None:
    result = _timeout_diagnostics(_unused_local_port(), 0.01)

    assert result["ok"] is False
    assert result["error"] == "http_search_timeout"
    diagnostics = cast("dict[str, object]", result["diagnostics"])
    health = cast("dict[str, object]", diagnostics["health"])
    jobs = cast("dict[str, object]", diagnostics["jobs"])
    backpressure = cast("dict[str, object]", diagnostics["backpressure"])
    assert health["available"] is False
    assert jobs["available"] is False
    assert backpressure["active_indexing_conflict"] is None


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_direct_http_search_invalid_root_is_bad_request(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    port, _status_dir = live_service
    root = tmp_path / "not-a-vaultspec-project"
    root.mkdir()

    result = _do_http_call(
        port,
        "/search",
        {
            "query": "anything",
            "type": "vault",
            "top_k": 3,
            "project_root": str(root),
        },
        timeout=120,
    )

    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["error"] == "bad_request"
    assert "no .vault" in str(result["message"])
