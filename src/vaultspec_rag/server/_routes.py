"""Read-only HTTP routes for the resident service (#142, plan P03).

Per the ``service-observability`` ADR these routes are strictly
read-only - control happens through the same REST surface, not a
separate protocol. They are registered as Starlette
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
from typing import TYPE_CHECKING, Any, cast

from anyio.to_thread import run_sync as _run_in_thread
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

import vaultspec_rag.server as _m

from ..concurrency import get_search_limiter
from ..logging_config import (
    InvalidManagedLogSourceError,
    log_event,
    read_managed_logs,
)
from ..service import RegistryFullError
from ..store import VaultStoreLockedError
from . import _jobs
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
from ._routes_logs import (
    _MAX_LOG_LINES,
    _clamp_lines,
    _filter_log_groups,
    _log_filters_from_request,
    _managed_log_payload,
    _render_plain_log_groups,
    _tail_log_groups,
)
from ._routes_storage import (
    _clamp_survey_limit,
    _fetch_surveys,
    _shape_survey_payload,
)
from ._utils import (
    ProjectRootRequiredError,
    _clamp_top_k,
    _resolve_root,
    _validate_query,
)

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

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


def _bad_request_invalid_root(exc: ValueError) -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "error": "bad_request",
            "message": str(exc),
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
    return PlainTextResponse(_render_plain_log_groups(groups))


async def _managed_logs_for_request(
    request: Request,
) -> dict[str, object] | JSONResponse:
    """Read, filter, and shape one bounded managed-log request."""
    lines = _clamp_lines(request.query_params.get("lines"))
    source = request.query_params.get("source", "all")
    filters = _log_filters_from_request(request)
    read_limit = _MAX_LOG_LINES if filters else lines
    try:
        # Sparse rotated reads can cross several files; keep filesystem work
        # off the event loop while preserving the production reader contract.
        groups = await _run_in_thread(
            partial(read_managed_logs, read_limit, source=source)
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
    if filters:
        groups = _filter_log_groups(groups, **filters)
    groups = _tail_log_groups(groups, lines)
    return _managed_log_payload(
        source=source,
        limit=lines,
        groups=groups,
        filters=filters,
    )


def _search_index_state(
    *,
    status: dict[str, Any],
    requested_root: object,
    search_type: object,
) -> dict[str, object]:
    indexed_target = str(status.get("target_dir", ""))
    requested_target = str(requested_root)
    source = "code" if search_type in ("code", "codebase") else "vault"
    indexed_count = (
        int(status.get("code_count", 0))
        if source == "code"
        else int(status.get("vault_count", 0))
    )
    return {
        "source": source,
        "indexed_count": indexed_count,
        "vault_count": int(status.get("vault_count", 0)),
        "code_count": int(status.get("code_count", 0)),
        "indexed_target_root": indexed_target,
        "requested_target_root": requested_target,
        "target_matches": indexed_target == requested_target,
        "status": "missing" if indexed_count == 0 else "available",
    }


def _empty_search_diagnostics(
    index_state: dict[str, object],
    *,
    port: int | None,
) -> dict[str, object]:
    if index_state["indexed_count"] == 0:
        reason = "index_missing"
        message = f"No indexed {index_state['source']} items are available."
    else:
        reason = "no_match"
        message = "The index is available, but no indexed item matched the query."

    source = index_state["source"]
    port_suffix = f" --port {port}" if port is not None else ""
    return {
        "reason": reason,
        "message": message,
        "remediation": [
            f"vaultspec-rag index --type {source}{port_suffix}",
            "vaultspec-rag server status",
            f"vaultspec-rag server jobs --state active{port_suffix}",
        ],
    }


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
    records = _jobs.snapshot()
    phase = _normalise_filter_value(request.query_params.get("phase"))
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


async def search_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied

    payload = await request.json()
    request_id = uuid.uuid4().hex
    search_type = payload.get("type", "vault")
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

    notes: dict[str, object] = {}

    def _run():
        import vaultspec_rag

        try:
            phase_started = time.perf_counter()
            if search_type == "vault":
                results, phase_timing = vaultspec_rag.search_vault_timed(
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
            else:
                results, phase_timing = vaultspec_rag.search_codebase_timed(
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
            search_seconds = time.perf_counter() - phase_started
            phase_started = time.perf_counter()
            status = vaultspec_rag.get_status(root)
            status_seconds = time.perf_counter() - phase_started
            phase_started = time.perf_counter()
            from ._models import SearchResultItem

            items = [
                SearchResultItem.model_validate(r, from_attributes=True).model_dump(
                    mode="json"
                )
                for r in results
            ]
            serialization_seconds = time.perf_counter() - phase_started
            return {
                "request_id": request_id,
                "results": items,
                "summary": f"Found {len(results)} relevant items.",
                # Per-domain counts of noise candidates dropped by the policy,
                # so the caller sees what the filter removed (never silent).
                "filtered": notes.get("dropped_domains"),
                "timing": {
                    "status_seconds": status_seconds,
                    "search_seconds": search_seconds,
                    "model_load_seconds": phase_timing.get("model_load_seconds"),
                    "project_lease_seconds": phase_timing.get("project_lease_seconds"),
                    "embedding_seconds": phase_timing.get("embedding_seconds"),
                    "qdrant_seconds": phase_timing.get("qdrant_seconds"),
                    "rerank_seconds": phase_timing.get("rerank_seconds"),
                    "postprocess_seconds": phase_timing.get("postprocess_seconds"),
                    "serialization_seconds": serialization_seconds,
                    "queue_wait_seconds": phase_timing.get(
                        "queue_wait_seconds",
                        0.0,
                    ),
                    "timing_scope": "server_route",
                    "phases": phase_timing,
                },
                "index_state": _search_index_state(
                    status=status,
                    requested_root=root,
                    search_type=search_type,
                ),
            }
        except RegistryFullError as exc:
            return _m._registry_full_error_dict(exc)
        except VaultStoreLockedError as exc:
            return _m._local_store_locked_error_dict(exc)

    started = time.perf_counter()
    result = await _run_in_thread(_run, limiter=get_search_limiter())
    total_seconds = time.perf_counter() - started
    _m.incr("search_total")
    _m.observe("search_last_duration_seconds", total_seconds)
    if "results" in result:
        result["request_id"] = request_id
        timing = result.get("timing")
        if isinstance(timing, dict):
            timing["server_total_seconds"] = total_seconds
        if not result["results"]:
            result["empty"] = _empty_search_diagnostics(
                cast("dict[str, object]", result.get("index_state", {})),
                port=request.url.port,
            )
        _m._ensure_watcher_soon(root)
        hits = result.get("results")
        hit_count = len(cast("list[object]", hits)) if isinstance(hits, list) else 0
        log_event(
            logger,
            "service.search",
            "completed",
            request_id=request_id,
            search_type=search_type,
            root=root,
            results=hit_count,
            total_seconds=f"{total_seconds:.3f}",
        )
    return JSONResponse(result)


def _preprocess_preflight(root: Path) -> dict[str, object]:
    """Report whether *root*'s preprocess hooks will run, before indexing.

    The ``/reindex`` route returns ``queued`` before the background job runs,
    so a non-interactive client otherwise has no way to know whether the root's
    document-preprocessing hooks will fire (preprocess-sandbox ADR D9). This
    mirrors the ``server start`` operator notice as JSON: whether the root ships
    a ``.vaultragpreprocess.toml``, its resolved rule count, the effective mode,
    and whether hooks will run under it (``off`` skips; ``default`` runs).

    Torch-free by construction: ``load_preprocess_rules`` is CPU-only, keeping
    the routes/server layer off the torch import path. Never raises - a missing
    or malformed config yields ``config_present`` with a zero rule count.
    """
    from ..config import get_config
    from ..indexer._preprocess_config import (
        PREPROCESS_CONFIG_FILENAME,
        PreprocessConfigError,
        load_preprocess_rules,
    )

    mode = get_config().preprocess_mode
    config_present = (root / PREPROCESS_CONFIG_FILENAME).is_file()
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


async def reindex_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied

    payload = await request.json()
    reindex_type = payload.get("type", "vault")
    clean = payload.get("clean", False)
    project_root = payload.get("project_root")
    raw_initiator = payload.get("initiator_kind", "service")
    initiator_kind = (
        str(raw_initiator)
        if raw_initiator in ("cli", "mcp", "service", "watcher")
        else "service"
    )

    try:
        root = _resolve_root(project_root)
    except ProjectRootRequiredError:
        return _BAD_REQUEST_MISSING_ROOT
    from ..jobs import start_reindex_codebase, start_reindex_vault

    if reindex_type == "vault":
        job_id = start_reindex_vault(root, clean, initiator_kind=initiator_kind)
    else:
        job_id = start_reindex_codebase(root, clean, initiator_kind=initiator_kind)

    _m._ensure_watcher_soon(root)
    return JSONResponse(
        {
            "ok": True,
            "job_id": job_id,
            "status": "queued",
            "preprocess": _preprocess_preflight(root),
        }
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
    from datetime import UTC, datetime

    from ._state import publish_survey_snapshot, survey_snapshot

    if not fresh:
        snapshot = survey_snapshot()
        if snapshot is not None:
            return _shape_survey_payload(
                list(snapshot.surveys),
                status_filter,
                limit,
                root,
                computed_at=snapshot.computed_at,
                source="cache",
            )
    surveys = _fetch_surveys()
    computed_at = datetime.now(UTC).isoformat()
    publish_survey_snapshot(surveys, computed_at=computed_at)
    return _shape_survey_payload(
        surveys, status_filter, limit, root, computed_at=computed_at, source="fresh"
    )


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
    denied = require_token(request)
    if denied is not None:
        return denied
    payload = await request.json()
    root = payload.get("root")
    from pathlib import Path

    from ..config import get_config

    cfg = get_config()
    target = Path(root).resolve()
    started = _m._ensure_watcher(target)
    return JSONResponse(
        {
            "root": str(target),
            "started": started,
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
    restarted = _m._ensure_watcher(
        target, debounce_ms=debounce_ms, cooldown_s=cooldown_s
    )

    db_ms = int(debounce_ms) if debounce_ms is not None else int(cfg.watch_debounce_ms)
    db_cs = float(cooldown_s) if cooldown_s is not None else float(cfg.watch_cooldown_s)
    return JSONResponse(
        {
            "root": str(target),
            "restarted": bool(restarted),
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


ROUTES: list[Route] = [
    Route("/logs", logs_route, methods=["GET"]),
    Route("/logs/json", logs_json_route, methods=["GET"]),
    Route("/jobs", jobs_route, methods=["GET"]),
    Route("/metrics", metrics_route, methods=["GET"]),
    Route("/readiness", get_readiness_route, methods=["GET"]),
    Route("/search", search_route, methods=["POST"]),
    Route("/reindex", reindex_route, methods=["POST"]),
    Route("/projects", list_projects_route, methods=["GET"]),
    Route("/projects/evict", evict_project_route, methods=["POST"]),
    Route("/watcher", get_watcher_state_route, methods=["GET"]),
    Route("/watcher/start", start_watcher_route, methods=["POST"]),
    Route("/watcher/stop", stop_watcher_route, methods=["POST"]),
    Route("/watcher/reconfigure", reconfigure_watcher_route, methods=["POST"]),
    Route("/service-state", get_service_state_route, methods=["GET"]),
    Route("/storage/survey", storage_survey_route, methods=["GET"]),
    Route("/code-file", code_file_route, methods=["POST"]),
    Route("/vault-document", vault_document_route, methods=["POST"]),
    Route("/benchmark", benchmark_route, methods=["POST"]),
    Route("/quality", quality_route, methods=["POST"]),
]
