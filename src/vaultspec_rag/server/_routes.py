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
query parameter - compared in constant time against
``_state._SERVICE_TOKEN``. This is a pragmatic monitoring gate, not an
auth boundary. ``/health`` stays ungated and is registered in
:mod:`._main`, not here.
"""

from __future__ import annotations

import hmac
import logging
import time
import uuid
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from anyio.to_thread import run_sync as _run_in_thread
from qdrant_client.http.exceptions import UnexpectedResponse
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

import vaultspec_rag.server as _m

from .. import jobs as _jobs
from .._operator_commands import (
    index_command,
    server_jobs_command,
    server_status_command,
)
from .._source_types import (
    INDEX_SOURCES,
    IndexSource,
    PublicSourceType,
    SourceTypeParseError,
    parse_source_type,
)
from .._store_locks import VaultStoreLockedError
from ..concurrency import get_search_limiter
from ..job_models import JobOutcome
from ..logging_config import (
    InvalidManagedLogSourceError,
    log_event,
    query_managed_logs,
    render_managed_log_groups,
)
from ..service import RegistryFullError
from ._routes_jobs import (
    _clamp_limit,
    _job_matches,
    _job_summary,
    _job_with_liveness,
    _normalise_filter_value,
    _normalise_job_source_filter,
    _parse_since_seconds,
    _prioritise_running_jobs,
)
from ._routes_logs import _log_filters_from_request
from ._routes_storage import (
    _clamp_survey_limit,
    _fetch_surveys,
    _shape_survey_payload,
)
from ._search_availability import (
    SearchResponseClassification,
    classify_qdrant_collection_disappearance,
    classify_search_response,
)
from ._utils import (
    ProjectRootRequiredError,
    _clamp_top_k,
    _resolve_root,
    _validate_query,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request

    from ..indexer._codebase_indexer import CodeIndexPreflight
    from ..indexer._document_indexer import DocumentIndexPreflight
    from ..job_control import QuiesceGate
    from ..job_models import JobInitiator, JobSpec
    from ..storage_survey import NamespaceSurvey

logger = logging.getLogger("vaultspec_rag.server")

_BAD_REQUEST_MISSING_ROOT = JSONResponse(
    {
        "ok": False,
        "error": "bad_request",
        "message": (
            "project_root is required - "
            "supply it in the request body (POST) or as a query parameter (GET)."
        ),
    },
    status_code=400,
)

_BAD_REQUEST_EMPTY_QUERY = JSONResponse(
    {
        "ok": False,
        "error": "bad_request",
        "message": (
            "query is empty - supply search text, or filter tokens such as "
            "'lang:python class:Engine' when searching by metadata alone."
        ),
    },
    status_code=400,
)

# The admissible desired-state control modes, mapped to themselves so a raw
# request string resolves to the typed mode without an unchecked cast.
_CONTROL_MODES: dict[str, Literal["graceful", "force"]] = {
    "graceful": "graceful",
    "force": "force",
}


def _bad_request_invalid_root(exc: ValueError) -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "error": "bad_request",
            "message": str(exc),
        },
        status_code=400,
    )


def _normalise_search_type(value: object) -> PublicSourceType | JSONResponse:
    try:
        return parse_source_type(value, allow_aliases=False)
    except SourceTypeParseError as exc:
        return JSONResponse(exc.as_error_envelope(), status_code=400)


def _unsupported_search_feedback(
    search_type: PublicSourceType,
    payload: dict[str, object],
) -> JSONResponse | None:
    """Reject feedback where no cross-collection identity contract exists."""
    if search_type not in {PublicSourceType.DOCUMENT, PublicSourceType.COMBINED}:
        return None
    if not (payload.get("like_ids") or payload.get("unlike_ids")):
        return None
    return JSONResponse(
        {
            "ok": False,
            "error": "unsupported_feedback_for_search_type",
            "message": (
                f"feedback point ids are not supported for {search_type.value} "
                "search; omit like_ids and unlike_ids"
            ),
        },
        status_code=400,
    )


def _extract_token(request: Request) -> str | None:
    """Pull the presented token from the bearer header or ``?token=``.

    Prefers the ``Authorization: Bearer <token>`` header; falls back to
    the ``token`` query parameter. Returns ``None`` when neither is
    present.
    """
    auth = request.headers.get("authorization")
    if auth:
        scheme, _, value = auth.partition(" ")
        if scheme.lower() == "bearer" and value:
            return value
    query_token = request.query_params.get("token")
    if query_token:
        return query_token
    return None


def require_token(request: Request) -> JSONResponse | None:
    """Token-gate a request; return a 401 response when it fails.

    The live ``_state._SERVICE_TOKEN`` is read through the package alias
    so the value the lifespan generated at startup is observed. The
    presented token is compared in constant time
    (:func:`hmac.compare_digest`).

    Args:
        request: The incoming Starlette request.

    Returns:
        ``None`` when the token matches (caller proceeds), or a
        ``JSONResponse`` with HTTP 401 when the token is missing or
        wrong (caller must return it).
    """
    expected = _m._SERVICE_TOKEN
    presented = _extract_token(request)
    if expected and presented is not None and hmac.compare_digest(presented, expected):
        return None
    return JSONResponse(
        {
            "ok": False,
            "error": "unauthorized",
            "message": (
                "This monitoring route requires the service_token via "
                "'Authorization: Bearer <token>' or '?token='."
            ),
        },
        status_code=401,
    )


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
    groups = cast("list[Any]", result["groups"])
    return PlainTextResponse(render_managed_log_groups(groups))


async def _managed_logs_for_request(
    request: Request,
) -> dict[str, object] | JSONResponse:
    """Read, filter, and shape one bounded managed-log request."""
    lines = request.query_params.get("lines")
    source = request.query_params.get("source", "all")
    filters = _log_filters_from_request(request)
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


def _search_index_state(
    *,
    indexed_count: int | float,
    requested_root: object,
    search_type: PublicSourceType | str,
    published_points: float | None = None,
    named_files: float | None = None,
    covered_files: float | None = None,
) -> dict[str, object]:
    """Adapt this route's carried figures onto the service-domain block.

    The route owns no part of the shape. It converts the published-point
    figure it carries on the timing channel back into the shortfall the
    domain builder expects, and renders whatever that returns.
    """
    from .._index_breadth import BreadthShortfall, FileBreadthShortfall
    from .._search_state import search_index_state

    count = int(indexed_count)
    shortfall = (
        None
        if published_points is None
        else BreadthShortfall(published=int(published_points), live=count)
    )
    file_shortfall = (
        None
        if named_files is None or covered_files is None
        else FileBreadthShortfall(named=int(named_files), covered=int(covered_files))
    )
    return search_index_state(
        indexed_count=count,
        requested_root=requested_root,
        search_type=search_type,
        shortfall=shortfall,
        file_shortfall=file_shortfall,
    )


def _search_summary(count: int, index_state: dict[str, object]) -> str:
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


def _empty_search_diagnostics(
    index_state: dict[str, object],
    *,
    port: int | None,
    path_filter: dict[str, object] | None = None,
) -> dict[str, object]:
    source = index_state["source"]
    remediation = [
        index_command(source, port=port),
        server_status_command(),
        server_jobs_command(port),
    ]
    if index_state["indexed_count"] == 0:
        reason = "index_missing"
        message = f"No indexed {source} items are available."
    elif path_filter is not None:
        # The search proved this: candidates matched the query and the path
        # patterns removed every one. Saying so, with the patterns, is the
        # difference between a fixable typo and an operator concluding the
        # filter is unsupported.
        patterns = ", ".join(
            str(p) for p in cast("list[object]", path_filter["patterns"])
        )
        reason = "no_match_path_filter"
        message = (
            f"{path_filter['candidates_before_filter']} indexed items matched "
            f"the query, and the path filter ({patterns}) excluded every one. "
            "Patterns match project-relative paths; a plain pattern matches "
            "that path and everything under it."
        )
        remediation = [
            "rerun without the path filter to see what the query matches",
            "widen the pattern, or check it against a path from an unfiltered result",
        ]
    else:
        reason = "no_match"
        message = "The index is available, but no indexed item matched the query."

    return {
        "reason": reason,
        "message": message,
        "remediation": remediation,
    }


def _classify_search_result(
    result: dict[str, object],
    *,
    job_snapshot_before: list[dict[str, object]],
    root: Path,
    source: IndexSource,
    request_id: str,
    port: int | None,
) -> SearchResponseClassification:
    """Apply availability classification and stable-empty diagnostics."""
    index_state = cast("dict[str, object]", result.get("index_state", {}))
    classification = classify_search_response(
        result,
        before_snapshot=job_snapshot_before,
        after_snapshot=_canonical_job_snapshot(),
        requested_root=root,
        source=source,
        request_id=request_id,
        index_state=index_state,
        port=port,
    )
    if classification.status_code == 200 and not classification.response["results"]:
        raw_path_filter = classification.response.get("path_filter")
        classification.response["empty"] = _empty_search_diagnostics(
            index_state,
            port=port,
            path_filter=cast("dict[str, object]", raw_path_filter)
            if isinstance(raw_path_filter, dict)
            else None,
        )
    return classification


def _classify_collection_disappearance(
    exc: UnexpectedResponse,
    *,
    job_snapshot_before: list[dict[str, object]],
    root: Path,
    source: IndexSource,
    request_id: str,
    port: int | None,
) -> SearchResponseClassification | None:
    """Classify one instantaneous missing-collection search observation."""
    return classify_qdrant_collection_disappearance(
        exc,
        before_snapshot=job_snapshot_before,
        after_snapshot=_canonical_job_snapshot(),
        requested_root=root,
        source=source,
        request_id=request_id,
        index_state=_search_index_state(
            indexed_count=0,
            requested_root=root,
            search_type=source,
        ),
        port=port,
    )


async def _run_search_with_availability(
    run: Callable[[], dict[str, object]],
    *,
    job_snapshot_before: list[dict[str, object]],
    root: Path,
    source: IndexSource,
    request_id: str,
    port: int | None,
) -> tuple[dict[str, object], SearchResponseClassification | None]:
    """Run retrieval and recover only an evidenced collection disappearance."""
    try:
        return await _run_in_thread(run, limiter=get_search_limiter()), None
    except UnexpectedResponse as exc:
        classification = _classify_collection_disappearance(
            exc,
            job_snapshot_before=job_snapshot_before,
            root=root,
            source=source,
            request_id=request_id,
            port=port,
        )
        if classification is None:
            raise
        return classification.response, classification


def _complete_classified_search(
    classification: SearchResponseClassification,
    *,
    root: Path,
    source: IndexSource,
    request_id: str,
    total_seconds: float,
) -> tuple[dict[str, object], Literal[200, 503]]:
    """Complete watcher and log effects from one classification decision."""
    result = classification.response
    response_status = classification.status_code
    _m._ensure_watcher_soon(root)
    hits = result.get("results")
    hit_count = len(cast("list[object]", hits)) if isinstance(hits, list) else 0
    unavailable = response_status == 503 and result.get("error") == "index_unavailable"
    log_event(
        logger,
        "service.search",
        "unavailable" if unavailable else "completed",
        fields={
            "status_code": response_status,
            **({"error": "index_unavailable"} if unavailable else {}),
            **(
                {"availability_cause": classification.availability_cause}
                if classification.availability_cause is not None
                else {}
            ),
            "request_id": request_id,
            "source": source,
            "search_type": source,
            "root": root,
            "results": hit_count,
            "matching_index_jobs": len(classification.matching_jobs),
            "matching_index_job_ids": ",".join(
                job.id for job in classification.matching_jobs
            ),
            "matching_index_jobs_truncated": classification.matching_jobs_truncated,
            "total_seconds": f"{total_seconds:.3f}",
        },
    )
    return result, response_status


def _canonical_job_snapshot() -> list[dict[str, object]]:
    """Return the canonical manager's copied, JSON-ready job view."""
    from ..jobs import get_job_manager

    return [snapshot.to_dict() for snapshot in get_job_manager().list_jobs()]


def _service_job_snapshot() -> list[dict[str, object]]:
    """Return canonical jobs plus legacy-only service activity records."""
    canonical = _canonical_job_snapshot()
    canonical_ids = {str(record.get("id", "")) for record in canonical}
    legacy_only = [
        record
        for record in _jobs.snapshot()
        if str(record.get("id", "")) not in canonical_ids
    ]
    return [*canonical, *legacy_only]


class _InvalidJobRequestError(ValueError):
    """Stable client-input failure for the canonical jobs resource."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def _job_payload(
    request: Request,
    *,
    required: bool,
) -> dict[str, object]:
    try:
        raw = await request.json()
    except Exception as exc:
        if not required and not await request.body():
            return {}
        raise _InvalidJobRequestError(
            "invalid_json",
            "The request body must be a JSON object.",
        ) from exc
    if not isinstance(raw, dict):
        raise _InvalidJobRequestError(
            "invalid_json",
            "The request body must be a JSON object.",
        )
    return cast("dict[str, object]", raw)


def _job_bool(payload: dict[str, object], key: str, *, default: bool) -> bool:
    value = payload.get(key, default)
    if type(value) is not bool:
        raise _InvalidJobRequestError(
            "invalid_job_spec",
            f"{key} must be a boolean when provided.",
        )
    return bool(value)


def _job_string(
    payload: dict[str, object],
    key: str,
    *,
    default: str | None = None,
) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise _InvalidJobRequestError(
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
        raise _InvalidJobRequestError(
            "invalid_initiator",
            "initiator must be a JSON object when provided.",
        )
    legacy_kind = payload.get("initiator_kind", "service")
    kind = initiator.get("kind", legacy_kind)
    command = initiator.get("command", default_command)
    if not isinstance(kind, str) or not kind.strip():
        raise _InvalidJobRequestError(
            "invalid_initiator",
            "initiator.kind must be a non-empty string.",
        )
    if not isinstance(command, str) or not command.strip():
        raise _InvalidJobRequestError(
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
        raise _InvalidJobRequestError(
            "invalid_idempotency_key",
            "idempotency_key must be a string when provided.",
        )
    if header_key is not None and body_key is not None and header_key != body_key:
        raise _InvalidJobRequestError(
            "idempotency_key_conflict",
            "The header and body idempotency keys must match.",
        )
    key = header_key if header_key is not None else body_key
    if key is None or suffix is None:
        return key
    return f"{key}:{suffix}"


async def _validated_index_request(
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

    operation = _job_string(payload, "operation", default="index")
    source = _job_string(payload, "source")
    mode = _job_string(payload, "mode", default="incremental")
    if operation != JobOperation.INDEX.value:
        raise _InvalidJobRequestError(
            "invalid_job_spec",
            "operation must be 'index'.",
        )
    if source not in {
        JobSource.VAULT.value,
        JobSource.CODE.value,
        JobSource.DOCUMENT.value,
    }:
        raise _InvalidJobRequestError(
            "invalid_job_spec",
            "source must be 'vault', 'code', or 'document'.",
        )
    if mode not in set(JobMode):
        allowed = ", ".join(f"'{member}'" for member in JobMode)
        raise _InvalidJobRequestError(
            "invalid_job_spec",
            f"mode must be one of {allowed}.",
        )
    raw_root = _job_string(payload, "project_root")
    if not Path(raw_root).expanduser().is_absolute():
        raise _InvalidJobRequestError(
            "invalid_job_spec",
            "project_root must be an absolute path.",
        )
    try:
        root = _resolve_root(raw_root)
    except (ProjectRootRequiredError, ValueError) as exc:
        raise _InvalidJobRequestError("invalid_job_spec", str(exc)) from exc
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
        raise _InvalidJobRequestError(
            exc.error_kind.value,
            exc.detail,
        ) from exc
    except ValueError as exc:
        raise _InvalidJobRequestError(
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


def _index_admission_preflight(
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


def _job_outcome_status(code: str) -> int:
    if code.startswith("invalid_") and code != "invalid_transition":
        return 400
    if code == "job_not_found":
        return 404
    if code == "job_capacity_exceeded":
        return 429
    if code in {
        "corpus_limit_exceeded",
        "profile_requirements_not_met",
    }:
        return 422
    if code == "disk_preflight_failed":
        return 507
    if code.startswith("persistence_") or code in {
        "dispatch_stopped",
        "event_loop_required",
    }:
        return 503
    if code in {
        "active_job_exists",
        "idempotency_key_conflict",
        "invalid_transition",
        "job_id_conflict",
        "job_not_retryable",
        "job_not_terminal",
        "revision_conflict",
        "force_not_supported",
        "force_termination_unavailable",
    }:
        return 409
    return 500


def _job_error(
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
        status_code = _job_outcome_status(outcome.code)
    else:
        status_code = 202 if outcome.status is JobOutcomeStatus.ACCEPTED else 200
    if extra:
        payload.update(extra)
    headers: dict[str, str] | None = None
    if location and outcome.job is not None:
        headers = {"Location": f"/jobs/{outcome.job.id}"}
    return JSONResponse(payload, status_code=status_code, headers=headers)


async def _activate_index_job(
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
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    raise _InvalidJobRequestError(
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
    records = _service_job_snapshot()
    phase = _normalise_filter_value(request.query_params.get("phase"))
    state = _normalise_filter_value(request.query_params.get("state"))
    desired_state = _normalise_filter_value(request.query_params.get("desired_state"))
    source = _normalise_job_source_filter(request.query_params.get("source"))
    trigger = _normalise_filter_value(request.query_params.get("trigger"))
    query = _normalise_filter_value(request.query_params.get("query"))
    job_id = _normalise_filter_value(request.query_params.get("job_id"))
    failed = _normalise_filter_value(request.query_params.get("failed")) in (
        "1",
        "true",
        "yes",
    )
    since_seconds = _parse_since_seconds(request.query_params.get("since"))
    try:
        controllable = _normalise_controllable_filter(
            request.query_params.get("controllable")
        )
    except _InvalidJobRequestError as exc:
        return _job_error("list", exc.code, str(exc))
    now = time.time()
    filtered_records = [
        _job_with_liveness(record, now=now)
        for record in records
        if _job_matches(
            record,
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


async def create_job_route(request: Request) -> JSONResponse:
    """Admit one validated canonical index job."""
    denied = require_token(request)
    if denied is not None:
        return denied
    try:
        payload = await _job_payload(request, required=True)
        (
            spec,
            initiator,
            start_paused,
            idempotency_key,
            admission,
        ) = await _validated_index_request(request, payload)
    except _InvalidJobRequestError as exc:
        return _job_error("create", exc.code, str(exc))

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
    outcome = await _activate_index_job(outcome, admission)
    return _job_response(
        outcome,
        location=True,
        extra=(
            {"admission": _index_admission_preflight(admission)}
            if admission is not None
            else None
        ),
    )


async def job_detail_route(request: Request) -> JSONResponse:
    """Return one full, exact-ID canonical job resource."""
    denied = require_token(request)
    if denied is not None:
        return denied
    from ..jobs import get_job_manager

    job_id = str(request.path_params["job_id"])
    snapshot = get_job_manager().get(job_id)
    if snapshot is None:
        return _job_error("get", "job_not_found", "The job was not found.")
    return JSONResponse(
        {
            "ok": True,
            "job": _job_with_liveness(snapshot.to_dict(), now=time.time()),
        }
    )


def _validated_expected_revision(payload: dict[str, object]) -> int | None:
    raw = payload.get("expected_revision")
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise _InvalidJobRequestError(
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
        payload = await _job_payload(request, required=True)
        state = _job_string(payload, "state")
        mode = _job_string(payload, "mode", default="graceful")
        if state not in set(DesiredJobState):
            allowed = ", ".join(f"'{member}'" for member in DesiredJobState)
            raise _InvalidJobRequestError(
                "invalid_desired_state",
                f"state must be one of {allowed}.",
            )
        control_mode = _CONTROL_MODES.get(mode)
        if control_mode is None:
            raise _InvalidJobRequestError(
                "invalid_control_mode",
                "mode must be 'graceful' or 'force'.",
            )
        expected_revision = _validated_expected_revision(payload)
    except _InvalidJobRequestError as exc:
        return _job_error("set_desired_state", exc.code, str(exc))

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
        payload = await _job_payload(request, required=False)
    except _InvalidJobRequestError as exc:
        return _job_error("retry", exc.code, str(exc))

    from ..jobs import get_job_manager

    manager = get_job_manager()
    parent = manager.get(str(request.path_params["job_id"]))
    admission = None
    if parent is not None:
        try:
            admission = await _validate_index_job_spec(parent.spec)
        except _InvalidJobRequestError as exc:
            return _job_error("retry", exc.code, str(exc))
    initiator = None
    if parent is not None and ("initiator" in payload or "initiator_kind" in payload):
        try:
            root = Path(str(parent.spec.project_root))
            initiator = _validated_initiator(
                payload,
                root=root,
                default_command="http_job_retry",
            )
        except _InvalidJobRequestError as exc:
            return _job_error("retry", exc.code, str(exc))
    outcome = await _run_in_thread(
        partial(
            manager.retry,
            str(request.path_params["job_id"]),
            initiator=initiator,
        )
    )
    outcome = await _activate_index_job(outcome, admission)
    return _job_response(
        outcome,
        location=True,
        extra=(
            {"admission": _index_admission_preflight(admission)}
            if admission is not None
            else None
        ),
    )


async def delete_job_route(request: Request) -> JSONResponse:
    """Delete one exact terminal-history resource without cancelling work."""
    denied = require_token(request)
    if denied is not None:
        return denied
    from ..jobs import get_job_manager

    outcome = await _run_in_thread(
        get_job_manager().delete,
        str(request.path_params["job_id"]),
    )
    return _job_response(outcome)


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


def _dispatch_public_search(
    root: Path,
    query: str,
    top_k: int,
    payload: dict[str, Any],
    search_type: PublicSourceType,
    notes: dict[str, object],
) -> tuple[list[Any], dict[str, float], Any | None]:
    """Dispatch one canonical source without adapter fallback."""
    import vaultspec_rag

    from .._public_search import (
        CodeCombinedSearchFilters,
        DocumentCombinedSearchFilters,
        VaultCombinedSearchFilters,
    )

    if search_type is PublicSourceType.VAULT:
        results, timings = vaultspec_rag.search_vault_timed(
            root,
            query,
            top_k=top_k,
            doc_type=payload.get("doc_type"),
            feature=payload.get("feature"),
            date=payload.get("date"),
            tag=payload.get("tag"),
            intent=payload.get("intent"),
            like_ids=payload.get("like_ids"),
            unlike_ids=payload.get("unlike_ids"),
        )
        return results, timings, None
    if search_type is PublicSourceType.CODE:
        results, timings = vaultspec_rag.search_codebase_timed(
            root,
            query,
            top_k=top_k,
            language=payload.get("language"),
            path=payload.get("path"),
            node_type=payload.get("node_type"),
            function_name=payload.get("function_name"),
            class_name=payload.get("class_name"),
            include_paths=payload.get("include_paths"),
            exclude_paths=payload.get("exclude_paths"),
            dedup_locales=payload.get("dedup_locales"),
            prefer=payload.get("prefer"),
            exclude_domains=payload.get("exclude_domains"),
            only_domains=payload.get("only_domains"),
            include_domains=payload.get("include_domains"),
            like_ids=payload.get("like_ids"),
            unlike_ids=payload.get("unlike_ids"),
            notes=notes,
        )
        return results, timings, None
    if search_type is PublicSourceType.DOCUMENT:
        results, timings = vaultspec_rag.search_documents_timed(
            root,
            query,
            top_k=top_k,
            source_path=payload.get("source_path"),
            extractor_id=payload.get("extractor_id"),
            extractor_version=payload.get("extractor_version"),
            locator_kind=payload.get("locator_kind"),
        )
        return results, timings, None
    combined, timings = vaultspec_rag.search_combined_timed(
        root,
        query,
        top_k=top_k,
        vault_filters=VaultCombinedSearchFilters(
            doc_type=payload.get("doc_type"),
            feature=payload.get("feature"),
            date=payload.get("date"),
            tag=payload.get("tag"),
            intent=payload.get("intent"),
        ),
        code_filters=CodeCombinedSearchFilters(
            language=payload.get("language"),
            path=payload.get("path"),
            node_type=payload.get("node_type"),
            function_name=payload.get("function_name"),
            class_name=payload.get("class_name"),
            include_paths=tuple(payload.get("include_paths") or ()),
            exclude_paths=tuple(payload.get("exclude_paths") or ()),
            dedup_locales=payload.get("dedup_locales"),
            prefer=payload.get("prefer"),
            exclude_domains=tuple(payload.get("exclude_domains") or ()),
            only_domains=tuple(payload.get("only_domains") or ()),
            include_domains=tuple(payload.get("include_domains") or ()),
        ),
        document_filters=DocumentCombinedSearchFilters(
            source_path=payload.get("source_path"),
            extractor_id=payload.get("extractor_id"),
            extractor_version=payload.get("extractor_version"),
            locator_kind=payload.get("locator_kind"),
        ),
    )
    return combined.results, timings, combined


def _execute_search_request(
    *,
    root: Path,
    query: str,
    top_k: int,
    payload: dict[str, Any],
    search_type: PublicSourceType,
    request_id: str,
) -> dict[str, object]:
    """Execute and serialize one search off the event loop."""
    try:
        notes: dict[str, object] = {}
        phase_started = time.perf_counter()
        results, phase_timing, combined = _dispatch_public_search(
            root, query, top_k, payload, search_type, notes
        )
        search_seconds = time.perf_counter() - phase_started
        phase_started = time.perf_counter()
        indexed_count = (
            sum(
                int(phase_timing.get(f"{source}_indexed_count", 0.0))
                for source in INDEX_SOURCES
            )
            if search_type is PublicSourceType.COMBINED
            else int(phase_timing["indexed_count"])
        )
        index_state = _search_index_state(
            indexed_count=indexed_count,
            requested_root=root,
            search_type=search_type,
            published_points=phase_timing.get("published_points"),
            named_files=phase_timing.get("named_files"),
            covered_files=phase_timing.get("covered_files"),
        )
        index_state_seconds = time.perf_counter() - phase_started
        phase_started = time.perf_counter()
        from ._models import SearchResultItem

        items = [
            SearchResultItem.model_validate(result, from_attributes=True).model_dump(
                mode="json"
            )
            for result in results
        ]
        response: dict[str, object] = {
            "request_id": request_id,
            "results": items,
            "summary": _search_summary(len(results), index_state),
            "filtered": notes.get("dropped_domains"),
            "path_filter": notes.get("path_filter"),
            "timing": {
                "index_state_seconds": index_state_seconds,
                "search_seconds": search_seconds,
                "embedding_seconds": phase_timing.get("embedding_seconds"),
                "qdrant_seconds": phase_timing.get("qdrant_seconds"),
                "rerank_seconds": phase_timing.get("rerank_seconds"),
                "postprocess_seconds": phase_timing.get("postprocess_seconds"),
                # Promoted alongside the phases above, not nested only. A
                # reshape of this dict carried the other phase keys up and left
                # these two reachable solely through "phases", which silently
                # broke the diagnostic contract a consumer reads to tell a cold
                # model load apart from a slow query.
                "model_load_seconds": phase_timing.get("model_load_seconds"),
                "project_lease_seconds": phase_timing.get("project_lease_seconds"),
                "serialization_seconds": time.perf_counter() - phase_started,
                "queue_wait_seconds": phase_timing.get("queue_wait_seconds", 0.0),
                "timing_scope": "server_route",
                "phases": phase_timing,
            },
            "index_state": index_state,
        }
        if combined is not None:
            response["ok"] = combined.ok
            response["partial"] = combined.partial
            response["domains"] = combined.domain_status_payload()
            if not combined.ok:
                response.update(
                    {
                        "error": "combined_search_failed",
                        "message": "Every combined-search domain failed.",
                        "summary": "Combined search failed in every domain.",
                    }
                )
        return response
    except RegistryFullError as exc:
        return _m._registry_full_error_dict(exc)
    except VaultStoreLockedError as exc:
        return _m._local_store_locked_error_dict(exc)


async def search_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied

    payload = await request.json()
    request_id = uuid.uuid4().hex
    search_type = _normalise_search_type(payload.get("type", "vault"))
    if isinstance(search_type, JSONResponse):
        return search_type
    unsupported_feedback = _unsupported_search_feedback(search_type, payload)
    if unsupported_feedback is not None:
        return unsupported_feedback
    query = payload.get("query", "")
    top_k = payload.get("top_k", 5)
    project_root = payload.get("project_root")

    top_k = _clamp_top_k(top_k)
    query = _validate_query(query)
    # An empty/whitespace query has no text and no filter tokens to act
    # on; encoding it retrieves arbitrary nearest neighbours, so reject
    # it. A filter-only query like "lang:python" is non-empty here and
    # proceeds (its filters drive the search after token stripping).
    if not query.strip():
        return _BAD_REQUEST_EMPTY_QUERY
    try:
        root = _resolve_root(project_root)
    except ProjectRootRequiredError:
        return _BAD_REQUEST_MISSING_ROOT
    except ValueError as exc:
        return _bad_request_invalid_root(exc)

    job_snapshot_before = _canonical_job_snapshot()
    search_source = search_type.value
    run = partial(
        _execute_search_request,
        root=root,
        query=query,
        top_k=top_k,
        payload=cast("dict[str, Any]", payload),
        search_type=search_type,
        request_id=request_id,
    )

    started = time.perf_counter()
    if search_type is PublicSourceType.COMBINED:
        result = await _run_in_thread(run, limiter=get_search_limiter())
        classification = None
    else:
        result, classification = await _run_search_with_availability(
            run,
            job_snapshot_before=job_snapshot_before,
            root=root,
            source=cast('Literal["vault", "code", "document"]', search_source),
            request_id=request_id,
            port=request.url.port,
        )
    total_seconds = time.perf_counter() - started
    _m.incr("search_total")
    _m.observe("search_last_duration_seconds", total_seconds)
    response_status = 200
    if search_type is PublicSourceType.COMBINED and result.get("ok") is False:
        response_status = 503
    if (
        classification is None
        and "results" in result
        and search_type is not PublicSourceType.COMBINED
    ):
        result["request_id"] = request_id
        timing = result.get("timing")
        if isinstance(timing, dict):
            cast("dict[str, object]", timing)["server_total_seconds"] = total_seconds
        classification = _classify_search_result(
            result,
            job_snapshot_before=job_snapshot_before,
            root=root,
            source=cast('Literal["vault", "code", "document"]', search_source),
            request_id=request_id,
            port=request.url.port,
        )
    if classification is not None:
        result, response_status = _complete_classified_search(
            classification,
            root=root,
            source=cast('Literal["vault", "code", "document"]', search_source),
            request_id=request_id,
            total_seconds=total_seconds,
        )
    return JSONResponse(result, status_code=response_status)


def _preprocess_preflight(
    root: Path,
    admission: CodeIndexPreflight | None = None,
) -> dict[str, object]:
    """Report whether *root*'s preprocess hooks will run, before indexing.

    The ``/reindex`` route returns ``queued`` before the background job runs,
    so a non-interactive client otherwise has no way to know whether the root's
    document-preprocessing hooks will fire. This
    mirrors the ``server start`` operator notice as JSON: whether the root ships
    a preprocess configuration, its resolved rule count, the effective mode,
    and whether hooks will run under it (``off`` skips; ``default`` runs).

    Code jobs project rule count, mode, and execution state from the same
    structured scan used for admission. The file-presence field is retained as
    non-authoritative compatibility metadata. Vault jobs do not run this code
    admission scan, so their legacy informational response keeps its bounded,
    CPU-only configuration read.
    """
    from ..indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME

    config_present = (root / PREPROCESS_CONFIG_FILENAME).is_file()
    if admission is not None:
        scan = admission.scan
        return {
            "config_present": config_present,
            "rule_count": scan.preprocess_rule_count,
            "mode": scan.preprocess_mode,
            "hooks_will_run": scan.hooks_will_run,
        }

    from ..config import get_config
    from ..indexer._preprocess_config import (
        PreprocessConfigError,
        load_preprocess_rules,
    )

    mode = get_config().preprocess_mode
    rule_count = 0
    if config_present:
        try:
            # strict resolves the true rule count regardless of the kill
            # switch, so the count reported is the config's own, not a
            # mode-gated zero.
            rule_count = len(load_preprocess_rules(root, strict=True).rules)
        except PreprocessConfigError:
            rule_count = 0
    hooks_will_run = config_present and rule_count > 0 and mode != "off"
    return {
        "config_present": config_present,
        "rule_count": rule_count,
        "mode": mode,
        "hooks_will_run": hooks_will_run,
    }


def _reindex_sources(source_type: PublicSourceType) -> tuple[PublicSourceType, ...]:
    """Expand the combined compatibility source into independent domains."""
    if source_type is not PublicSourceType.COMBINED:
        return (source_type,)
    return (
        PublicSourceType.VAULT,
        PublicSourceType.CODE,
        PublicSourceType.DOCUMENT,
    )


def _reindex_failure(*, error_kind: str, detail: str) -> dict[str, object]:
    """Return one stable failed-domain response."""
    return {
        "ok": False,
        "job_id": None,
        "error_kind": error_kind,
        "detail": detail,
        "outcome": {
            "status": "error",
            "code": error_kind,
            "message": detail,
        },
    }


async def _validate_reindex_domains(
    request: Request,
    payload: dict[str, object],
    source_type: PublicSourceType,
    *,
    clean: bool,
) -> tuple[list[tuple[PublicSourceType, Any]], dict[str, dict[str, object]]]:
    """Validate every requested domain without collapsing combined admission."""
    validated: list[tuple[PublicSourceType, Any]] = []
    failures: dict[str, dict[str, object]] = {}
    for source in _reindex_sources(source_type):
        canonical_payload = {
            **payload,
            "operation": "index",
            "source": source.value,
            "mode": "rebuild" if clean else "incremental",
            "start_paused": False,
        }
        try:
            request_parts = await _validated_index_request(
                request,
                canonical_payload,
                idempotency_suffix=(
                    source.value if source_type is PublicSourceType.COMBINED else None
                ),
            )
        except _InvalidJobRequestError as exc:
            if source_type is not PublicSourceType.COMBINED:
                raise
            failures[source.value] = _reindex_failure(
                error_kind=exc.code,
                detail=str(exc),
            )
        else:
            validated.append((source, request_parts))
    return validated, failures


async def _create_reindex_domains(
    validated: list[tuple[PublicSourceType, Any]],
    source_type: PublicSourceType,
    domain_responses: dict[str, dict[str, object]],
) -> tuple[Path | None, CodeIndexPreflight | None]:
    """Create independently validated jobs and retain per-domain failures."""
    from ..job_models import JobOutcomeStatus
    from ..jobs import get_job_manager

    manager = get_job_manager()
    first_root: Path | None = None
    first_admission: CodeIndexPreflight | None = None
    for source, request_parts in validated:
        spec, initiator, start_paused, idempotency_key, admission = request_parts
        try:
            outcome = await _run_in_thread(
                partial(
                    manager.create,
                    spec,
                    initiator,
                    start_paused=start_paused,
                    idempotency_key=idempotency_key,
                )
            )
            outcome = await _activate_index_job(outcome, admission)
        except Exception as exc:
            if source_type is not PublicSourceType.COMBINED:
                raise
            logger.exception("Combined reindex failed for %s", source.value)
            domain_responses[source.value] = _reindex_failure(
                error_kind=type(exc).__name__,
                detail=str(exc) or type(exc).__name__,
            )
            continue
        ok = outcome.status is not JobOutcomeStatus.ERROR
        domain: dict[str, object] = {
            "ok": ok,
            "job_id": outcome.job.id if outcome.job is not None else None,
            "error_kind": None if ok else outcome.code,
            "detail": outcome.message,
            "outcome": outcome.to_dict(),
        }
        if admission is not None:
            domain["admission"] = _index_admission_preflight(admission)
        domain_responses[source.value] = domain
        if outcome.job is not None:
            first_root = Path(str(outcome.job.spec.project_root))
        if (
            first_admission is None
            and source is PublicSourceType.CODE
            and admission is not None
        ):
            first_admission = cast("CodeIndexPreflight", admission)
    return first_root, first_admission


async def reindex_route(request: Request) -> JSONResponse:
    """Validated compatibility adapter over canonical ``POST /jobs`` creation."""
    denied = require_token(request)
    if denied is not None:
        return denied
    try:
        payload = await _job_payload(request, required=True)
        try:
            source_type = parse_source_type(
                payload.get("type", PublicSourceType.VAULT.value),
                allow_aliases=False,
            )
        except SourceTypeParseError as exc:
            return _job_error(
                "create",
                "invalid_job_spec",
                str(exc),
                extra={"error": exc.error_kind, **exc.as_payload()},
            )
        clean = payload.get("clean", False)
        if type(clean) is not bool:
            raise _InvalidJobRequestError(
                "invalid_job_spec",
                "clean must be a boolean when provided.",
            )
        validated, domain_responses = await _validate_reindex_domains(
            request,
            payload,
            source_type,
            clean=clean,
        )
    except _InvalidJobRequestError as exc:
        return _job_error("create", exc.code, str(exc))

    first_root, first_admission = await _create_reindex_domains(
        validated,
        source_type,
        domain_responses,
    )

    if first_root is not None:
        _m._ensure_watcher_soon(first_root)
    if source_type is PublicSourceType.COMBINED:
        successes = sum(bool(item["ok"]) for item in domain_responses.values())
        return JSONResponse(
            {
                "ok": successes == len(domain_responses),
                "partial": 0 < successes < len(domain_responses),
                "status": (
                    "queued"
                    if successes == len(domain_responses)
                    else "partial"
                    if successes
                    else "failed"
                ),
                "domains": domain_responses,
            },
            status_code=200 if successes else 409,
        )

    domain = domain_responses[source_type.value]
    if not domain["ok"]:
        outcome_payload = cast("dict[str, object]", domain["outcome"])
        return JSONResponse(
            {**outcome_payload, "ok": False, "error": domain["error_kind"]},
            status_code=_job_outcome_status(str(domain["error_kind"])),
        )
    assert first_root is not None
    response: dict[str, object] = {
        "ok": True,
        "job_id": domain["job_id"],
        "status": "queued",
        "preprocess": _preprocess_preflight(first_root, first_admission),
        "outcome": domain["outcome"],
    }
    if "admission" in domain:
        response["admission"] = domain["admission"]
    return JSONResponse(response)


async def clean_route(request: Request) -> JSONResponse:
    """Clean one canonical index domain or all domains independently."""
    denied = require_token(request)
    if denied is not None:
        return denied
    try:
        payload = await _job_payload(request, required=True)
        try:
            source_type = parse_source_type(
                payload.get("type", PublicSourceType.COMBINED.value),
                allow_aliases=False,
            )
        except SourceTypeParseError as exc:
            return JSONResponse(exc.as_error_envelope(), status_code=400)
        raw_root = _job_string(payload, "project_root")
        root = _resolve_root(raw_root)
    except (ProjectRootRequiredError, ValueError, _InvalidJobRequestError) as exc:
        return JSONResponse(
            {"ok": False, "error": "invalid_clean_request", "message": str(exc)},
            status_code=400,
        )

    import vaultspec_rag

    sources = (
        (
            PublicSourceType.VAULT,
            PublicSourceType.CODE,
            PublicSourceType.DOCUMENT,
        )
        if source_type is PublicSourceType.COMBINED
        else (source_type,)
    )
    domains: dict[str, dict[str, object]] = {}
    for source in sources:
        try:
            cleared = await _run_in_thread(
                partial(vaultspec_rag.clean, root, clean_type=source.value)
            )
        except Exception as exc:
            logger.exception("Index clean failed for %s", source.value)
            domains[source.value] = {
                "ok": False,
                "cleared": [],
                "error_kind": type(exc).__name__,
                "detail": str(exc),
            }
        else:
            domains[source.value] = {
                "ok": True,
                "cleared": cleared,
                "error_kind": None,
                "detail": None,
            }
    successes = sum(bool(item["ok"]) for item in domains.values())
    return JSONResponse(
        {
            "ok": successes == len(domains),
            "partial": 0 < successes < len(domains),
            "domains": domains,
        },
        status_code=200 if successes else 409,
    )


async def list_projects_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    projects = _m._registry.snapshot()
    for p in projects:
        p["root"] = str(p["root"])
    return JSONResponse(
        {
            "projects": projects,
            "max_projects": _m._registry.max_projects,
            "idle_ttl_seconds": _m._registry.idle_ttl_seconds,
        }
    )


async def evict_project_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    payload = await request.json()
    root = payload.get("root")
    from pathlib import Path

    target = Path(root).resolve()
    evicted, reason = _m._registry.try_evict(target)
    return JSONResponse({"root": str(target), "evicted": evicted, "reason": reason})


async def get_watcher_state_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    project_root = request.query_params.get("project_root")
    from ..config import get_config

    cfg = get_config()
    with _m._watcher_lock:
        roots = [str(p) for p in _m._watcher_tasks]

    state = {
        "watch_enabled": bool(cfg.watch_enabled),
        "debounce_ms": int(cfg.watch_debounce_ms),
        "cooldown_s": float(cfg.watch_cooldown_s),
        "watching": sorted(roots),
    }

    if project_root is not None:
        from pathlib import Path

        state["running"] = str(Path(project_root).resolve()) in roots

    return JSONResponse(state)


_STORAGE_SURVEY_STATUSES = frozenset({"live", "orphaned", "unknown", "unverifiable"})


def _serve_survey_from_snapshot(
    status_filter: str | None,
    limit: int,
    root: str | None,
    *,
    fresh: bool,
) -> dict[str, Any] | None:
    """Shape the cached answer, or ``None`` when the caller must walk.

    The admission rule for the daemon-held snapshot, stated apart from the
    walk it spares: a ``fresh`` request never consults the slot even when
    one is published, and a cold slot has no answer to give. ``None`` in
    both cases is the instruction to compute.
    """
    from ._state import survey_snapshot

    if fresh:
        return None
    snapshot = survey_snapshot()
    if snapshot is None:
        return None
    return _shape_survey_payload(
        list(snapshot.surveys),
        status_filter,
        limit,
        root,
        computed_at=snapshot.computed_at,
        source="cache",
    )


def _publish_and_shape_survey(
    surveys: list[NamespaceSurvey],
    status_filter: str | None,
    limit: int,
    root: str | None,
) -> dict[str, Any]:
    """Adopt freshly walked surveys as the snapshot and shape the answer.

    Publishing is what makes the walk worth its cost: the whole result is
    stamped and installed, so the next caller is served from cache again
    and the answer this caller receives carries the same stamp the slot
    now holds. Takes the surveys as a reading so the adoption rule is
    stated over what was walked rather than over the walking.
    """
    from datetime import UTC, datetime

    from ._state import publish_survey_snapshot

    computed_at = datetime.now(UTC).isoformat()
    publish_survey_snapshot(surveys, computed_at=computed_at)
    return _shape_survey_payload(
        surveys, status_filter, limit, root, computed_at=computed_at, source="fresh"
    )


def _gather_storage_survey(
    status_filter: str | None,
    limit: int,
    root: str | None = None,
    *,
    fresh: bool = False,
) -> dict[str, Any]:
    """Answer the survey from the daemon snapshot, or compute and publish.

    The daemon-held snapshot (published by the startup warmer, every
    maintenance cycle, and every fresh compute here) makes the common path
    O(1) at any namespace count. ``fresh=True`` - or a cold snapshot -
    triggers the full walk, whose result is published so subsequent callers
    are served from cache again.
    """
    cached = _serve_survey_from_snapshot(status_filter, limit, root, fresh=fresh)
    if cached is not None:
        return cached
    return _publish_and_shape_survey(_fetch_surveys(), status_filter, limit, root)


async def storage_survey_route(request: Request) -> JSONResponse:
    """Return a bounded, filterable read-only survey of stored namespaces.

    Server-mode only (the local store has a single namespace and nothing to
    reconcile). Token-gated like every other monitoring route. The optional
    ``?status=`` narrows to one classification, ``?limit=`` bounds the
    window, and ``?root=`` narrows to one root's namespace while returning
    that root's authoritative collection prefix as ``queried_root``; the
    default is biased to the actionable states first.

    The default answer comes from the daemon-held survey snapshot (published
    at startup, by every maintenance cycle, and by every fresh compute), so
    the route is O(1) at any namespace count; ``computed_at``/``source``
    surface the snapshot's age and ``?fresh=true`` forces a recompute.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    from ..config import get_config

    if not get_config().effective_server_mode():
        return JSONResponse(
            {
                "ok": False,
                "error": "server_mode_required",
                "message": (
                    "Storage survey requires server mode. A local-only store has "
                    "a single namespace and nothing to reconcile."
                ),
            },
            status_code=409,
        )
    raw_status = request.query_params.get("status")
    if raw_status is not None and raw_status not in _STORAGE_SURVEY_STATUSES:
        return JSONResponse(
            {
                "ok": False,
                "error": "bad_request",
                "message": (
                    "status must be one of live, orphaned, unknown, unverifiable."
                ),
            },
            status_code=400,
        )
    limit = _clamp_survey_limit(request.query_params.get("limit"))
    raw_root = request.query_params.get("root")
    if raw_root is not None and not raw_root.strip():
        return JSONResponse(
            {
                "ok": False,
                "error": "bad_request",
                "message": "root must be a non-empty path.",
            },
            status_code=400,
        )
    raw_fresh = request.query_params.get("fresh")
    fresh = raw_fresh is not None and raw_fresh.strip().lower() in ("1", "true", "yes")

    def _run() -> dict[str, Any]:
        return _gather_storage_survey(raw_status, limit, raw_root, fresh=fresh)

    result = await _run_in_thread(_run)
    return JSONResponse(result)


async def start_watcher_route(request: Request) -> JSONResponse:
    """Start automatic updates for one root and report the state achieved.

    ``started`` answers only "is a watcher watching this root now". When
    another owner still holds the root - a draining stop, an in-flight warm -
    the start is recorded and ``status`` names that owner instead, so a caller
    is never told updates are back on while they are still off.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    payload = await request.json()
    root = payload.get("root")
    from pathlib import Path

    from ..config import get_config

    cfg = get_config()
    target = Path(root).resolve()
    outcome = _m._ensure_watcher(target)
    return JSONResponse(
        {
            "root": str(target),
            "started": outcome.running,
            "status": outcome.value,
            "watch_enabled": bool(cfg.watch_enabled),
        }
    )


async def stop_watcher_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    payload = await request.json()
    root = payload.get("root")
    from pathlib import Path

    target = Path(root).resolve()
    with _m._watcher_lock:
        was_running = target in _m._watcher_tasks
    _m._stop_watcher(target)
    return JSONResponse({"root": str(target), "stopped": was_running})


async def reconfigure_watcher_route(request: Request) -> JSONResponse:
    """Restart one root's watcher with new timing and report the state achieved.

    The stop that precedes the restart leaves the old generation draining, so
    ``restarted`` reports whether a watcher carrying the new timing is running
    on return, and ``status`` names the owner still holding the root when it
    is not.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    payload = await request.json()
    root = payload.get("root")
    debounce_ms = payload.get("debounce_ms")
    cooldown_s = payload.get("cooldown_s")
    from pathlib import Path

    from ..config import get_config

    cfg = get_config()
    target = Path(root).resolve()
    _m._stop_watcher(target)
    outcome = _m._ensure_watcher(target, debounce_ms=debounce_ms, cooldown_s=cooldown_s)

    db_ms = int(debounce_ms) if debounce_ms is not None else int(cfg.watch_debounce_ms)
    db_cs = float(cooldown_s) if cooldown_s is not None else float(cfg.watch_cooldown_s)
    return JSONResponse(
        {
            "root": str(target),
            "restarted": outcome.running,
            "status": outcome.value,
            "debounce_ms": db_ms,
            "cooldown_s": db_cs,
        }
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

    def _run():
        return vaultspec_rag.get_service_state(root, watching_roots=watching_roots)

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

    def _run():
        import vaultspec_rag

        return vaultspec_rag.run_benchmark(root, n_queries=n_queries)

    from anyio.to_thread import run_sync as _run_in_thread

    res = await _run_in_thread(_run)
    return JSONResponse(res)


async def quality_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied

    def _run():
        import vaultspec_rag

        return vaultspec_rag.run_quality_probe()

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

    def _run() -> dict[str, Any]:
        try:
            with _m._registry.lease(root) as slot:
                doc = slot.store.get_by_id(doc_id)
                if not doc:
                    return {"ok": False, "error": "not_found"}
                return {"content": doc.get("content", "")}
        except RegistryFullError as exc:
            return _m._registry_full_error_dict(exc)
        except VaultStoreLockedError as exc:
            return _m._local_store_locked_error_dict(exc)

    result = await _run_in_thread(_run)
    return JSONResponse(result)


def _quiesce_transition(gate: QuiesceGate, *, pause: bool) -> str:
    """Apply one pause/resume transition and name the outcome.

    The prior gate state is read BEFORE the mutation so an
    already-satisfied request is reported as ``already_*`` rather than
    as a fresh state change. This is the single service-domain owner of
    the pause/resume status vocabulary; adapters (CLI, MCP) render it
    without recomputing state.
    """
    was_paused = gate.is_paused()
    if pause:
        gate.pause()
        return "already_paused" if was_paused else "paused"
    gate.resume()
    return "resumed" if was_paused else "already_running"


async def _quiesce_route(request: Request, *, pause: bool) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    gate = _m._registry.quiesce_gate
    status = _quiesce_transition(gate, pause=pause)
    # Re-read after the transition: a gate latched open by a pending
    # shutdown ignores pause(), and the honest post-state lets the
    # caller detect the unachieved hold instead of trusting the verb.
    paused = gate.is_paused()
    log_event(
        logger,
        "service.quiesce",
        status,
        fields={"paused": paused},
    )
    return JSONResponse({"ok": True, "status": status, "paused": paused})


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
