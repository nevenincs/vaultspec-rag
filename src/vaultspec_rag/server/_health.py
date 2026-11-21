"""The raw ``/health`` endpoint and the verdict it reports.

Readiness and degradation are authored here once, from the registry, the vector
store's runtime state, the quiesce controller and the job rollup, so the CLI,
the MCP surface and start-up warnings all read the same coded reasons.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Final, cast

from anyio.to_thread import run_sync as _run_in_thread

import vaultspec_rag.server as _m

from .._job_errors import JobErrorKind
from .._runtime_identity import interpreter_fields
from ..capabilities import backend_capabilities_dict
from ..operator_state._models import Degradation
from ..operator_state._service import DegradationReason, HealthVerdict
from ..service_quiesce import QuiesceState
from ._runtime import get_request_runtime

if TYPE_CHECKING:
    from starlette.requests import Request

    from ..qdrant_runtime._constants import QdrantRuntimeState
    from ..service import ServiceHealth
    from ..service_quiesce import QuiesceSnapshot


def _initial_health_verdict(reg_health: ServiceHealth, *, held: bool) -> HealthVerdict:
    """Choose the verdict before infrastructure degradation is folded in.

    A held service is neither ready nor broken, so it gets its own answer rather
    than the closest of three that do not fit it.
    """
    if held:
        return HealthVerdict.PAUSED
    if reg_health["model_loaded"]:
        return HealthVerdict.READY
    return HealthVerdict.DEGRADED if _m._start_time > 0 else HealthVerdict.ERROR


def _service_health_status(
    reg_health: ServiceHealth,
    qdrant_state: QdrantRuntimeState,
    quiesce: QuiesceSnapshot,
) -> tuple[HealthVerdict, list[Degradation]]:
    """Resolve service readiness and its infrastructure degradation reasons.

    A held service is reported as held rather than as broken.  Pause releases
    resident GPU components on purpose, so inferring the verdict from model
    residency alone reported the pause's own success criterion as a fault and
    sent operators to a repair command for a service with nothing wrong with it.
    The controller is asked first, and its answer wins: ``ready``, ``degraded``
    and ``error`` all describe a service that is trying to serve, which a
    deliberately held one is not.
    """
    held = quiesce.state is not QuiesceState.RUNNING
    status = _initial_health_verdict(reg_health, held=held)
    degradations: list[Degradation] = []
    # Absent models are a fault only when nobody asked for them to be absent.
    if not reg_health["model_loaded"] and not held:
        degradations.append(
            Degradation(
                reason=DegradationReason.MODELS_NOT_LOADED,
                detail="embedding models are not loaded",
            )
        )
    if qdrant_state.mode == "server" and not qdrant_state.alive:
        degradations.append(
            Degradation(
                reason=DegradationReason.VECTOR_SERVICE_UNAVAILABLE,
                detail="the configured vector service is not live"
                + qdrant_state.restart_refusal_note,
            )
        )
        if status is HealthVerdict.READY:
            status = HealthVerdict.DEGRADED
    # A collection whose vectors were built by a different model still answers
    # every query and still looks healthy by every other signal, which is
    # exactly why it has to be said here: this is the only place live-service
    # degradation is authored, so a reason added here is the one that reaches
    # status, start warnings, and the MCP surface without a second renderer.
    nonconforming = reg_health.get("nonconforming") or []
    if nonconforming:
        degradations.append(
            Degradation(
                reason=DegradationReason.NONCONFORMING,
                detail=f"{len(nonconforming)} indexed collection(s) were built by a "
                f"different embedding model than the one configured, so their "
                f"search ranking is unreliable: {', '.join(nonconforming[:3])}",
            )
        )
        if status is HealthVerdict.READY:
            status = HealthVerdict.DEGRADED
    # A quarantined collection was moved out of the store's active set after it
    # failed to load. The server is alive, ready, and answering - the affected
    # root just returns empty or partial results, with nothing but a log line to
    # say why. That is the whole reason it has to be reported here: quarantined
    # data must never sit behind a ready status.
    quarantined = quarantined_collections(qdrant_state)
    if quarantined:
        degradations.append(
            Degradation(
                reason=DegradationReason.QUARANTINED,
                detail=f"{len(quarantined)} collection(s) are quarantined out of "
                "the vector store after failing to load, so the roots that own "
                f"them return incomplete results: {', '.join(quarantined[:3])}",
            )
        )
        if status is HealthVerdict.READY:
            status = HealthVerdict.DEGRADED
    # A permitted upgrade is still a one-way door. The store opened, every
    # probe is green, and nothing anywhere records that the previous binary can
    # no longer read it - which is exactly what an operator needs to know
    # before attempting to go back. Reported for this daemon generation only,
    # because the open has already rewritten the stamp.
    migrated_from = store_migrated_from(qdrant_state)
    if migrated_from:
        degradations.append(
            Degradation(
                reason=DegradationReason.STORE_CARRIED_ACROSS,
                detail=f"the vector store was carried across a server version change "
                f"(written by {migrated_from}, now opened by {qdrant_state.version}), "
                f"so the binary that wrote it can no longer read this store",
            )
        )
        if status is HealthVerdict.READY:
            status = HealthVerdict.DEGRADED
    return status, degradations


def quarantined_collections(qdrant_state: QdrantRuntimeState) -> list[str]:
    """Return the quarantine entries the runtime state reports, if any.

    The runtime state is the one place this fact is produced, and it reaches
    both the degradation author above and the health payload's structured
    signal through this accessor rather than through two readings of the same
    ``extra`` key.
    """
    entries = qdrant_state.extra.get("quarantined")
    if not isinstance(entries, list):
        return []
    return [str(entry) for entry in cast("list[object]", entries)]


def store_migrated_from(qdrant_state: QdrantRuntimeState) -> str:
    """Return the version this store was carried across from, if any.

    Empty whenever the open did not cross a version boundary, which is the
    ordinary case. Read through this accessor for the same reason the
    quarantine listing is: the runtime state produces the fact once, and both
    the degradation author and the health payload read it the same way.
    """
    migrated_from = qdrant_state.extra.get("migrated_from")
    return str(migrated_from) if isinstance(migrated_from, str) else ""


def _health_job_records() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Merge canonical jobs with legacy-only records without duplicating IDs."""
    from .. import jobs as _jobs_registry

    canonical_records = [
        snapshot.to_dict() for snapshot in _jobs_registry.get_job_manager().list_jobs()
    ]
    canonical_ids = {str(record.get("id", "")) for record in canonical_records}
    legacy_only = [
        record
        for record in _jobs_registry.snapshot()
        if str(record.get("id", "")) not in canonical_ids
    ]
    return canonical_records, [*canonical_records, *legacy_only]


def _latest_job_record(
    records: list[dict[str, object]],
) -> dict[str, object] | None:
    """Return the most recently updated record from a possibly empty list."""
    if not records:
        return None
    from ._routes_jobs import job_updated_timestamp

    return max(
        records,
        key=lambda record: job_updated_timestamp(record) or float("-inf"),
    )


def _resilience_job_health(
    record: dict[str, object] | None,
) -> dict[str, object] | None:
    """Project the bounded latest-resilience health shape."""
    if record is None:
        return None
    # "spec" is always a nested object: every job snapshot builds it as a
    # literal dict, never omitted or null. "resilience" is only ever a dict
    # here because the sole caller below filters candidates to
    # ``isinstance(record.get("resilience"), dict)`` before this record can
    # become the latest one passed in.
    return {
        "job_id": record.get("id"),
        "source": cast("dict[str, object]", record["spec"]).get("source"),
        **cast("dict[str, object]", record["resilience"]),
    }


def _uptime_seconds() -> float:
    """Return seconds elapsed since this generation's monotonic start stamp.

    ``0.0`` before a generation is stamped, which is the value the health
    payload reports for a process that has not run the lifespan.
    """
    return time.monotonic() - _m._start_time if _m._start_time > 0 else 0.0


def _generation_start_wall_clock() -> float | None:
    """Return the epoch instant this service generation began, or ``None``.

    Two independent witnesses are stamped at lifespan startup: the epoch
    reading itself, and a monotonic reading from which the epoch start can be
    re-derived at call time (``now - uptime``). Neither survives every clock
    adjustment alone - a backward step invalidates the recorded epoch stamp, a
    forward step invalidates the derived one - so the earlier of the two is
    returned. Widening the window can only make a stale failure look current,
    which is the same verdict an unbounded check would give; narrowing it would
    hide a live failure, which is the outcome worth ruling out.

    ``None`` means no generation has been stamped, which is every caller
    outside a running lifespan.
    """
    candidates: list[float] = []
    if _m._start_time > 0:
        candidates.append(time.time() - _uptime_seconds())
    if _m._start_wall_time > 0:
        candidates.append(_m._start_wall_time)
    return min(candidates) if candidates else None


def _failure_belongs_to_this_generation(record: dict[str, object]) -> bool:
    """Return whether a failed job's failure happened under the running process.

    Job records are durable and outlive the process that ran them, so the
    latest failure on file is routinely one some earlier daemon suffered, hours
    or restarts ago. Such a failure is history, not a verdict on the process
    reading it: it stays in the reported rollup, but only a failure that
    finished inside the current generation may degrade health.
    """
    from .._job_values import measurement

    generation_start = _generation_start_wall_clock()
    if generation_start is None:
        # No generation is stamped, so nothing can be ruled out of it. Report
        # the failure rather than suppress every failure a non-lifespan caller
        # could ever see.
        return True
    finished_at = measurement(record.get("finished_at"))
    if finished_at is None:
        # Missing or non-numeric stamp: a failure that cannot be placed in time
        # degrades. Under-reporting costs an operator the only signal that the
        # live service is broken; over-reporting is visible in the payload and
        # clears itself once a job completes with a usable stamp.
        return True
    return finished_at >= generation_start


#: How long an unresolved project index failure may hold the service verdict.
#: Watched projects re-index on change, so a failure nothing retried within
#: this window usually belongs to a project nobody is working in. Past it the
#: failure stays listed but stops degrading.
_FAILURE_DEGRADES_FOR_SECONDS = 3600.0

#: Failing project indexes named in the health payload; the rest are counted.
_FAILING_NAMED = 5


def _decisive_outcome(record: dict[str, object]) -> str | None:
    """Return ``succeeded`` or ``failed`` when the record proves either.

    A success proves the project's index can be built; a failure proves it
    could not. A missing or rebuild-required index is normal repository
    readiness, not a broken service, so a refusal stays in job history but
    never counts. A run an explicit rebuild's reset fenced was stopped by the
    rebuild that now owns the source, which says nothing about whether the
    index can be built either. An interrupted run left the published data
    intact, the models resident and the backend live, so serving is
    unimpaired. A
    cancelled run is an operator or watcher decision. Neither those nor a
    superseded record say whether the index can be built, so none of them may
    clear or create a failure.
    """
    from ._routes_jobs import job_state

    state = job_state(record)
    if state == "succeeded":
        return state
    if state == "failed" and record.get("error_kind") not in _NON_DECISIVE_FAILURES:
        return state
    return None


#: Failure kinds that stay in job history without proving the index broken.
_NON_DECISIVE_FAILURES: Final = frozenset(
    {JobErrorKind.FULL_REINDEX_REQUIRED, JobErrorKind.INDEX_TRANSITION}
)


def _failing_project_indexes(
    records: list[dict[str, object]],
    *,
    now: float,
) -> list[dict[str, object]]:
    """Return each project and source whose newest decisive outcome failed.

    Records are folded once per project root and source. A key fails when
    the newest record that proves anything about it is a failure, so a later
    success clears it and a later cancellation leaves it standing. Each entry
    says whether it degrades health: only a failure inside this generation
    and inside the degradation window does. Older failures stay listed so the
    operator never loses the fact. Degrading entries come first, newest
    first within each group.
    """
    from .._job_values import measurement
    from .._root_identity import canonical_root_key_or_none
    from ._routes_jobs import job_project_root, job_source, job_updated_timestamp

    newest: dict[tuple[str | None, str], tuple[float, dict[str, object]]] = {}
    for record in records:
        outcome = _decisive_outcome(record)
        if outcome is None:
            continue
        key = (
            canonical_root_key_or_none(job_project_root(record)),
            job_source(record),
        )
        stamp = job_updated_timestamp(record) or float("-inf")
        held = newest.get(key)
        # A tie between a success and a failure cannot say which came last,
        # so the failure stands: hiding a live fault costs more than reporting
        # one that a later run will clear.
        if (
            held is None
            or stamp > held[0]
            or (stamp == held[0] and outcome == "failed")
        ):
            newest[key] = (stamp, record)

    entries: list[tuple[float, dict[str, object]]] = []
    for stamp, record in newest.values():
        if _decisive_outcome(record) != "failed":
            continue
        finished_at = measurement(record.get("finished_at"))
        # A failure that cannot be placed in time degrades, for the reason
        # the generation check gives: under-reporting hides the only signal.
        recent = (
            finished_at is None or now - finished_at <= _FAILURE_DEGRADES_FOR_SECONDS
        )
        entries.append(
            (
                stamp,
                {
                    "id": record.get("id"),
                    "project_root": job_project_root(record),
                    "source": job_source(record),
                    "error_kind": record.get("error_kind"),
                    "finished_at": record.get("finished_at"),
                    "degrading": recent and _failure_belongs_to_this_generation(record),
                },
            )
        )
    entries.sort(key=lambda item: (not item[1]["degrading"], -item[0]))
    return [entry for _stamp, entry in entries]


def _failing_health(
    failing: list[dict[str, object]],
) -> tuple[dict[str, object], Degradation | None]:
    """Bound the failing list for the payload and author its degradation."""
    degrading = [entry for entry in failing if entry["degrading"]]
    payload: dict[str, object] = {
        "total": len(failing),
        "degrading": len(degrading),
        "entries": failing[:_FAILING_NAMED],
    }
    if not degrading:
        return payload, None
    first = degrading[0]
    root = first["project_root"] or "an unrecorded project"
    kind = first["error_kind"] or "unknown"
    count = len(degrading)
    more = count - 1
    detail = (
        f"{count} project index run{'s' if count != 1 else ''} failed: "
        f"{root} ({first['source']}: {kind})"
        + (f" and {more} more" if more > 0 else "")
    )
    return payload, Degradation(reason=DegradationReason.JOB_FAILED, detail=detail)


def _undispatched_job_count(now: float) -> int:
    """Count queued work that nothing has started for the stall threshold.

    Queued work is normally dispatched the moment it is queued, so work that
    has waited this long with no owner will never start by itself.
    """
    from .. import jobs as _jobs_registry
    from .._job_errors import STALL_THRESHOLD_SECONDS

    return sum(
        now - snapshot.timestamps.state_changed_at >= STALL_THRESHOLD_SECONDS
        for snapshot in _jobs_registry.get_job_manager().undispatched()
    )


def _jobs_health(*, now: float) -> tuple[dict[str, object], list[Degradation]]:
    """Build the bounded job rollup and its service degradation reasons."""
    from .. import jobs as _jobs_registry
    from ._routes_jobs import _job_summary, job_state, with_admission

    canonical_records, job_records = _health_job_records()
    summary = _job_summary(
        with_admission(job_records, _jobs_registry.get_job_manager().admission_queue()),
        now=now,
    )
    undispatched = _undispatched_job_count(now)
    failing, failed_degradation = _failing_health(
        _failing_project_indexes(job_records, now=now)
    )
    latest_resilience = _latest_job_record(
        [
            record
            for record in canonical_records
            if isinstance(record.get("resilience"), dict)
        ]
    )
    effective_operations: dict[str, int] = {}
    for record in canonical_records:
        spec = record.get("spec")
        if not isinstance(spec, dict) or job_state(record) in {
            "succeeded",
            "failed",
            "cancelled",
            "interrupted",
        }:
            continue
        typed_spec = cast("dict[str, object]", spec)
        operation = str(
            typed_spec.get("effective_mode") or typed_spec.get("mode") or "unknown"
        )
        effective_operations[operation] = effective_operations.get(operation, 0) + 1
    jobs_health: dict[str, object] = {
        "running": summary["running"],
        "working": summary["working"],
        "waiting": summary["waiting"],
        "awaiting_admission": summary["awaiting_admission"],
        "queued": summary["queued"],
        "paused": summary["paused"],
        "transitional": summary["transitional"],
        "active": summary["active"],
        "stalled": summary["stalled"],
        "undispatched": undispatched,
        "degraded": summary["degraded"],
        "effective_operations": effective_operations,
        "control_pending": summary["control_pending"],
        "states": summary["states"],
        "failing": failing,
        "resilience": _resilience_job_health(latest_resilience),
    }
    degradations: list[Degradation] = []
    if summary["stalled"]:
        degradations.append(
            Degradation(
                reason=DegradationReason.JOBS_STALLED,
                detail=f"{summary['stalled']} indexing job(s) are stalled",
            )
        )
    if undispatched:
        degradations.append(
            Degradation(
                reason=DegradationReason.JOBS_UNDISPATCHED,
                detail=(
                    f"{undispatched} queued indexing job(s) have nothing to start them"
                ),
            )
        )
    if summary["degraded"]:
        degradations.append(
            Degradation(
                reason=DegradationReason.JOBS_DEGRADED,
                detail=f"{summary['degraded']} indexing job(s) are degraded",
            )
        )
    if failed_degradation is not None:
        degradations.append(failed_degradation)
    return jobs_health, degradations


#: Stale roots named in the health detail; the rest are counted.
_STALE_ROOTS_NAMED = 5


def _stale_watcher_root_degradations() -> list[Degradation]:
    """Report watched roots that were deleted or moved, until pruned or back."""
    from .._root_presence import stale_watcher_roots

    stale = stale_watcher_roots()
    if not stale:
        return []
    named = ", ".join(record.root for record in stale[:_STALE_ROOTS_NAMED])
    more = len(stale) - _STALE_ROOTS_NAMED
    return [
        Degradation(
            reason=DegradationReason.STALE_WATCHER_ROOTS,
            detail=(
                f"{len(stale)} watched project root(s) no longer exist: {named}"
                + (f" and {more} more" if more > 0 else "")
            ),
        )
    ]


async def health_handler(request: Request) -> object:
    """Return service health as the typed health report.

    Args:
        request: The incoming Starlette request.

    Returns:
        A ``JSONResponse`` carrying the serialised :class:`HealthReport`: the
        health verdict and its coded degradations, the service-wide optional
        features, model state, identity, and uptime.
    """
    from starlette.responses import JSONResponse

    from .. import store_schema
    from .._gpu_admission import device_load_reading
    from ..config._settings import get_config
    from ..jobs import active_index_support_profiles
    from ..operator_state._models import HealthReport, ServiceFeatures
    from ..qdrant_runtime import _supervise
    from ..search._typesafe_transport import enrollment_status
    from ..serviceclient._compat import local_package_version
    from ._auth import require_token

    authenticated = False
    if request.scope.get("headers") and (
        request.headers.get("authorization") or request.query_params.get("token")
    ):
        refusal = require_token(request)
        if refusal is not None:
            return refusal
        authenticated = True
    runtime = get_request_runtime(request)
    # Cached conformance still takes store lifecycle locks shared with
    # collection I/O. A contended snapshot must not hold the serving loop.
    reg_health = await _run_in_thread(runtime.registry.health)
    quiesce_snapshot = runtime.registry.quiesce_snapshot()
    qdrant_state = _supervise.runtime_state()
    status, degradations = _service_health_status(
        reg_health,
        qdrant_state,
        quiesce_snapshot,
    )
    jobs_health, jobs_degradations = _jobs_health(now=time.time())
    degradations.extend(jobs_degradations)
    degradations.extend(await _run_in_thread(_stale_watcher_root_degradations))
    if status is HealthVerdict.READY and degradations:
        status = HealthVerdict.DEGRADED

    cfg = get_config()
    report = HealthReport(
        status=status,
        degradations=tuple(degradations),
        features=ServiceFeatures(
            typesafe=enrollment_status(),
            reranker_enabled=bool(cfg.reranker_enabled),
            reranker_loaded=reg_health["reranker_loaded"],
            sparse_enabled=bool(cfg.sparse_enabled),
            watcher_enabled=bool(cfg.watch_enabled),
            preprocess_mode=cfg.preprocess_mode,
            storage_backend="server" if cfg.effective_server_mode() else "local",
            embedding_model=cfg.embedding_model,
            sparse_model=cfg.sparse_model if cfg.sparse_enabled else None,
            reranker_model=cfg.reranker_model if cfg.reranker_enabled else None,
        ),
        models_loaded=reg_health["model_loaded"],
        project_count=reg_health["project_count"],
        # The structured signal behind the conformance degradation code. The
        # CLI derives its remediation from this, so rewording the detail costs
        # nothing.
        nonconforming=tuple(reg_health.get("nonconforming") or ()),
        pid=os.getpid(),
        parent_pid=os.getppid(),
        port=runtime.port,
        **interpreter_fields(),
        uptime_s=round(_uptime_seconds(), 2),
        # Bare storage-schema version: the cheapest ungated pre-read gate a
        # direct-Qdrant consumer can check before scrolling. The full
        # descriptor lives on /readiness.
        schema_version=store_schema.STORAGE_SCHEMA_VERSION,
        # The release discriminator a client compares before driving this
        # daemon. Distinct from schema_version (the storage shape) and from
        # the discovery file's own schema pair: this is the package release,
        # the thing that decides whether the fields a client sends are fields
        # this daemon understands.
        package_version=local_package_version(),
        # Per-process identity token. Mirrors the value written to
        # service.json. The CLI compares the two to detect PID reuse and an
        # unrelated HTTP server on the port.
        service_token=runtime.token if authenticated else None,
        jobs=jobs_health,
        qdrant=qdrant_state.to_dict(),
        quiesce=quiesce_snapshot.as_envelope(),
        device_load=device_load_reading(),
        backend_capabilities=backend_capabilities_dict(),
        support_profile=active_index_support_profiles(),
    )
    payload = report.model_dump(mode="json")
    if report.service_token is None:
        payload.pop("service_token")
    return JSONResponse(payload)
