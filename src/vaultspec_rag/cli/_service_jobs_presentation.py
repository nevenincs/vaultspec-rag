"""Human presentation for ``server jobs`` views and job detail."""

from __future__ import annotations

import math
import re
import time
from typing import cast

import typer

import vaultspec_rag.cli as _cli

from .._job_errors import STALL_THRESHOLD_SECONDS, classify_error_text, remediation
from ..jobs import measurement
from ._cli_format import (
    _format_mb,
    _format_milliseconds,
    _format_seconds,
    _path_label,
    compact_duration,
)
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


def _nested_section(
    job: dict[str, object],
    outer: str,
    inner: str,
) -> dict[str, object] | None:
    """One dict-valued *inner* section of the dict-valued *outer* block."""
    container = job.get(outer)
    if not isinstance(container, dict):
        return None
    value = cast("dict[str, object]", container).get(inner)
    return cast("dict[str, object]", value) if isinstance(value, dict) else None


def _resource_at(job: dict[str, object], key: str) -> dict[str, object] | None:
    return _nested_section(job, "resources", key)


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


def _job_superseded(job: dict[str, object]) -> bool:
    """Whether the service resolved this job through a later successful retry.

    Judged from the payload's own state strings, not a local enum: the wire
    value is the contract, and older payloads simply never carry it. A
    superseded row is resolved history - its work was delivered by a linked
    retry - so it must read as neither a failure awaiting action nor a job
    that did the work itself.
    """
    return "superseded" in (
        str(job.get("phase", "")).strip().lower(),
        str(job.get("state", "")).strip().lower(),
    )


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
        # The counter behind this step counts files whose chunks have been
        # encoded and durably written, not files handed to the chunker, so
        # the label names the completed work.
        "chunk + embed": "embedding and writing files",
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
    return _nested_section(job, "degradation_evidence", name)


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
    # A collapse keeps every recency reading fresh, so without this the row
    # would name an age of seconds as the cause of a verdict the throughput
    # actually earned.
    throughput = _throughput_phrase(job)
    parts = (base, forward, throughput)
    return f"{verdict}: {'; '.join(part for part in parts if part)}"


def _encode_evidence_line(job: dict[str, object]) -> str | None:
    forward = _evidence_section(job, "forward")
    if forward is None:
        return None
    phrase = _forward_evidence_phrase(job)
    if not phrase:
        # A CPU-bound step runs no forward pass, so its absence is the
        # expected shape of the phase there, not a finding against the job;
        # only a step the service marked as encoding turns silence into
        # "no forward pass observed".
        phrase = (
            "no forward pass expected in this phase"
            if forward.get("expected") is False
            else "no forward pass observed"
        )
    ordinal = forward.get("slice_ordinal")
    items = forward.get("items")
    # The service writes this count once per slice and never moves it, so it
    # is the slice's size and is captioned as one. Progress through those
    # items is a fraction on the encode-batch line below, never a bare count
    # here that a reader would take for the size.
    if ordinal is not None and items is not None:
        phrase += f" (slice {ordinal}, {items} items)"
    alive = forward.get("thread_alive")
    if alive is not None and forward.get("in_flight") is not True:
        phrase += "; encode thread " + ("alive" if alive is True else "dead")
    return f"Encode: {phrase}"


def _encode_budget_line(job: dict[str, object]) -> str | None:
    """The encode batch bounds the service reported, in the numbers it sent.

    Silent for a job the service published no encode state for, which is
    every job that never reached an encode stage.

    The sub-slice climb is rendered only as a fraction, and only when the
    service published both of its halves: a completed count on its own
    reads as a size, which is the reading that has to stay impossible here
    because the forward line above already names the slice's size.
    """
    encode = _evidence_section(job, "encode")
    if encode is None:
        return None
    parts: list[str] = []
    budget = measurement(encode.get("token_budget"))
    if budget is not None:
        parts.append(f"{budget:g} tokens per batch")
    items = measurement(encode.get("bucket_items"))
    if items is not None:
        parts.append(f"{items:g} items in the last batch")
    done = measurement(encode.get("items_done"))
    total = measurement(encode.get("items_total"))
    if done is not None and total is not None:
        parts.append(f"{done:g} of {total:g} items encoded")
    retries = measurement(encode.get("oom_count"))
    if retries:
        parts.append(f"{retries:g} GPU memory {'retry' if retries == 1 else 'retries'}")
    return f"Encode batch: {', '.join(parts)}" if parts else None


def _throughput_phrase(job: dict[str, object]) -> str:
    """One phrase comparing current throughput to this run's own median.

    Both numbers and the factor between them come from the service; nothing
    here decides what counts as slow.
    """
    rate = _evidence_section(job, "rate")
    if rate is None:
        return ""
    recent = measurement(rate.get("recent_per_second"))
    median = measurement(rate.get("median_per_second"))
    if recent is None or median is None:
        return ""
    phrase = f"{recent:g} per second against a {median:g} per second run median"
    ratio = measurement(rate.get("ratio"))
    if ratio is not None:
        phrase += f" ({round(ratio * 100)}% of it)"
    return phrase


def _rate_baseline_line(job: dict[str, object]) -> str | None:
    phrase = _throughput_phrase(job)
    return f"Throughput: {phrase}" if phrase else None


def _cpu_evidence_line(job: dict[str, object]) -> str | None:
    """The service process's own CPU reading - valid liveness in every phase."""
    cpu = _evidence_section(job, "cpu")
    if cpu is None:
        return None
    if cpu.get("available") is not True:
        return "Process CPU: not measurable from the service process"
    percent = cpu.get("utilization_percent")
    if isinstance(percent, int | float) and not isinstance(percent, bool):
        return f"Process CPU: {round(float(percent))}% of one core"
    # The first sample only primes the counter; the next poll carries a
    # number, so an empty reading is a warming probe, not an absent one.
    return None


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
        _encode_budget_line(job),
        _rate_baseline_line(job),
        _cpu_evidence_line(job),
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


def remaining_estimate_label(job: dict[str, object]) -> str:
    """Say how much longer the service expects this job to run.

    Three answers, kept distinct. A published value renders as a coarse
    countdown; a published null is the service declining to estimate this
    job and reads as an explicit unknown; an absent key is a daemon that
    predates the estimate and yields nothing here at all - rendering that
    as unknown would tell the operator their work is unmeasurable when
    the truth is their service does not measure. The service owns the
    number: nothing here derives a rate from raw progress.
    """
    if "estimated_remaining_seconds" not in job:
        return ""
    remaining = job.get("estimated_remaining_seconds")
    if isinstance(remaining, int | float) and not isinstance(remaining, bool):
        # Ceiling, not truncation: a countdown must never read below what
        # the service just said, and the coarse two-unit rendering already
        # removes any precision the estimate does not have.
        return f"~{compact_duration(math.ceil(max(0.0, float(remaining))))} remaining"
    return "ETA unknown"


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
    # A stalled job's estimate is measured over a window whose newest
    # samples predate the stall, so a countdown beside "no progress for
    # five minutes" is two contradictory claims; the stall wins.
    estimate = remaining_estimate_label(job) if not stale_progress else ""
    parts = [p for p in (detail, runtime_detail, estimate, stale_progress) if p]
    return "; ".join(parts) if parts else runtime_detail


def _job_summary_detail(job: dict[str, object]) -> str:
    phase = str(job.get("phase", ""))
    if phase == "running":
        return _running_job_detail(job)
    if phase in ("error", "failed"):
        result = _human_result(job.get("result"), failed=True)
        return f"error: {result}" if result else "error reported"
    if _job_superseded(job):
        # The stored result predates resolution (typically the original
        # interruption text), so rendering it would read as a failure
        # still awaiting action; the lineage note names the retry.
        return "resolved: a linked retry succeeded"
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


def _retry_lineage_notes(
    jobs: list[dict[str, object]],
    labels: dict[int, str],
) -> dict[int, str]:
    """Per-row phrases linking a retry to the job it retried, by list index.

    The service publishes the relationship as ``parent_job_id``; without
    saying it out loud, a retry reads as an unrelated job that ran briefly
    and vanished, and its interrupted parent reads as never retried. A
    child row names its parent; a parent row reports its newest retry and
    that retry's state, so an interrupted row whose retry succeeded says so.
    """
    ids = [str(job.get("id", "")) for job in jobs]
    label_by_id = {job_id: labels[index] for index, job_id in enumerate(ids) if job_id}
    notes: dict[int, str] = {}
    newest_child_by_parent: dict[str, int] = {}
    for index, job in enumerate(jobs):
        parent = job.get("parent_job_id")
        if not isinstance(parent, str) or not parent:
            continue
        notes[index] = f"retry of job {label_by_id.get(parent, parent[:8])}"
        current = newest_child_by_parent.get(parent)
        if current is None or _job_timestamp(job) >= _job_timestamp(jobs[current]):
            newest_child_by_parent[parent] = index
    for parent_id, child_index in newest_child_by_parent.items():
        parent_index = next(
            (index for index, job_id in enumerate(ids) if job_id == parent_id),
            None,
        )
        if parent_index is None:
            continue
        child = jobs[child_index]
        notes[parent_index] = (
            f"retried as job {labels[child_index]} ({phase_label(child)})"
        )
    return notes


def _shown_job_counts(jobs: list[dict[str, object]]) -> tuple[int, int, int, int]:
    active = 0
    waiting = 0
    finished = 0
    failed = 0
    for job in jobs:
        phase = str(job.get("phase", ""))
        if phase in ("error", "failed"):
            failed += 1
        elif phase == "done" or _job_superseded(job):
            # Superseded is resolved history: counting it anywhere else
            # would report either a phantom failure or uncounted work.
            finished += 1
        elif job_is_waiting(job):
            waiting += 1
        elif phase == "running":
            active += 1
    return active, waiting, finished, failed


def _machine_pressure_line(result: dict[str, object]) -> str:
    """One line naming the machine pressure tier, or nothing to say.

    Three answers, kept distinct: an absent key is a daemon that predates
    the tier and yields no line at all; a nominal tier is the healthy
    steady state and earns no line either; elevated and critical are the
    verdicts an operator must see without asking. The tier is rendered
    verbatim - the service owns the verdict.
    """
    if "pressure" not in result:
        return ""
    block = result.get("pressure")
    if not isinstance(block, dict):
        return ""
    tier = cast("dict[str, object]", block).get("tier")
    if not isinstance(tier, str) or tier in ("", "nominal"):
        return ""
    return f"Machine pressure: {tier}"


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
    pressure = _machine_pressure_line(result)
    if pressure:
        _plain(pressure)
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
    lineage_notes = _retry_lineage_notes(sorted_jobs, job_id_labels)
    for index, job in enumerate(sorted_jobs):
        job_id = job_id_labels[index]
        detail = _job_summary_detail(job)
        note = lineage_notes.get(index)
        if note:
            detail = f"{detail}; {note}" if detail else note
        _cli.console.print(
            f"{_job_prefix(job)} {_job_time_label(job)} {phase_label(job)} "
            f"{operation_label(job)}{_project_phrase(job)} (job {job_id}) - "
            f"{detail}",
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
    pressure = _machine_pressure_line(result)
    if pressure:
        # An empty page must still surface a pressured machine: the tier is
        # a machine verdict, not a property of any listed job.
        _plain(pressure)
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
    # Only work that is actually doing something now carries the line:
    # queued and admission-parked jobs have nothing to count down, and a
    # stalled job's countdown would contradict the warning above.
    if (
        str(job.get("phase", "")) == "running"
        and not job_is_waiting(job)
        and not job_awaiting_admission(job)
        and not stale_progress
    ):
        estimate = remaining_estimate_label(job)
        if estimate:
            # The exact phrase the feed uses, so the two views cannot drift
            # into naming the same estimate differently.
            _cli.console.print(estimate)


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
    if _job_superseded(job):
        # The stored result predates resolution; printing it would read as
        # a failure still awaiting action.
        _cli.console.print("Resolution: a linked retry succeeded")
        return
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
    parent = job.get("parent_job_id")
    if isinstance(parent, str) and parent:
        # Without this line a retry's detail view reads as an unrelated job.
        _cli.console.print(f"Retry of job: {parent}")
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
