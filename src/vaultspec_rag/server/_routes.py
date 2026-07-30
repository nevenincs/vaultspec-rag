"""HTTP resource and control routes for the resident service.

Read-only observability and exact job lifecycle control share this
service-domain REST surface rather than diverging across adapters. The routes are
registered as Starlette
:class:`~starlette.routing.Route` objects on the app assembled in
:mod:`._main` (alongside ``Route("/health")``), never as additional
ASGI wrappers. The daemon serves native REST only; the MCP stdio
client reaches these routes through ``vaultspec_rag.serviceclient``.

Gating model (ADR Constraints). The HTTP service binds to loopback only
(``127.0.0.1``), which is the real boundary; on top of that these
monitoring routes accept the per-process ``service_token`` as an
optional bearer - via ``Authorization: Bearer <token>`` or a ``?token=``
query parameter - compared in constant time against the app-scoped route
runtime token. This is a pragmatic monitoring gate, not an
auth boundary. ``/health`` stays ungated and is registered in
:mod:`._main`, not here.

This module owns the canonical ``/jobs`` CRUD and control routes - and the
whole admission pipeline a job creation goes through - plus every route with
no other natural home: logs, metrics, service state/readiness, the code-file
and vault-document readers, and the quiesce pair. It assembles the
``ROUTES`` table every other route module's handlers are registered onto.
The search, reindex/clean, storage-survey, and project/watcher route groups
live in their own sibling ``_routes_*`` modules and reach back into this one
for the canonical job-admission pipeline they build on.
"""

from __future__ import annotations

import logging
import time
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from anyio.to_thread import run_sync as _run_in_thread
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

import vaultspec_rag.server as _m

from .. import jobs as _jobs
from .._store_locks import VaultStoreLockedError
from ..job_models import JobOutcome
from ..logging_config import (
    InvalidManagedLogSourceError,
    ManagedLogsResult,
    log_event,
    managed_log_filters,
    query_managed_logs,
    render_managed_log_groups,
)
from ..service import RegistryFullError
from ..service_quiesce import (
    ServiceQuiesceTransitionConflictError,
    ServiceQuiesceTransitionWaitTimeoutError,
)
from ._auth import require_token
from ._routes_jobs import (
    JobFilter,
    _clamp_limit,
    _job_matches,
    _job_summary,
    _job_with_liveness,
    _machine_pressure,
    _normalise_filter_value,
    _normalise_job_source_filter,
    _parse_since_seconds,
    _prioritise_running_jobs,
)
from ._routes_registry import (
    evict_project_route,
    get_watcher_state_route,
    list_projects_route,
    reconfigure_watcher_route,
    start_watcher_route,
    stop_watcher_route,
)
from ._routes_reindex import clean_route, reindex_route
from ._routes_search import search_route
from ._routes_storage import storage_survey_route
from ._runtime import get_request_runtime
from ._search_activity import DEFAULT_SEARCH_ACTIVITY_ROWS, SearchActivityFilters
from ._state import search_activity_ledger
from ._utils import (
    _BAD_REQUEST_MISSING_ROOT,
    _TRUTHY_QUERY_VALUES,
    ProjectRootRequiredError,
    _resolve_root,
)

if TYPE_CHECKING:
    from starlette.requests import Request

    from ..indexer._codebase_indexer import CodeIndexPreflight
    from ..indexer._document_indexer import DocumentIndexPreflight
    from ..job_models import JobInitiator, JobSpec
    from ..service_quiesce import QuiesceSnapshot

logger = logging.getLogger("vaultspec_rag.server")

# The admissible desired-state control modes, mapped to themselves so a raw
# request string resolves to the typed mode without an unchecked cast.
_CONTROL_MODES: dict[str, Literal["graceful", "force"]] = {
    "graceful": "graceful",
    "force": "force",
}


def search_summary(count: int, index_state: dict[str, object]) -> str:
    """Return the one-line summary, naming every demonstrated shortfall inline.

    An adapter that surfaces only the summary would otherwise report a
    confident count drawn from an index known to be incomplete. The deficit
    belongs in the sentence a reader actually reads, not solely in a nested
    field they have to go looking for.

    Reads the deficits through the shared walker rather than the one key this
    route happens to know about. It previously named the point shortfall
    alone, so a publication covering a fraction of the files it named - the
    case a point count cannot express - reached an agent as an unqualified
    count while the command line warned about it.
    """
    from .._index_breadth import SHORTFALL_CONSEQUENCE, shortfall_warnings

    found = f"Found {count} relevant items."
    notes = [
        f"{warning.deficit}, so {SHORTFALL_CONSEQUENCE}"
        for warning in shortfall_warnings(index_state)
    ]
    if not notes:
        return found
    return f"{found} Warning: " + "; ".join(notes) + "."


def canonical_job_snapshot() -> list[dict[str, object]]:
    """Return the canonical manager's copied, JSON-ready job view."""
    from ..jobs import get_job_manager

    return [snapshot.to_dict() for snapshot in get_job_manager().list_jobs()]


def _service_job_snapshot() -> list[dict[str, object]]:
    """Return canonical jobs plus legacy-only service activity records."""
    canonical = canonical_job_snapshot()
    canonical_ids = {str(record.get("id", "")) for record in canonical}
    legacy_only = [
        record
        for record in _jobs.snapshot()
        if str(record.get("id", "")) not in canonical_ids
    ]
    return [*canonical, *legacy_only]


class InvalidJobRequestError(ValueError):
    """Stable client-input failure for the canonical jobs resource."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def job_payload(
    request: Request,
    *,
    required: bool,
) -> dict[str, object]:
    try:
        raw = await request.json()
    except Exception as exc:
        if not required and not await request.body():
            return {}
        raise InvalidJobRequestError(
            "invalid_json",
            "The request body must be a JSON object.",
        ) from exc
    if not isinstance(raw, dict):
        raise InvalidJobRequestError(
            "invalid_json",
            "The request body must be a JSON object.",
        )
    return cast("dict[str, object]", raw)


def _job_bool(payload: dict[str, object], key: str, *, default: bool) -> bool:
    value = payload.get(key, default)
    if type(value) is not bool:
        raise InvalidJobRequestError(
            "invalid_job_spec",
            f"{key} must be a boolean when provided.",
        )
    return bool(value)


def job_string(
    payload: dict[str, object],
    key: str,
    *,
    default: str | None = None,
) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise InvalidJobRequestError(
            "invalid_job_spec",
            f"{key} must be a non-empty string.",
        )
    return value.strip()


def _validated_initiator(
    payload: dict[str, object],
    *,
    root: Path,
    default_command: str,
) -> JobInitiator:
    from ..job_models import JobInitiator

    raw = payload.get("initiator")
    if raw is None:
        initiator: dict[str, object] = {}
    elif isinstance(raw, dict):
        initiator = cast("dict[str, object]", raw)
    else:
        raise InvalidJobRequestError(
            "invalid_initiator",
            "initiator must be a JSON object when provided.",
        )
    legacy_kind = payload.get("initiator_kind", "service")
    kind = initiator.get("kind", legacy_kind)
    command = initiator.get("command", default_command)
    if not isinstance(kind, str) or not kind.strip():
        raise InvalidJobRequestError(
            "invalid_initiator",
            "initiator.kind must be a non-empty string.",
        )
    if not isinstance(command, str) or not command.strip():
        raise InvalidJobRequestError(
            "invalid_initiator",
            "initiator.command must be a non-empty string.",
        )
    return JobInitiator(
        kind=kind.strip(),
        command=command.strip(),
        project_root=str(root),
    )


def _validated_idempotency_key(
    request: Request,
    payload: dict[str, object],
    *,
    suffix: str | None = None,
) -> str | None:
    header_key = request.headers.get("Idempotency-Key")
    body_key = payload.get("idempotency_key")
    if body_key is not None and not isinstance(body_key, str):
        raise InvalidJobRequestError(
            "invalid_idempotency_key",
            "idempotency_key must be a string when provided.",
        )
    if header_key is not None and body_key is not None and header_key != body_key:
        raise InvalidJobRequestError(
            "idempotency_key_conflict",
            "The header and body idempotency keys must match.",
        )
    key = header_key if header_key is not None else body_key
    if key is None or suffix is None:
        return key
    return f"{key}:{suffix}"


async def validated_index_request(
    request: Request,
    payload: dict[str, object],
    *,
    idempotency_suffix: str | None = None,
) -> tuple[
    JobSpec,
    JobInitiator,
    bool,
    str | None,
    CodeIndexPreflight | DocumentIndexPreflight | None,
]:
    from ..job_models import JobMode, JobOperation, JobSource, JobSpec

    operation = job_string(payload, "operation", default="index")
    source = job_string(payload, "source")
    mode = job_string(payload, "mode", default="incremental")
    if operation != JobOperation.INDEX.value:
        raise InvalidJobRequestError(
            "invalid_job_spec",
            "operation must be 'index'.",
        )
    if source not in {
        JobSource.VAULT.value,
        JobSource.CODE.value,
        JobSource.DOCUMENT.value,
    }:
        raise InvalidJobRequestError(
            "invalid_job_spec",
            "source must be 'vault', 'code', or 'document'.",
        )
    if mode not in set(JobMode):
        allowed = ", ".join(f"'{member}'" for member in JobMode)
        raise InvalidJobRequestError(
            "invalid_job_spec",
            f"mode must be one of {allowed}.",
        )
    raw_root = job_string(payload, "project_root")
    if not Path(raw_root).expanduser().is_absolute():
        raise InvalidJobRequestError(
            "invalid_job_spec",
            "project_root must be an absolute path.",
        )
    try:
        root = _resolve_root(raw_root)
    except (ProjectRootRequiredError, ValueError) as exc:
        raise InvalidJobRequestError("invalid_job_spec", str(exc)) from exc
    start_paused = _job_bool(payload, "start_paused", default=False)
    spec = JobSpec(
        operation=JobOperation.INDEX,
        source=JobSource(source),
        project_root=str(root),
        mode=JobMode(mode),
    )
    admission = await _validate_index_job_spec(spec)
    initiator = _validated_initiator(
        payload,
        root=root,
        default_command="http_jobs_create",
    )
    return (
        spec,
        initiator,
        start_paused,
        _validated_idempotency_key(request, payload, suffix=idempotency_suffix),
        admission,
    )


async def _validate_index_job_spec(
    spec: JobSpec,
) -> CodeIndexPreflight | DocumentIndexPreflight | None:
    """Resolve domain admission before durable job mutation."""
    from .._job_errors import JobError
    from ..job_models import JobSource
    from ..jobs import validate_code_job_admission, validate_document_job_admission

    if spec.project_root is None or spec.source is JobSource.VAULT:
        return None
    try:
        validator = (
            validate_code_job_admission
            if spec.source is JobSource.CODE
            else validate_document_job_admission
        )
        return await _run_in_thread(validator, Path(spec.project_root))
    except JobError as exc:
        # ``exc.detail``, never ``str(exc)``: the exception text carries the
        # kind as a prefix so the typed identity survives the background-job
        # text boundary, and the kind is already travelling separately as the
        # response code. Rendering both concatenates the kind twice.
        raise InvalidJobRequestError(
            exc.error_kind.value,
            exc.detail,
        ) from exc
    except ValueError as exc:
        raise InvalidJobRequestError(
            "invalid_job_spec",
            str(exc),
        ) from exc


def _admission_preflight(preflight: CodeIndexPreflight) -> dict[str, object]:
    """Project one bounded structured scan onto the HTTP response surface."""
    scan = preflight.scan
    return {
        "count": len(scan.files),
        "policy_fingerprint": scan.policy_fingerprint,
        "measurement": {
            "source_files": scan.measurement.source_files,
            "source_bytes": scan.measurement.source_bytes,
            "generated_chunks": scan.measurement.generated_chunks,
            "weighted_bytes": scan.measurement.weighted_bytes,
            "extracted_bytes": scan.measurement.extracted_bytes,
            "queue_bytes": scan.measurement.queue_bytes,
            "rss_bytes": scan.measurement.rss_bytes,
            "cuda_bytes": scan.measurement.cuda_bytes,
        },
        "counts": [count.as_payload() for count in scan.counts],
        "samples": [sample.as_payload() for sample in scan.samples],
    }


def index_admission_preflight(
    preflight: CodeIndexPreflight | DocumentIndexPreflight,
) -> dict[str, object]:
    """Project exact code or document admission without reclassification."""
    from ..indexer._codebase_indexer import CodeIndexPreflight

    if isinstance(preflight, CodeIndexPreflight):
        return _admission_preflight(preflight)
    fingerprints = preflight.policy.fingerprints.per_kind.document
    return {
        "count": len(preflight.files),
        "policy_fingerprint": fingerprints.membership,
        "samples": [
            path.relative_to(preflight.root_dir).as_posix()
            for path in preflight.files[:100]
        ],
    }


def job_outcome_status(code: str) -> int:
    if code.startswith("invalid_") and code != "invalid_transition":
        return 400
    if code.startswith("persistence_") or code in {
        "dispatch_loop_unresponsive",
        "dispatch_stopped",
        "event_loop_required",
    }:
        return 503
    status_codes = {
        "job_not_found": 404,
        "job_capacity_exceeded": 429,
        "corpus_limit_exceeded": 422,
        "profile_requirements_not_met": 422,
        "disk_preflight_failed": 507,
        "active_job_exists": 409,
        "idempotency_key_conflict": 409,
        "invalid_transition": 409,
        "job_id_conflict": 409,
        "job_not_retryable": 409,
        "job_not_terminal": 409,
        "revision_conflict": 409,
        "force_not_supported": 409,
        "force_termination_unavailable": 409,
    }
    return status_codes.get(code, 500)


def job_error(
    command: str,
    code: str,
    message: str,
    *,
    extra: dict[str, object] | None = None,
) -> JSONResponse:
    from ..job_models import JobOutcomeStatus

    return _job_response(
        JobOutcome(
            command=command,
            status=JobOutcomeStatus.ERROR,
            code=code,
            message=message,
        ),
        extra=extra,
    )


def _job_response(
    outcome: JobOutcome,
    *,
    location: bool = False,
    extra: dict[str, object] | None = None,
) -> JSONResponse:
    from ..job_models import JobOutcomeStatus

    payload = outcome.to_dict()
    payload["ok"] = outcome.status is not JobOutcomeStatus.ERROR
    if outcome.status is JobOutcomeStatus.ERROR:
        payload["error"] = outcome.code
        status_code = job_outcome_status(outcome.code)
    else:
        status_code = 202 if outcome.status is JobOutcomeStatus.ACCEPTED else 200
    if extra:
        payload.update(extra)
    headers: dict[str, str] | None = None
    if location and outcome.job is not None:
        headers = {"Location": f"/jobs/{outcome.job.id}"}
    return JSONResponse(payload, status_code=status_code, headers=headers)


async def activate_index_job(
    outcome: JobOutcome,
    preflight: CodeIndexPreflight | DocumentIndexPreflight | None,
) -> JobOutcome:
    from ..indexer._codebase_indexer import CodeIndexPreflight
    from ..indexer._document_indexer import DocumentIndexPreflight
    from ..job_models import JobSource
    from ..jobs import activate_index_job

    source = outcome.job.spec.source if outcome.job is not None else None
    return await activate_index_job(
        outcome,
        code_preflight=(
            preflight
            if source is JobSource.CODE and isinstance(preflight, CodeIndexPreflight)
            else None
        ),
        document_preflight=(
            preflight
            if source is JobSource.DOCUMENT
            and isinstance(preflight, DocumentIndexPreflight)
            else None
        ),
    )


def _normalise_controllable_filter(raw: str | None) -> bool | None:
    value = _normalise_filter_value(raw)
    if value is None:
        return None
    if value in _TRUTHY_QUERY_VALUES:
        return True
    if value in {"0", "false", "no"}:
        return False
    raise InvalidJobRequestError(
        "invalid_filter",
        "controllable must be true or false when provided.",
    )


async def jobs_route(request: Request) -> JSONResponse:
    """Token-gated read-only ``GET /jobs`` returning the activity snapshot.

    Returns the newest-first :mod:`._jobs` registry snapshot as JSON -
    parity with the ``get_jobs`` MCP tool. Read-only: it never mutates
    the registry. An optional ``?limit=N`` query parameter caps the
    number of returned records (newest first).

    Args:
        request: The incoming Starlette request.

    Returns:
        A ``JSONResponse`` of ``{"jobs": [...]}``, or the
        ``require_token`` 401 ``JSONResponse``.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    registry = get_request_runtime(request).registry
    records = _service_job_snapshot()
    phase = _normalise_filter_value(request.query_params.get("phase"))
    state = _normalise_filter_value(request.query_params.get("state"))
    desired_state = _normalise_filter_value(request.query_params.get("desired_state"))
    source = _normalise_job_source_filter(request.query_params.get("source"))
    trigger = _normalise_filter_value(request.query_params.get("trigger"))
    query = _normalise_filter_value(request.query_params.get("query"))
    job_id = _normalise_filter_value(request.query_params.get("job_id"))
    failed = (
        _normalise_filter_value(request.query_params.get("failed"))
        in _TRUTHY_QUERY_VALUES
    )
    since_seconds = _parse_since_seconds(request.query_params.get("since"))
    try:
        controllable = _normalise_controllable_filter(
            request.query_params.get("controllable")
        )
    except InvalidJobRequestError as exc:
        return job_error("list", exc.code, str(exc))
    now = time.time()
    filtered_records = [
        _job_with_liveness(record, now=now)
        for record in records
        if _job_matches(
            record,
            JobFilter(
                phase=phase,
                source=source,
                trigger=trigger,
                query=query,
                failed=failed,
                job_id=job_id,
                since_seconds=since_seconds,
                now=now,
                state=state,
                desired_state=desired_state,
                controllable=controllable,
            ),
        )
    ]
    filtered_records = _prioritise_running_jobs(filtered_records)
    limit = _clamp_limit(request.query_params.get("limit"))
    if limit is not None:
        filtered_records = filtered_records[:limit] if limit > 0 else []
    return JSONResponse(
        {
            "jobs": filtered_records,
            "total": len(records),
            "returned": len(filtered_records),
            "summary": _job_summary(records, now=now),
            "quiesce": registry.quiesce_snapshot().as_envelope(),
            # Machine-wide GPU pressure beside the work list, so a header can
            # show the card's condition without a request of its own. Served
            # from a short-lived cache; every measurement is null where this
            # host cannot measure, and the key itself marks a daemon that
            # reports at all.
            "gpu": _jobs.gpu_pressure_snapshot(now=now),
            # The machine-wide pressure tier beside the GPU reading: same
            # probes, folded through hysteresis into one verdict. Additive -
            # the key's absence marks a daemon that predates the tier - and
            # purely informational: nothing acts on it.
            "pressure": _machine_pressure(records, now=now),
            # A different thing from both blocks above: whether the device
            # will actually admit a new model load right now, against the
            # configured floor. Synchronous and fail-fast, not a display
            # reading and not folded through hysteresis - an operator watching
            # this listing can see the one fact that decides whether the next
            # load or test run is refused. Null when this host's reading could
            # not be taken; the key's absence marks a daemon that predates it.
            "device_load": _jobs.device_load_snapshot(now=now),
            "filters": {
                "phase": phase,
                "state": state,
                "desired_state": desired_state,
                "controllable": controllable,
                "source": source,
                "trigger": trigger,
                "query": query,
                "failed": failed,
                "job_id": job_id,
                "since": since_seconds,
                "limit": limit,
            },
        }
    )


async def search_activity_route(request: Request) -> JSONResponse:
    """Return token-gated, bounded active and recent served-search activity."""
    denied = require_token(request)
    if denied is not None:
        return denied
    raw_root = request.query_params.get("root")
    root = raw_root.strip() if raw_root is not None else None
    raw_request_id = request.query_params.get("request_id")
    request_id = raw_request_id.strip() if raw_request_id is not None else None
    raw_since = request.query_params.get("since")
    try:
        since = float(raw_since) if raw_since is not None else None
    except ValueError:
        since = None
    return JSONResponse(
        search_activity_ledger().snapshot(
            include_query=True,
            filters=SearchActivityFilters(
                state=_normalise_filter_value(request.query_params.get("state")),
                search_type=_normalise_filter_value(request.query_params.get("type")),
                root=root or None,
                request_id=request_id or None,
                since=since,
                # Bounded by default: an absent limit means the caller
                # named none, not that they want every retained record.
                limit=_clamp_limit(request.query_params.get("limit"))
                or DEFAULT_SEARCH_ACTIVITY_ROWS,
            ),
        )
    )


async def create_job_route(request: Request) -> JSONResponse:
    """Admit one validated canonical index job."""
    denied = require_token(request)
    if denied is not None:
        return denied
    try:
        payload = await job_payload(request, required=True)
        (
            spec,
            initiator,
            start_paused,
            idempotency_key,
            admission,
        ) = await validated_index_request(request, payload)
    except InvalidJobRequestError as exc:
        return job_error("create", exc.code, str(exc))

    from ..jobs import get_job_manager

    manager = get_job_manager()
    outcome = await _run_in_thread(
        partial(
            manager.create,
            spec,
            initiator,
            start_paused=start_paused,
            idempotency_key=idempotency_key,
        )
    )
    outcome = await activate_index_job(outcome, admission)
    return _job_response(
        outcome,
        location=True,
        extra=(
            {"admission": index_admission_preflight(admission)}
            if admission is not None
            else None
        ),
    )


async def job_detail_route(request: Request) -> JSONResponse:
    """Return one full, exact-ID job resource from either registry.

    Resolves against the same union ``GET /jobs`` lists. Reading only canonical
    history here is what made an activity record listable but unaddressable,
    and every control verb resolves through this route.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    from ..jobs import find_job

    job_id = str(request.path_params["job_id"])
    record = find_job(job_id)
    if record is None:
        return job_error("get", "job_not_found", "The job was not found.")
    return JSONResponse(
        {
            "ok": True,
            "job": _job_with_liveness(record, now=time.time()),
        }
    )


def _validated_expected_revision(payload: dict[str, object]) -> int | None:
    raw = payload.get("expected_revision")
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise InvalidJobRequestError(
            "invalid_revision",
            "expected_revision must be a positive integer when provided.",
        )
    return raw


async def set_job_desired_state_route(request: Request) -> JSONResponse:
    """Apply one exact, revision-aware desired-state transition."""
    denied = require_token(request)
    if denied is not None:
        return denied
    from ..job_models import DesiredJobState

    try:
        payload = await job_payload(request, required=True)
        state = job_string(payload, "state")
        mode = job_string(payload, "mode", default="graceful")
        if state not in set(DesiredJobState):
            allowed = ", ".join(f"'{member}'" for member in DesiredJobState)
            raise InvalidJobRequestError(
                "invalid_desired_state",
                f"state must be one of {allowed}.",
            )
        control_mode = _CONTROL_MODES.get(mode)
        if control_mode is None:
            raise InvalidJobRequestError(
                "invalid_control_mode",
                "mode must be 'graceful' or 'force'.",
            )
        expected_revision = _validated_expected_revision(payload)
    except InvalidJobRequestError as exc:
        return job_error("set_desired_state", exc.code, str(exc))

    from ..jobs import get_job_manager

    outcome = await get_job_manager().set_desired_state_async(
        str(request.path_params["job_id"]),
        DesiredJobState(state),
        expected_revision=expected_revision,
        mode=control_mode,
    )
    return _job_response(outcome, location=outcome.job is not None)


async def retry_job_route(request: Request) -> JSONResponse:
    """Create and activate one linked retry from exact terminal history."""
    denied = require_token(request)
    if denied is not None:
        return denied
    try:
        payload = await job_payload(request, required=False)
    except InvalidJobRequestError as exc:
        return job_error("retry", exc.code, str(exc))

    from ..jobs import get_job_manager

    manager = get_job_manager()
    parent = manager.get(str(request.path_params["job_id"]))
    admission = None
    if parent is not None:
        try:
            admission = await _validate_index_job_spec(parent.spec)
        except InvalidJobRequestError as exc:
            return job_error("retry", exc.code, str(exc))
    initiator = None
    if parent is not None and ("initiator" in payload or "initiator_kind" in payload):
        try:
            root = Path(str(parent.spec.project_root))
            initiator = _validated_initiator(
                payload,
                root=root,
                default_command="http_job_retry",
            )
        except InvalidJobRequestError as exc:
            return job_error("retry", exc.code, str(exc))
    outcome = await _run_in_thread(
        partial(
            manager.retry,
            str(request.path_params["job_id"]),
            initiator=initiator,
        )
    )
    outcome = await activate_index_job(outcome, admission)
    return _job_response(
        outcome,
        location=True,
        extra=(
            {"admission": index_admission_preflight(admission)}
            if admission is not None
            else None
        ),
    )


async def delete_job_route(request: Request) -> JSONResponse:
    """Delete one exact terminal-history resource without cancelling work."""
    denied = require_token(request)
    if denied is not None:
        return denied
    from ..jobs import delete_job

    outcome = await _run_in_thread(
        delete_job,
        str(request.path_params["job_id"]),
    )
    return _job_response(outcome)


async def logs_route(request: Request) -> PlainTextResponse | JSONResponse:
    """Token-gated read-only ``GET /logs`` returning grouped log text.

    Returns bounded service, Qdrant, or all-source sections selected by
    ``?source=``. ``all`` is grouped and never presented as a global timeline.

    Args:
        request: The incoming Starlette request.

    Returns:
        A ``PlainTextResponse`` with the joined log lines, or the
        ``require_token`` 401 ``JSONResponse``.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    result = await _managed_logs_for_request(request)
    if isinstance(result, JSONResponse):
        return result
    return PlainTextResponse(render_managed_log_groups(result["groups"]))


async def _managed_logs_for_request(
    request: Request,
) -> ManagedLogsResult | JSONResponse:
    """Read, filter, and shape one bounded managed-log request."""
    lines = request.query_params.get("lines")
    source = request.query_params.get("source", "all")
    # The route reads the query string; which filters are accepted, and what
    # counts as an empty one, belongs to the managed-log contract. Restating
    # that here is how the HTTP boundary and the CLI come to disagree about
    # whether a whitespace-only --contains filters anything.
    filters = managed_log_filters(
        job_id=request.query_params.get("job_id"),
        contains=request.query_params.get("contains"),
    )
    try:
        # Reading, filtering, and byte-bounded shaping are one service-domain
        # operation and stay off the event loop for both live and offline parity.
        return await _run_in_thread(
            partial(query_managed_logs, lines, source=source, **filters)
        )
    except InvalidManagedLogSourceError as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": "invalid_log_source",
                "message": str(exc),
            },
            status_code=400,
        )


async def metrics_route(request: Request) -> PlainTextResponse | JSONResponse:
    """Token-gated read-only ``GET /metrics`` in Prometheus text format.

    Emits the ``0.0.4`` text exposition format produced inline by
    :func:`~vaultspec_rag.server.render_prometheus` (counters/gauges
    incremented by the search/reindex tool paths; GPU memory read
    on-demand at scrape time). No background collector thread, no
    ``prometheus_client`` dependency. Read-only.

    Args:
        request: The incoming Starlette request.

    Returns:
        A ``PlainTextResponse`` with the Prometheus exposition text, or
        the ``require_token`` 401 ``JSONResponse``.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    return PlainTextResponse(
        _m.render_prometheus(),
        media_type="text/plain; version=0.0.4",
    )


async def get_service_state_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    project_root = request.query_params.get("project_root")
    import vaultspec_rag

    from ._utils import _resolve_root

    try:
        root = _resolve_root(project_root)
    except ProjectRootRequiredError:
        return _BAD_REQUEST_MISSING_ROOT

    with _m._watcher_lock:
        watching_roots = [str(r) for r in _m._watcher_tasks]
    registry = get_request_runtime(request).registry

    def _run() -> dict[str, object]:
        return vaultspec_rag.get_service_state(
            root,
            registry=registry,
            watching_roots=watching_roots,
        )

    from anyio.to_thread import run_sync as _run_in_thread

    res = await _run_in_thread(_run)
    return JSONResponse(res)


async def get_readiness_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    import vaultspec_rag

    res = await _run_in_thread(vaultspec_rag.get_readiness)
    return JSONResponse(res)


async def code_file_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    payload = await request.json()
    path = payload.get("path")
    project_root = payload.get("project_root")
    from ._utils import _resolve_root

    try:
        root = _resolve_root(project_root)
    except ProjectRootRequiredError:
        return _BAD_REQUEST_MISSING_ROOT

    def _run():
        try:
            root_resolved = root.resolve()
            full_path = (root_resolved / path).resolve()
            if not full_path.is_relative_to(root_resolved):
                return {"error": f"path '{path}' is outside the workspace"}
            from ._utils import _is_sensitive_path

            if _is_sensitive_path(path):
                return {"error": "access denied"}
            if not full_path.exists():
                return {"error": f"File '{path}' not found"}
            max_read_size = 10 * 1024 * 1024
            if full_path.stat().st_size > max_read_size:
                return {"error": f"File '{path}' exceeds maximum read size of 10 MB"}
            return {"content": full_path.read_text(encoding="utf-8")}
        except Exception as e:
            return {"error": str(e)}

    from anyio.to_thread import run_sync as _run_in_thread

    res = await _run_in_thread(_run)
    return JSONResponse(res)


async def benchmark_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    payload = await request.json()
    project_root = payload.get("project_root")
    n_queries = payload.get("n_queries", 20)
    from ._utils import _resolve_root

    try:
        root = _resolve_root(project_root)
    except ProjectRootRequiredError:
        return _BAD_REQUEST_MISSING_ROOT

    registry = get_request_runtime(request).registry

    def _run():
        import vaultspec_rag

        return vaultspec_rag.run_benchmark(
            root,
            n_queries=n_queries,
            registry=registry,
        )

    from anyio.to_thread import run_sync as _run_in_thread

    res = await _run_in_thread(_run)
    return JSONResponse(res)


async def quality_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied

    registry = get_request_runtime(request).registry

    def _run():
        import vaultspec_rag

        return vaultspec_rag.run_quality_probe(registry=registry)

    from anyio.to_thread import run_sync as _run_in_thread

    res = await _run_in_thread(_run)
    return JSONResponse(res)


async def logs_json_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    result = await _managed_logs_for_request(request)
    if isinstance(result, JSONResponse):
        return result
    return JSONResponse(result)


async def vault_document_route(request: Request) -> JSONResponse:
    """Token-gated ``POST /vault-document`` returning a single vault doc.

    Accepts ``{"doc_id": "...", "project_root": "..."}`` and returns
    ``{"content": "..."}`` on success, or
    ``{"ok": false, "error": "not_found"}`` when no matching document
    exists.

    Args:
        request: The incoming Starlette request.

    Returns:
        A ``JSONResponse`` with the document content, or a structured
        error response.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    payload = await request.json()
    doc_id = payload.get("doc_id")
    project_root = payload.get("project_root")

    if not doc_id:
        return JSONResponse(
            {"ok": False, "error": "bad_request", "message": "doc_id is required"},
            status_code=400,
        )

    try:
        root = _resolve_root(project_root)
    except ProjectRootRequiredError:
        return _BAD_REQUEST_MISSING_ROOT

    registry = get_request_runtime(request).registry

    def _run() -> dict[str, Any]:
        try:
            with registry.lease(root) as slot:
                doc = slot.store.get_by_id(doc_id)
                if not doc:
                    return {"ok": False, "error": "not_found"}
                return {"content": doc.get("content", "")}
        except RegistryFullError as exc:
            return _m._registry_full_error_dict(exc, registry)
        except VaultStoreLockedError as exc:
            return _m._local_store_locked_error_dict(exc)

    result = await _run_in_thread(_run)
    return JSONResponse(result)


def _quiesce_envelope(
    *,
    achieved: bool,
    status: str,
    snapshot: QuiesceSnapshot,
    message: str | None = None,
) -> JSONResponse:
    """Emit the one quiesce envelope, on the achieved and failed exits alike.

    Every exit carries the same ``ok``/``status``/``quiesce`` shape so an
    adapter branches on ``ok`` alone.  A failure adds ``error`` and
    ``message``: the operator asked for a state change and did not get it,
    and the reason is the whole content of that answer.  The daemon answered
    in every one of these cases, so the transport status stays 200 and the
    achieved/failed distinction lives in the body - a broker pausing
    speculatively must be able to tell a refused lifecycle request from a
    gateway that never reached the service.
    """
    log_event(
        logger,
        "service.quiesce",
        status,
        fields={
            "state": snapshot.state.value,
            "safe_to_borrow_gpu": snapshot.safe_to_borrow_gpu,
        },
    )
    payload: dict[str, object] = {
        "ok": achieved,
        "status": status,
        "quiesce": snapshot.as_envelope(),
    }
    if not achieved:
        payload["error"] = status
        payload["message"] = (
            message
            if message is not None
            else _quiesce_reason(
                status,
                snapshot,
            )
        )
        payload["retryable"] = True
    return JSONResponse(payload)


def _quiesce_reason(status: str, snapshot: QuiesceSnapshot) -> str:
    """Describe an unachieved transition from the controller's own evidence."""
    failure_reason = snapshot.failure_reason
    held = f"the service is {snapshot.state.value!r}"
    if failure_reason is not None:
        return f"Quiesce transition {status!r} left {held}: {failure_reason}."
    return f"Quiesce transition {status!r} left {held}."


async def _quiesce_route(request: Request, *, pause: bool) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    registry = get_request_runtime(request).registry
    try:
        if pause:
            transition = await _run_in_thread(
                partial(registry.quiesce_resources, timeout_seconds=5.0),
            )
        else:
            transition = await _run_in_thread(registry.resume_resources)
    except (
        ServiceQuiesceTransitionConflictError,
        ServiceQuiesceTransitionWaitTimeoutError,
    ) as exc:
        return _quiesce_envelope(
            achieved=False,
            status=exc.code,
            snapshot=exc.snapshot,
            message=str(exc),
        )
    except Exception as exc:
        return _quiesce_envelope(
            achieved=False,
            status="quiesce_transition_failed",
            snapshot=registry.quiesce_snapshot(),
            message=f"{exc.__class__.__name__}: {exc}",
        )
    return _quiesce_envelope(
        achieved=transition.achieved,
        status=transition.code.value,
        snapshot=transition.snapshot,
    )


async def pause_service_route(request: Request) -> JSONResponse:
    """Token-gated ``POST /pause`` holding the whole daemon at safe points.

    Idempotent: pausing an already-paused service reports
    ``already_paused`` with HTTP 200. Quiesce is a hold, never a stop -
    the daemon stays alive and ``POST /resume`` releases it.
    """
    return await _quiesce_route(request, pause=True)


async def resume_service_route(request: Request) -> JSONResponse:
    """Token-gated ``POST /resume`` releasing a held daemon.

    Idempotent: resuming an already-running service reports
    ``already_running`` with HTTP 200.
    """
    return await _quiesce_route(request, pause=False)


ROUTES: list[Route] = [
    Route("/logs", logs_route, methods=["GET"]),
    Route("/logs/json", logs_json_route, methods=["GET"]),
    Route("/jobs", jobs_route, methods=["GET"]),
    Route("/jobs", create_job_route, methods=["POST"]),
    Route("/jobs/{job_id}", job_detail_route, methods=["GET"]),
    Route(
        "/jobs/{job_id}/desired-state",
        set_job_desired_state_route,
        methods=["PUT"],
    ),
    Route("/jobs/{job_id}/retry", retry_job_route, methods=["POST"]),
    Route("/jobs/{job_id}", delete_job_route, methods=["DELETE"]),
    Route("/metrics", metrics_route, methods=["GET"]),
    Route("/readiness", get_readiness_route, methods=["GET"]),
    Route("/search", search_route, methods=["POST"]),
    Route("/search-activity", search_activity_route, methods=["GET"]),
    Route("/reindex", reindex_route, methods=["POST"]),
    Route("/clean", clean_route, methods=["POST"]),
    Route("/projects", list_projects_route, methods=["GET"]),
    Route("/projects/evict", evict_project_route, methods=["POST"]),
    Route("/watcher", get_watcher_state_route, methods=["GET"]),
    Route("/watcher/start", start_watcher_route, methods=["POST"]),
    Route("/watcher/stop", stop_watcher_route, methods=["POST"]),
    Route("/watcher/reconfigure", reconfigure_watcher_route, methods=["POST"]),
    Route("/pause", pause_service_route, methods=["POST"]),
    Route("/resume", resume_service_route, methods=["POST"]),
    Route("/service-state", get_service_state_route, methods=["GET"]),
    Route("/storage/survey", storage_survey_route, methods=["GET"]),
    Route("/code-file", code_file_route, methods=["POST"]),
    Route("/vault-document", vault_document_route, methods=["POST"]),
    Route("/benchmark", benchmark_route, methods=["POST"]),
    Route("/quality", quality_route, methods=["POST"]),
]
