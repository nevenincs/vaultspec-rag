"""Human presentation for ``server jobs`` views and job detail."""

from __future__ import annotations

import re
import time
from typing import cast

import typer

import vaultspec_rag.cli as _cli

from .._job_errors import STALL_THRESHOLD_SECONDS, classify_error_text, remediation
from ._cli_format import _format_mb, _format_milliseconds, _format_seconds, _path_label
from ._render import _plain, address_line
from ._service_jobs_query import (
    empty_jobs_message,
    filter_is_set,
    job_awaiting_admission,
    job_is_waiting,
    jobs_from_result,
)

_RESULT_RE = re.compile(
    r"^\+(?P<added>\d+)\s*/(?P<updated>\d+)\s*-(?P<removed>\d+)"
    r"\s*\((?P<duration_ms>\d+)ms\)(?:\s*~(?P<skipped>\d+))?$"
)
# The stall threshold is service-domain: the server computes the
# authoritative ``stalled`` flag; this constant only backs the fallback
# for snapshots from an older service that lacks the flag.


def _resource_at(job: dict[str, object], key: str) -> dict[str, object] | None:
    resources = job.get("resources")
    if not isinstance(resources, dict):
        return None
    value = cast("dict[str, object]", resources).get(key)
    return cast("dict[str, object]", value) if isinstance(value, dict) else None


def _preferred_resource_snapshot(job: dict[str, object]) -> dict[str, object] | None:
    for key in ("current", "finished", "started"):
        snapshot = _resource_at(job, key)
        if snapshot is not None:
            return snapshot
    return None


def _resource_summary(job: dict[str, object]) -> str:
    snapshot = _preferred_resource_snapshot(job)
    if snapshot is None:
        return ""
    parts: list[str] = []
    if "rss_mb" in snapshot:
        parts.append(f"process {_format_mb(snapshot.get('rss_mb'))}")
    if "cuda_allocated_mb" in snapshot:
        parts.append(f"GPU used {_format_mb(snapshot.get('cuda_allocated_mb'))}")
    if "cuda_reserved_mb" in snapshot:
        parts.append(f"GPU reserved {_format_mb(snapshot.get('cuda_reserved_mb'))}")
    return ", ".join(parts)


def _initiator_label(raw: object) -> str:
    value = str(raw or "not reported")
    if value == "watcher":
        return "automatic updates"
    if value in ("cli", "tool"):
        return "manual request"
    return value.replace("_", " ")


def _command_label(raw: object) -> str:
    value = str(raw or "request not reported")
    if value == "watcher_code_index":
        return "automatic code index update"
    if value == "watcher_vault_index":
        return "automatic vault index update"
    if value == "reindex_codebase":
        return "code index refresh"
    if value == "reindex_vault":
        return "vault index refresh"
    return value.replace("_", " ")


def phase_label(job: dict[str, object]) -> str:
    phase = str(job.get("phase", "not-reported"))
    if phase in ("error", "failed"):
        return "failed"
    if job_is_waiting(job):
        return "waiting"
    if phase == "running":
        return "active"
    if phase == "done":
        return "finished"
    return phase


def _job_prefix(job: dict[str, object]) -> str:
    phase = str(job.get("phase", ""))
    if job_is_waiting(job):
        return "~"
    if phase == "running":
        return "*"
    if phase in ("error", "failed"):
        return "!"
    return "-"


def _job_timestamp(job: dict[str, object]) -> float:
    timestamp = job.get("finished_at") or job.get("started_at")
    return float(timestamp) if isinstance(timestamp, int | float) else 0.0


def _job_time_label(job: dict[str, object]) -> str:
    timestamp = _job_timestamp(job)
    if timestamp <= 0:
        return "time not reported"
    return time.strftime("%H:%M:%S", time.localtime(timestamp))


def project_label(job: dict[str, object]) -> str:
    initiator = job.get("initiator")
    if not isinstance(initiator, dict):
        return "project not reported"
    project_root = cast("dict[str, object]", initiator).get("project_root")
    if not project_root:
        return "project not reported"
    parts = str(project_root).replace("\\", "/").rstrip("/").split("/")
    return parts[-1] if parts and parts[-1] else str(project_root)


def _project_phrase(job: dict[str, object]) -> str:
    project = project_label(job)
    if project == "project not reported":
        return ""
    return f" for {project}"


def project_root(job: dict[str, object]) -> str | None:
    initiator = job.get("initiator")
    if not isinstance(initiator, dict):
        return None
    root = cast("dict[str, object]", initiator).get("project_root")
    return str(root) if root else None


def _source_label(job: dict[str, object]) -> str:
    source = str(job.get("source", "index"))
    if source == "code":
        return "code"
    if source == "vault":
        return "vault"
    return source


def operation_label(job: dict[str, object]) -> str:
    source = _source_label(job)
    trigger = str(job.get("trigger", ""))
    initiator = job.get("initiator")
    command = ""
    if isinstance(initiator, dict):
        command = str(cast("dict[str, object]", initiator).get("command") or "")
    if source == "maintenance":
        return "storage maintenance cycle"
    if trigger == "watcher":
        return f"{source} index update"
    if command.startswith("reindex_"):
        return f"{source} index refresh"
    return f"{source} index operation"


def _progress_step_label(step: str, source: str) -> str:
    section = (
        "source code section"
        if source == "code"
        else "document section"
        if source == "vault"
        else "section"
    )
    sections = f"{section}s"
    labels = {
        "queued": "waiting to write the index",
        "discover": "discovering items",
        "chunk": "preparing files",
        "delete removed": (
            "removing stale source files"
            if source == "code"
            else "removing deleted vault documents"
            if source == "vault"
            else "removing stale index entries"
        ),
        "embed": f"embedding {sections}",
        "embed + upsert chunks": f"embedding and writing {sections}",
        "embed + upsert documents": "embedding and writing documents",
        "index": "writing index",
        "chunk + embed": "preparing and embedding files",
        "upsert": "writing vectors",
    }
    return labels.get(step, step.replace("_", " "))


def human_progress(job: dict[str, object]) -> str:
    raw_progress = job.get("progress")
    if not isinstance(raw_progress, dict):
        return ""
    progress = cast("dict[str, object]", raw_progress)
    step = str(progress.get("step", ""))
    label = _progress_step_label(step, _source_label(job))
    completed = progress.get("completed")
    total = progress.get("total")
    if step == "queued":
        return label
    if isinstance(completed, int | float) and isinstance(total, int | float):
        return f"{label} {int(completed)} of {int(total)}"
    if isinstance(completed, int | float) and step:
        return f"{label} {int(completed)}"
    return label


def degradation_verdict(job: dict[str, object]) -> str | None:
    """The service's three-way health verdict, or ``None`` from an older daemon.

    Absent is not the same answer as present: a daemon that publishes the
    field is the authority on the verdict, while one that never publishes it
    predates the classification and falls back to the local stall reading.
    """
    value = job.get("degradation")
    if isinstance(value, str) and value:
        return value
    return None


def _evidence_section(job: dict[str, object], name: str) -> dict[str, object] | None:
    evidence = job.get("degradation_evidence")
    if not isinstance(evidence, dict):
        return None
    section = cast("dict[str, object]", evidence).get(name)
    return cast("dict[str, object]", section) if isinstance(section, dict) else None


def _forward_evidence_phrase(job: dict[str, object]) -> str:
    """One phrase for the forward-pass finding, empty without evidence."""
    forward = _evidence_section(job, "forward")
    if forward is None:
        return ""
    age = forward.get("age_seconds")
    aged = isinstance(age, int | float) and not isinstance(age, bool)
    if forward.get("in_flight") is True:
        phrase = (
            f"GPU forward pass running {_format_seconds(age)}"
            if aged
            else "GPU forward pass running"
        )
        if forward.get("thread_alive") is False:
            phrase += " (encode thread dead)"
        return phrase
    if aged:
        return f"last GPU forward finished {_format_seconds(age)} ago"
    return ""


def _unhealthy_summary(job: dict[str, object], verdict: str) -> str:
    """One line naming the verdict and its leading cause, service words only."""
    raw_age = job.get("last_progress_age_seconds")
    base = (
        f"no progress for {_format_seconds(raw_age)}"
        if isinstance(raw_age, int | float)
        else "no recent progress"
    )
    forward = _forward_evidence_phrase(job)
    return f"{verdict}: {'; '.join(part for part in (base, forward) if part)}"


def _encode_evidence_line(job: dict[str, object]) -> str | None:
    forward = _evidence_section(job, "forward")
    if forward is None:
        return None
    phrase = _forward_evidence_phrase(job) or "no forward pass observed"
    ordinal = forward.get("slice_ordinal")
    items = forward.get("items")
    if ordinal is not None and items is not None:
        phrase += f" (slice {ordinal}, {items} items)"
    alive = forward.get("thread_alive")
    if alive is not None and forward.get("in_flight") is not True:
        phrase += "; encode thread " + ("alive" if alive is True else "dead")
    return f"Encode: {phrase}"


def _gpu_evidence_line(job: dict[str, object]) -> str | None:
    gpu = _evidence_section(job, "gpu")
    if gpu is None:
        return None
    if gpu.get("available") is not True:
        return "GPU: not measurable from the service process"
    parts: list[str] = []
    utilization = gpu.get("utilization_percent")
    if isinstance(utilization, int | float):
        parts.append(f"{round(float(utilization))}% busy")
    used = gpu.get("memory_used_mb")
    total = gpu.get("memory_total_mb")
    if used is not None or total is not None:
        parts.append(f"{_format_mb(used)} used of {_format_mb(total)}")
    return f"GPU: {', '.join(parts) if parts else 'no reading'}"


def _backend_evidence_line(job: dict[str, object]) -> str | None:
    backend = _evidence_section(job, "backend")
    if backend is None:
        return None
    alive = backend.get("alive")
    detail = backend.get("detail")
    if alive is True:
        return f"Backend: answered in {_format_seconds(backend.get('latency_seconds'))}"
    if alive is False:
        return f"Backend: failed: {detail}"
    return f"Backend: {detail or 'not probed'}"


def degradation_evidence_lines(job: dict[str, object]) -> tuple[str, ...]:
    """Render the service's evidence block, one finding per line, verbatim.

    Values are shown as the service sampled them - no local thresholds and
    no re-derivation - so the CLI and the TUI cannot tell an operator two
    different stories about the same unhealthy job.
    """
    lines = (
        _encode_evidence_line(job),
        _gpu_evidence_line(job),
        _backend_evidence_line(job),
    )
    return tuple(line for line in lines if line is not None)


def stale_progress_label(job: dict[str, object]) -> str:
    if str(job.get("phase", "")) != "running" or job_is_waiting(job):
        return ""
    verdict = degradation_verdict(job)
    if verdict is not None:
        # The service verdict is authoritative: render it and its evidence,
        # never a locally recomputed threshold.
        return "" if verdict == "healthy" else _unhealthy_summary(job, verdict)
    return _fallback_stale_label(job)


def _fallback_stale_label(job: dict[str, object]) -> str:
    """The pre-verdict stall reading, kept only for daemons that lack it.

    Prefers the service-computed ``stalled`` flag, then the local threshold
    for snapshots from an older service that lacks even that.
    """
    raw_age = job.get("last_progress_age_seconds")
    if not isinstance(raw_age, int | float):
        return ""
    stalled = job.get("stalled")
    if stalled is False:
        return ""
    if stalled is not True and float(raw_age) < STALL_THRESHOLD_SECONDS:
        return ""
    return f"no progress for {_format_seconds(raw_age)}"


def _human_result(raw: object, *, failed: bool = False) -> str:
    if not raw:
        return ""
    result = " ".join(str(raw).split())
    if result == "watcher task cancelled":
        return "automatic update cancelled"
    if failed:
        # One shared taxonomy: the same classification the service
        # stamps as ``error_kind`` drives the friendly remediation here,
        # so the CLI never grows its own error-string matching again.
        # Applied only to failed jobs so a success summary that happens
        # to contain a marker word is never replaced.
        friendly = remediation(classify_error_text(result))
        if friendly is not None:
            return friendly
    match = _RESULT_RE.match(result.strip())
    if match is None:
        return result
    added = int(match.group("added"))
    updated = int(match.group("updated"))
    removed = int(match.group("removed"))
    duration_ms = int(match.group("duration_ms"))
    parts = [
        f"added {added}",
        f"updated {updated}",
        f"removed {removed}",
        f"finished in {_format_milliseconds(duration_ms)}",
    ]
    skipped = match.group("skipped")
    if skipped is not None:
        parts.append(f"skipped {int(skipped)}")
    return ", ".join(parts)


def _waiting_job_detail(detail: str, raw_runtime: object) -> str:
    has_runtime = isinstance(raw_runtime, int | float)
    if detail:
        return (
            f"{detail} for {_format_seconds(raw_runtime)}"
            if has_runtime
            else f"{detail}; runtime not reported"
        )
    return (
        f"waiting for {_format_seconds(raw_runtime)}"
        if has_runtime
        else "waiting; runtime not reported"
    )


def _admission_wait_detail(raw_runtime: object) -> str:
    """Name the wait, not just its duration.

    An operator reading "waiting for 6 minutes" cannot tell whether the job is
    stuck or correctly queued. Naming the GPU slot says both what it waits on
    and that exactly one job holds it, which turns an alarming line into an
    expected one - and points at the real remedy when it is not expected.
    """
    if isinstance(raw_runtime, int | float):
        return (
            f"waiting {_format_seconds(raw_runtime)} for the GPU slot "
            "(one indexing job encodes at a time)"
        )
    return "waiting for the GPU slot (one indexing job encodes at a time)"


def _running_job_detail(job: dict[str, object]) -> str:
    detail = human_progress(job)
    raw_runtime = job.get("runtime_seconds")
    if job_awaiting_admission(job):
        return _admission_wait_detail(raw_runtime)
    if job_is_waiting(job):
        return _waiting_job_detail(detail, raw_runtime)
    runtime_detail = (
        f"running for {_format_seconds(raw_runtime)}"
        if isinstance(raw_runtime, int | float)
        else "runtime not reported"
    )
    stale_progress = stale_progress_label(job)
    parts = [p for p in (detail, runtime_detail, stale_progress) if p]
    return "; ".join(parts) if parts else runtime_detail


def _job_summary_detail(job: dict[str, object]) -> str:
    phase = str(job.get("phase", ""))
    if phase == "running":
        return _running_job_detail(job)
    if phase in ("error", "failed"):
        result = _human_result(job.get("result"), failed=True)
        return f"error: {result}" if result else "error reported"
    result = _human_result(job.get("result"))
    if result:
        return result
    return human_progress(job)


def _human_sorted_jobs(jobs: list[object]) -> list[dict[str, object]]:
    normalised = [
        cast("dict[str, object]", entry) if isinstance(entry, dict) else {}
        for entry in jobs
    ]
    return sorted(normalised, key=_job_timestamp)


def _job_id_labels(jobs: list[dict[str, object]]) -> dict[int, str]:
    raw_ids = [str(job.get("id", "")) for job in jobs]
    labels: dict[int, str] = {}
    for index, raw_id in enumerate(raw_ids):
        if not raw_id:
            labels[index] = "not reported"
            continue
        min_length = min(8, len(raw_id))
        label = raw_id[:min_length]
        for length in range(min_length, len(raw_id) + 1):
            prefix = raw_id[:length]
            matches = [other for other in raw_ids if other and other.startswith(prefix)]
            if len(matches) == 1:
                label = prefix
                break
        labels[index] = label
    return labels


def _shown_job_counts(jobs: list[dict[str, object]]) -> tuple[int, int, int, int]:
    active = 0
    waiting = 0
    finished = 0
    failed = 0
    for job in jobs:
        phase = str(job.get("phase", ""))
        if phase in ("error", "failed"):
            failed += 1
        elif phase == "done":
            finished += 1
        elif job_is_waiting(job):
            waiting += 1
        elif phase == "running":
            active += 1
    return active, waiting, finished, failed


def _filters_label(result: dict[str, object]) -> str:
    raw_filters = result.get("filters")
    if not isinstance(raw_filters, dict):
        return ""
    filters = cast("dict[str, object]", raw_filters)
    visible: list[str] = []
    labels = {
        "phase": "state",
        "source": "index",
        "trigger": "started by",
        "query": "text",
        "job_id": "job",
        "since": "updated within",
    }
    values = {
        "running": "active or waiting",
        "done": "finished",
        "watcher": "automatic updates",
        "tool": "manual request",
    }
    state = filters.get("state")
    if state == "active":
        visible.append("state active")
    elif state == "waiting":
        visible.append("state waiting")
    elif filter_is_set(state):
        visible.append(f"state {state}")

    for key in ("phase", "source", "trigger", "query", "job_id", "since"):
        if key == "phase" and state in ("active", "waiting"):
            continue
        value = filters.get(key)
        if filter_is_set(value):
            value_text = values.get(str(value), str(value))
            visible.append(f"{labels[key]} {value_text}")
    if filters.get("failed") is True:
        visible.append("failed only")
    return f" Filtered by {'; '.join(visible)}." if visible else ""


def _filter_line(result: dict[str, object]) -> str:
    text = _filters_label(result).strip()
    if not text:
        return ""
    prefix = "Filtered by "
    if text.startswith(prefix):
        text = text[len(prefix) :]
    return text.removesuffix(".")


def _job_count_text(
    count: object,
    singular: str = "job",
    plural: str | None = None,
) -> str:
    value = count if isinstance(count, int) else 0
    word = singular if value == 1 else (plural or f"{singular}s")
    return f"{value} {word}"


def _shown_count_text(returned: object, *, filtered: bool) -> str:
    if filtered:
        return _job_count_text(returned, "matching job", "matching jobs")
    return _job_count_text(returned)


def _job_counts_line(active: int, waiting: int, finished: int, failed: int) -> str:
    return (
        f"Displayed jobs: {active} active, {waiting} waiting, "
        f"{finished} finished, {failed} failed"
    )


def _render_jobs_header(
    *,
    port: int,
    shown_count: str,
    total: object,
    counts_line: str,
) -> None:
    """Print the opening lines both the populated and empty views share."""
    _plain("Jobs")
    _plain(address_line(port))
    _plain(f"Displayed: {shown_count}")
    _plain(f"Total: {_job_count_text(total)}")
    _plain(counts_line)


def _render_filter_and_watch(
    filter_text: str,
    *,
    monitoring: bool,
    watch_text: str | None,
) -> None:
    """Print the filter line and, while watching, the refresh banner.

    Shared so the two views cannot drift into telling an operator different
    things about the same refresh.
    """
    if filter_text:
        _plain(f"Filter: {filter_text}")
    if not monitoring:
        return
    _plain(f"Refreshed: {time.strftime('%H:%M:%S', time.localtime())}")
    _cli.console.print(watch_text or "Watch: press Ctrl+C to stop.")


def _render_jobs_feed(
    result: dict[str, object],
    jobs: list[object],
    *,
    port: int,
    monitoring: bool = False,
    watch_text: str | None = None,
) -> None:
    sorted_jobs = _human_sorted_jobs(jobs)
    filter_text = _filter_line(result)
    _render_jobs_header(
        port=port,
        shown_count=_shown_count_text(
            result.get("returned", len(jobs)), filtered=bool(filter_text)
        ),
        total=result.get("total", len(jobs)),
        counts_line=_job_counts_line(*_shown_job_counts(sorted_jobs)),
    )
    if not filter_text:
        _plain("Showing: active, waiting, failed, then latest finished")
    _plain("Order: latest job appears last")
    _plain("Legend: * active, ~ waiting, ! failed, - finished")
    # Scripted consumers must use the structured envelope: this human summary
    # always contains the literal words "active"/"waiting", so grepping it for
    # job states self-deadlocks (a waiter that greps "active" always matches).
    _plain("Scripting: use --json (this summary always contains the word 'active')")
    _render_filter_and_watch(filter_text, monitoring=monitoring, watch_text=watch_text)
    job_id_labels = _job_id_labels(sorted_jobs)
    for index, job in enumerate(sorted_jobs):
        job_id = job_id_labels[index]
        _cli.console.print(
            f"{_job_prefix(job)} {_job_time_label(job)} {phase_label(job)} "
            f"{operation_label(job)}{_project_phrase(job)} (job {job_id}) - "
            f"{_job_summary_detail(job)}",
            soft_wrap=True,
        )


def _render_empty_jobs_result(
    result: dict[str, object],
    *,
    job_id: str | None,
    port: int,
    monitoring: bool,
    watch_text: str | None = None,
) -> None:
    filter_text = _filter_line(result)
    _render_jobs_header(
        port=port,
        shown_count=_shown_count_text(
            result.get("returned", 0), filtered=bool(filter_text or job_id)
        ),
        total=result.get("total", 0),
        counts_line=_job_counts_line(0, 0, 0, 0),
    )
    _plain("Order: latest job appears last")
    _render_filter_and_watch(filter_text, monitoring=monitoring, watch_text=watch_text)
    _cli.console.print(empty_jobs_message(result, job_id))
    _plain("Next actions:")
    _plain(f"  vaultspec-rag server status --port {port}")
    _plain(f"  vaultspec-rag server logs --limit 20 --port {port}")


def _render_job_progress_detail(job: dict[str, object]) -> None:
    if str(job.get("phase", "")) == "running":
        _cli.console.print(
            "Last progress update: "
            f"{_format_seconds(job.get('last_progress_age_seconds'))} ago"
        )
    stale_progress = stale_progress_label(job)
    if stale_progress:
        _cli.console.print(f"Progress warning: {stale_progress}")
    if isinstance(job.get("progress"), dict):
        _cli.console.print(f"Progress: {human_progress(job)}")


def _render_job_degradation_detail(job: dict[str, object]) -> None:
    """Print the service verdict and its evidence, verbatim.

    Silent for a healthy job and for a daemon that predates the verdict -
    the stale-progress warning above already covers the older fallback.
    """
    verdict = degradation_verdict(job)
    if verdict is None or verdict == "healthy":
        return
    _cli.console.print(f"Health: {verdict}")
    for line in degradation_evidence_lines(job):
        _cli.console.print(f"  {line}")


def _render_job_initiator_detail(job: dict[str, object]) -> None:
    initiator = job.get("initiator")
    if not isinstance(initiator, dict):
        return
    initiator_data = cast("dict[str, object]", initiator)
    _cli.console.print(f"Started by: {_initiator_label(initiator_data.get('kind'))}")
    _cli.console.print(f"Request: {_command_label(initiator_data.get('command'))}")


def _render_job_runtime_detail(job: dict[str, object]) -> None:
    runtime = job.get("runtime")
    if not isinstance(runtime, dict):
        return
    runtime_data = cast("dict[str, object]", runtime)
    pid = runtime_data.get("pid")
    if pid is not None:
        _cli.console.print(f"Job process id: {pid}")
    user = runtime_data.get("user")
    if user:
        _cli.console.print(f"User: {user}")
    executable = runtime_data.get("executable")
    if executable:
        _cli.console.print(f"Python: {_path_label(executable)}")
    virtual_env = runtime_data.get("virtual_env") or runtime_data.get("prefix")
    if virtual_env:
        _cli.console.print(f"Python environment: {_path_label(virtual_env)}")


def _render_job_resource_detail(job: dict[str, object]) -> None:
    resource_summary = _resource_summary(job)
    if resource_summary:
        _cli.console.print(f"Memory: {resource_summary}")


def _resilience_summary_lines(job: dict[str, object]) -> tuple[str, ...]:
    """Return adapter-ready lines from the canonical resilience object."""
    resilience = job.get("resilience")
    if not isinstance(resilience, dict):
        return ()
    data = cast("dict[str, object]", resilience)
    lines: list[str] = []
    if profile := data.get("support_profile"):
        lines.append(f"Index profile: {profile}")
    if generation := data.get("generation_id"):
        lines.append(f"Checkpoint generation: {generation}")
    compatible = data.get("checkpoint_compatible")
    if compatible is not None:
        lines.append(
            "Checkpoint compatible: " + ("yes" if compatible is True else "no")
        )
    lines.append(
        f"Checkpoint units: {data.get('committed_units', 0)} committed, "
        f"{data.get('replayed_units', 0)} resumed"
    )
    deadline = data.get("no_progress_remaining_seconds")
    if deadline is not None:
        lines.append(f"No-progress budget remaining: {_format_seconds(deadline)}")
    if circuit := data.get("circuit_state"):
        lines.append(f"Retry circuit: {circuit}")
    next_retry = data.get("next_retry_at")
    if isinstance(next_retry, int | float):
        lines.append(
            "Next retry: "
            + time.strftime(
                "%Y-%m-%d %H:%M:%S UTC",
                time.gmtime(float(next_retry)),
            )
        )
    peak_rss = data.get("peak_rss_mb")
    rss_ceiling = data.get("rss_ceiling_mb")
    if peak_rss is not None or rss_ceiling is not None:
        lines.append(
            f"RSS high-water / ceiling: {_format_mb(peak_rss)} / "
            f"{_format_mb(rss_ceiling)}"
        )
    peak_allocated = data.get("peak_cuda_allocated_mb")
    if peak_allocated is not None:
        lines.append(f"CUDA allocated high-water: {_format_mb(peak_allocated)}")
    peak_reserved = data.get("peak_cuda_reserved_mb")
    cuda_ceiling = data.get("cuda_ceiling_mb")
    if peak_reserved is not None or cuda_ceiling is not None:
        lines.append(
            f"CUDA reserved high-water / ceiling: {_format_mb(peak_reserved)} / "
            f"{_format_mb(cuda_ceiling)}"
        )
    if terminal := data.get("terminal_outcome"):
        lines.append(f"Index outcome: {terminal}")
    return tuple(lines)


def _render_job_resilience_detail(job: dict[str, object]) -> None:
    for line in _resilience_summary_lines(job):
        _cli.console.print(line)


def _render_job_result_detail(job: dict[str, object]) -> None:
    result = job.get("result")
    if not result:
        return
    is_failed = str(job.get("phase")) in ("error", "failed")
    label = "Error" if is_failed else "Result"
    _cli.console.print(f"{label}: {_human_result(result, failed=is_failed)}")


def render_job_detail(job: dict[str, object], *, port: int | None = None) -> None:
    if port is not None:
        _plain(address_line(port))
    _cli.console.print(f"Job {job.get('id', '')!s}")
    _cli.console.print(f"Operation: {operation_label(job)}")
    _cli.console.print(f"Project: {project_label(job)}")
    root = project_root(job)
    if root:
        _plain(f"Path: {root}")
    _cli.console.print(f"Status: {phase_label(job)}")
    _cli.console.print(f"Runtime: {_format_seconds(job.get('runtime_seconds'))}")
    _render_job_progress_detail(job)
    _render_job_degradation_detail(job)
    _render_job_initiator_detail(job)
    _render_job_runtime_detail(job)
    _render_job_resource_detail(job)
    _render_job_resilience_detail(job)
    _render_job_result_detail(job)


def render_jobs_result(
    result: dict[str, object],
    *,
    job_id: str | None,
    port: int,
    monitoring: bool = False,
    watch_text: str | None = None,
) -> None:
    jobs = jobs_from_result(result)
    if not jobs:
        _render_empty_jobs_result(
            result,
            job_id=job_id,
            port=port,
            monitoring=monitoring,
            watch_text=watch_text,
        )
        return
    if job_id:
        if len(jobs) > 1:
            _plain(
                f"Error: job id prefix {job_id} matches {len(jobs)} jobs. "
                "Use a longer prefix."
            )
            _render_jobs_feed(result, jobs, port=port)
            raise typer.Exit(2)
        first = jobs[0]
        render_job_detail(
            cast("dict[str, object]", first) if isinstance(first, dict) else {},
            port=port,
        )
        return
    _render_jobs_feed(
        result, jobs, port=port, monitoring=monitoring, watch_text=watch_text
    )
