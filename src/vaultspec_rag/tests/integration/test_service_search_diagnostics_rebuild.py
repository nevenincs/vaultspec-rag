"""Search availability while a matching index rebuild is in flight.

A clean rebuild destroys the index the search would have answered from,
so an empty result during that window cannot be trusted to mean "no
matches exist". The service has to say so, and it has to say so
identically to every caller that asks at the same moment - the raw route,
the shared client, and an MCP process - while a search against an
unrelated root or an unrelated source stays unaffected.

The second half asserts the inverse: a rebuild that is merely paused
holds no authority over the index, so a matching search still answers
from real content and leaves the paused job untouched.
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from ...job_manager.manager import JobManager
from ...job_models import JobInitiator, JobMode, JobOperation, JobSource, JobSpec
from ...service_quiesce import ServiceQuiesceController
from ...serviceclient._search_transport import try_http_search
from ..corpus import build_synthetic_vault
from ._service_search_diagnostics_mcp import (
    McpConcurrentRequest,
    assert_mcp_unavailable_response,
    mcp_search_after_concurrent_admission,
    wait_for_mcp_initialization,
)
from ._service_search_diagnostics_support import (
    RawSearchPayloads,
    RawSearchResponse,
    SearchProbeContext,
    assert_request_id,
    bounded_failure_evidence,
    exact_job_snapshot,
    live_service_token,
    search_with_failure_evidence,
    submit_clean_vault_rebuild,
    wait_for_running_job,
    wait_for_search_log_line,
    wait_for_succeeded_job,
)
from .conftest import _live_service_context

if TYPE_CHECKING:
    from pathlib import Path

    from mcp.types import CallToolResult

type ConcurrentProbeResponses = tuple[
    RawSearchResponse,
    RawSearchResponse,
    RawSearchResponse,
    dict[str, object],
    CallToolResult,
]
type RebuildProbeRun = tuple[str, dict[str, object], ConcurrentProbeResponses]


@dataclass(frozen=True, slots=True)
class _ConcurrentSearchRequest:
    """Independent search shapes expected during one matching rebuild."""

    root: Path
    matching_empty_query: str
    raw_payloads: RawSearchPayloads


@dataclass(frozen=True, slots=True)
class _RebuildSearchInputs:
    """All independent inputs used to probe one matching vault rebuild."""

    port: int
    token: str
    status_dir: Path
    root: Path
    matching_empty_query: str
    raw_payloads: RawSearchPayloads


@dataclass(frozen=True, slots=True)
class _KnownDocumentSearch:
    """A real document expected to remain searchable during a paused rebuild."""

    document_id: str
    needle: str


def _search_after_concurrent_admission(
    admission: threading.Barrier,
    context: SearchProbeContext,
    payload: dict[str, object],
    *,
    label: str,
) -> RawSearchResponse:
    _wait_for_concurrent_admission(
        admission,
        context,
        label=label,
    )
    return search_with_failure_evidence(
        context,
        payload,
        label=label,
    )


def _wait_for_concurrent_admission(
    admission: threading.Barrier,
    context: SearchProbeContext,
    *,
    label: str,
) -> None:
    try:
        admission.wait(timeout=10)
    except threading.BrokenBarrierError as exc:
        pytest.fail(
            f"{label} did not reach concurrent admission: {exc}\n"
            + bounded_failure_evidence(
                context.port,
                context.token,
                context.job_id,
                last_job=context.last_job,
            )
        )


def _shared_search_after_concurrent_admission(
    admission: threading.Barrier,
    context: SearchProbeContext,
    query: str,
    root: Path,
) -> dict[str, object]:
    label = "shared-client matching empty search request"
    _wait_for_concurrent_admission(
        admission,
        context,
        label=label,
    )
    try:
        result = try_http_search(
            query,
            "vault",
            5,
            context.port,
            str(root),
            timeout=300,
        )
    except Exception as exc:
        pytest.fail(
            f"{label} failed: {exc}\n"
            + bounded_failure_evidence(
                context.port,
                context.token,
                context.job_id,
                last_job=context.last_job,
            )
        )
    if not isinstance(result, dict):
        pytest.fail(
            f"{label} returned {result!r}\n"
            + bounded_failure_evidence(
                context.port,
                context.token,
                context.job_id,
                last_job=context.last_job,
            )
        )
    return result


def _run_concurrent_search_probes(
    executor: ThreadPoolExecutor,
    admission: threading.Barrier,
    mcp_future: Future[CallToolResult],
    context: SearchProbeContext,
    request: _ConcurrentSearchRequest,
) -> ConcurrentProbeResponses:
    (
        search_payload,
        unrelated_payload,
        unrelated_source_payload,
    ) = request.raw_payloads
    search_future = executor.submit(
        _search_after_concurrent_admission,
        admission,
        context,
        search_payload,
        label="matching empty search request",
    )
    unrelated_future = executor.submit(
        _search_after_concurrent_admission,
        admission,
        context,
        unrelated_payload,
        label="unrelated-root empty search request",
    )
    unrelated_source_future = executor.submit(
        _search_after_concurrent_admission,
        admission,
        context,
        unrelated_source_payload,
        label="unrelated-source empty search request",
    )
    shared_client_future = executor.submit(
        _shared_search_after_concurrent_admission,
        admission,
        context,
        request.matching_empty_query,
        request.root,
    )
    try:
        mcp_response = mcp_future.result(timeout=390)
    except Exception as exc:
        pytest.fail(
            f"MCP matching empty search request failed: {exc}\n"
            + bounded_failure_evidence(
                context.port,
                context.token,
                context.job_id,
                last_job=context.last_job,
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
    inputs: _RebuildSearchInputs,
) -> RebuildProbeRun:
    admission = threading.Barrier(5)
    initialized = threading.Event()
    with ThreadPoolExecutor(max_workers=6) as executor:
        mcp_future = executor.submit(
            mcp_search_after_concurrent_admission,
            admission,
            initialized,
            McpConcurrentRequest(
                inputs.port,
                inputs.status_dir,
                inputs.root,
                inputs.matching_empty_query,
            ),
        )
        wait_for_mcp_initialization(initialized, mcp_future, inputs.port, inputs.token)
        job_id = submit_clean_vault_rebuild(
            inputs.port,
            inputs.token,
            inputs.root,
            label="matching-rebuild",
        )
        running_job = wait_for_running_job(inputs.port, inputs.token, job_id)
        responses = _run_concurrent_search_probes(
            executor,
            admission,
            mcp_future,
            SearchProbeContext(inputs.port, inputs.token, job_id, running_job),
            _ConcurrentSearchRequest(
                inputs.root,
                inputs.matching_empty_query,
                inputs.raw_payloads,
            ),
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
        "index_integrity",
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
        "index_integrity",
    }, evidence
    assert index_state["source"] == source, evidence
    assert index_state["indexed_count"] == 0, evidence
    # A fresh root has no publication to reconcile against, and the daemon
    # must say so rather than blessing the empty collection as checked-fine.
    raw_integrity = index_state["index_integrity"]
    assert isinstance(raw_integrity, dict), evidence
    integrity = cast("dict[str, object]", raw_integrity)
    assert integrity["verdict"] == "unverifiable", evidence
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
        _RebuildSearchInputs(
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
        ),
    )
    (
        search_response,
        unrelated_response,
        unrelated_source_response,
        shared_client_response,
        mcp_response,
    ) = probe_responses
    evidence = bounded_failure_evidence(
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
    unavailable_request_id = assert_request_id(search_response[2])
    unavailable_log = wait_for_search_log_line(port, unavailable_request_id)
    assert (
        "service.search event=unavailable status_code=503 error=index_unavailable"
    ) in unavailable_log, evidence
    assert f"request_id={unavailable_request_id}" in unavailable_log, evidence
    assert "source=vault" in unavailable_log, evidence
    assert "search_type=vault" in unavailable_log, evidence
    assert f"root={root}" in unavailable_log, evidence
    assert "results=0" in unavailable_log, evidence
    assert re.search(r"\btotal_seconds=\d+\.\d{3}\b", unavailable_log), evidence
    unrelated_evidence = bounded_failure_evidence(
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
    unrelated_source_evidence = bounded_failure_evidence(
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
        bounded_failure_evidence(
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
        bounded_failure_evidence(
            port,
            token,
            job_id,
            last_job=running_job,
        )[:12000]
        + "\nmcp_response="
        + repr(mcp_response)[:12000]
    )
    assert_mcp_unavailable_response(mcp_response, evidence=mcp_evidence)
    terminal_job = wait_for_succeeded_job(
        port,
        token,
        job_id,
        last_response=search_response,
    )
    post_response = search_with_failure_evidence(
        SearchProbeContext(port, token, job_id, terminal_job),
        search_payload,
        label="post-convergence empty search request",
        last_response=search_response,
    )
    post_status, _post_headers, post_body = post_response
    post_evidence = bounded_failure_evidence(
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


def _persist_paused_matching_rebuild(state_path: Path, root: Path) -> str:
    assert state_path.is_file()
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        state_path=state_path,
    )
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
        last_job = exact_job_snapshot(port, job_id)
        if last_job is not None and last_job.get("state") == "paused":
            _assert_paused_rebuild_snapshot(last_job, job_id=job_id, root=root)
            return last_job
        time.sleep(0.05)
    pytest.fail(
        f"job {job_id} did not remain paused after service restart\n"
        + bounded_failure_evidence(
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
    expected: _KnownDocumentSearch,
) -> None:
    paused_before = _wait_for_paused_rebuild_job(port, token, job_id, root)
    payload: dict[str, object] = {
        "query": expected.needle,
        "type": "vault",
        "top_k": 5,
        "project_root": str(root),
    }
    response = search_with_failure_evidence(
        SearchProbeContext(port, token, job_id, paused_before),
        payload,
        label="matching nonempty search with paused rebuild",
    )
    evidence = bounded_failure_evidence(
        port,
        token,
        job_id,
        last_job=paused_before,
        last_response=response,
    )
    _assert_matching_nonempty_response(
        response,
        expected_doc_id=expected.document_id,
        evidence=evidence,
    )
    request_id = assert_request_id(response[2])
    completed_log = wait_for_search_log_line(port, request_id)
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

    with _live_service_context(tmp_path) as (port, status_dir, _env):
        token = live_service_token(port)
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
    with _live_service_context(tmp_path) as (port, _status_dir, _env):
        token = live_service_token(port)
        _assert_nonempty_search_with_paused_rebuild(
            port,
            token,
            root,
            job_id=paused_job_id,
            expected=_KnownDocumentSearch(known_doc.doc_id, known_doc.needle),
        )
