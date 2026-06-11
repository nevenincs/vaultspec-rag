"""Read-only HTTP routes for the resident service (#142, plan P03).

Per the ``service-observability`` ADR these routes are strictly
read-only - all control stays on MCP. They are registered as Starlette
:class:`~starlette.routing.Route` objects on the *inner* app assembled
in :mod:`._main` (alongside ``Mount("/mcp")`` + ``Route("/health")``),
never as additional ASGI wrappers.

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
from typing import TYPE_CHECKING, Any

from anyio.to_thread import run_sync as _run_in_thread
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

import vaultspec_rag.server as _m

from ..logging_config import read_service_log
from ..service import RegistryFullError
from ..store import VaultStoreLockedError
from . import _jobs
from ._utils import (
    ProjectRootRequiredError,
    _clamp_top_k,
    _resolve_root,
    _validate_query,
)

if TYPE_CHECKING:
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


def _bad_request_invalid_root(exc: ValueError) -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "error": "bad_request",
            "message": str(exc),
        },
        status_code=400,
    )


# Default and clamp bounds for the ``?lines=`` query parameter.
_DEFAULT_LOG_LINES = 200
_MAX_LOG_LINES = 5_000


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


def _clamp_lines(raw: str | None) -> int:
    """Parse and clamp the ``?lines=`` query parameter.

    Non-integer or non-positive values fall back to the default; the
    value is clamped to ``_MAX_LOG_LINES`` to bound the response size.
    """
    if raw is None:
        return _DEFAULT_LOG_LINES
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_LOG_LINES
    if value <= 0:
        return _DEFAULT_LOG_LINES
    return min(value, _MAX_LOG_LINES)


def _filter_log_lines(
    lines: list[str],
    *,
    job_id: str | None = None,
    contains: str | None = None,
) -> list[str]:
    job_filter = job_id.strip().lower() if job_id else None
    contains_filter = contains.strip().lower() if contains else None
    if not job_filter and not contains_filter:
        return lines
    filtered: list[str] = []
    for line in lines:
        lowered = line.lower()
        if job_filter and job_filter not in lowered:
            continue
        if contains_filter and contains_filter not in lowered:
            continue
        filtered.append(line)
    return filtered


def _log_filters_from_request(request: Request) -> dict[str, str]:
    filters: dict[str, str] = {}
    job_id = request.query_params.get("job_id")
    contains = request.query_params.get("contains")
    if job_id and job_id.strip():
        filters["job_id"] = job_id.strip()
    if contains and contains.strip():
        filters["contains"] = contains.strip()
    return filters


async def logs_route(request: Request) -> PlainTextResponse | JSONResponse:
    """Token-gated read-only ``GET /logs`` returning recent log text.

    Returns the last ``?lines=N`` (default 200, clamped to 5000) lines
    of the rotated service log as ``text/plain``, newest last - parity
    with the ``get_logs`` MCP tool.

    Args:
        request: The incoming Starlette request.

    Returns:
        A ``PlainTextResponse`` with the joined log lines, or the
        ``require_token`` 401 ``JSONResponse``.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    lines = _clamp_lines(request.query_params.get("lines"))
    filters = _log_filters_from_request(request)
    read_limit = _MAX_LOG_LINES if filters else lines
    body_lines = read_service_log(read_limit)
    if filters:
        body_lines = _filter_log_lines(body_lines, **filters)
        body_lines = body_lines[-lines:]
    return PlainTextResponse("\n".join(body_lines))


def _clamp_limit(raw: str | None) -> int | None:
    """Parse the ``?limit=`` query parameter; ``None`` when absent/invalid.

    Returns ``None`` (no cap) when the parameter is missing or
    non-integer, so the full bounded snapshot is returned.
    """
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_since_seconds(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _normalise_filter_value(raw: str | None) -> str | None:
    """Return a stripped lower-case query filter or ``None`` when absent."""
    if raw is None:
        return None
    value = raw.strip().lower()
    return value or None


def _normalise_job_source_filter(raw: str | None) -> str | None:
    value = _normalise_filter_value(raw)
    if value == "codebase":
        return "code"
    return value


def _job_progress_text(record: dict[str, object]) -> str:
    progress = record.get("progress")
    if not isinstance(progress, dict):
        return ""
    step = progress.get("step")
    completed = progress.get("completed")
    total = progress.get("total")
    parts = [str(step)] if step else []
    if total is not None:
        parts.append(f"{completed}/{total}")
    elif completed is not None:
        parts.append(str(completed))
    return " ".join(parts)


def _job_updated_timestamp(record: dict[str, object]) -> float | None:
    progress = record.get("progress")
    if isinstance(progress, dict):
        last_updated = progress.get("last_updated")
        if isinstance(last_updated, int | float):
            return float(last_updated)
    timestamp = record.get("finished_at") or record.get("started_at")
    if isinstance(timestamp, int | float):
        return float(timestamp)
    return None


def _job_runtime_seconds(record: dict[str, object], now: float) -> float | None:
    started_at = record.get("started_at")
    if not isinstance(started_at, int | float):
        return None
    finished_at = record.get("finished_at")
    end = float(finished_at) if isinstance(finished_at, int | float) else now
    return max(0.0, end - float(started_at))


def _job_last_progress_age_seconds(
    record: dict[str, object],
    now: float,
) -> float | None:
    progress = record.get("progress")
    if not isinstance(progress, dict):
        return None
    last_updated = progress.get("last_updated")
    if not isinstance(last_updated, int | float):
        return None
    return max(0.0, now - float(last_updated))


def _job_with_liveness(
    record: dict[str, object],
    *,
    now: float,
) -> dict[str, object]:
    enriched = dict(record)
    enriched["runtime_seconds"] = _job_runtime_seconds(record, now)
    enriched["last_progress_age_seconds"] = _job_last_progress_age_seconds(record, now)
    return enriched


def _job_id_matches(record: dict[str, object], job_id: str | None) -> bool:
    if job_id is None:
        return True
    return str(record.get("id", "")).startswith(job_id)


def _job_matches(
    record: dict[str, object],
    *,
    phase: str | None,
    source: str | None,
    trigger: str | None,
    query: str | None,
    failed: bool,
    job_id: str | None,
    since_seconds: float | None,
    now: float,
) -> bool:
    if not _job_id_matches(record, job_id):
        return False
    if failed and str(record.get("phase", "")).lower() not in ("error", "failed"):
        return False
    if since_seconds is not None:
        timestamp = _job_updated_timestamp(record)
        if timestamp is None or timestamp < now - since_seconds:
            return False
    if phase is not None and str(record.get("phase", "")).lower() != phase:
        return False
    if source is not None and str(record.get("source", "")).lower() != source:
        return False
    if trigger is not None and str(record.get("trigger", "")).lower() != trigger:
        return False
    if query is None:
        return True
    haystack = " ".join(
        [
            str(record.get("id", "")),
            str(record.get("source", "")),
            str(record.get("trigger", "")),
            str(record.get("phase", "")),
            str(record.get("result", "")),
            _job_progress_text(record),
        ]
    ).lower()
    return query in haystack


def _job_summary(records: list[dict[str, object]]) -> dict[str, object]:
    phases: dict[str, int] = {}
    sources: dict[str, int] = {}
    triggers: dict[str, int] = {}
    for record in records:
        phase = str(record.get("phase", "unknown"))
        source = str(record.get("source", "unknown"))
        trigger = str(record.get("trigger", "unknown"))
        phases[phase] = phases.get(phase, 0) + 1
        sources[source] = sources.get(source, 0) + 1
        triggers[trigger] = triggers.get(trigger, 0) + 1
    return {
        "phases": phases,
        "sources": sources,
        "triggers": triggers,
        "running": phases.get("running", 0),
    }


def _prioritise_running_jobs(
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Keep running work visible before completed history while preserving recency."""
    return sorted(
        records,
        key=lambda record: 0 if record.get("phase") == "running" else 1,
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
            "vaultspec-rag server jobs --running",
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
            "summary": _job_summary(records),
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
    search_type = payload.get("type", "vault")
    query = payload.get("query", "")
    top_k = payload.get("top_k", 5)
    project_root = payload.get("project_root")

    top_k = _clamp_top_k(top_k)
    query = _validate_query(query)
    try:
        root = _resolve_root(project_root)
    except ProjectRootRequiredError:
        return _BAD_REQUEST_MISSING_ROOT
    except ValueError as exc:
        return _bad_request_invalid_root(exc)

    def _run():
        import vaultspec_rag

        try:
            phase_started = time.perf_counter()
            if search_type == "vault":
                results = vaultspec_rag.search_vault(
                    root,
                    query,
                    top_k=top_k,
                    doc_type=payload.get("doc_type"),
                    feature=payload.get("feature"),
                    date=payload.get("date"),
                    tag=payload.get("tag"),
                    like_ids=payload.get("like_ids"),
                    unlike_ids=payload.get("unlike_ids"),
                )
            else:
                results = vaultspec_rag.search_codebase(
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
                    dedup_locales=payload.get("dedup_locales", False),
                    prefer=payload.get("prefer"),
                    like_ids=payload.get("like_ids"),
                    unlike_ids=payload.get("unlike_ids"),
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
                "results": items,
                "summary": f"Found {len(results)} relevant items.",
                "timing": {
                    "status_seconds": status_seconds,
                    "search_seconds": search_seconds,
                    "serialization_seconds": serialization_seconds,
                    "queue_wait_seconds": None,
                    "timing_scope": "server_route",
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
    result = await _run_in_thread(_run)
    total_seconds = time.perf_counter() - started
    _m.incr("search_total")
    _m.observe("search_last_duration_seconds", total_seconds)
    if "results" in result:
        timing = result.get("timing")
        if isinstance(timing, dict):
            timing["server_total_seconds"] = total_seconds
        if not result["results"]:
            result["empty"] = _empty_search_diagnostics(
                result.get("index_state", {}),
                port=request.url.port,
            )
        _m._ensure_watcher(root)
    return JSONResponse(result)


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

    _m._ensure_watcher(root)
    return JSONResponse({"ok": True, "job_id": job_id, "status": "queued"})


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
    lines = _clamp_lines(request.query_params.get("lines"))
    filters = _log_filters_from_request(request)
    read_limit = _MAX_LOG_LINES if filters else lines
    body = read_service_log(read_limit)
    if filters:
        body = _filter_log_lines(body, **filters)
        body = body[-lines:]
    return JSONResponse({"lines": body, "total": len(body), "filters": filters})


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
    Route("/search", search_route, methods=["POST"]),
    Route("/reindex", reindex_route, methods=["POST"]),
    Route("/projects", list_projects_route, methods=["GET"]),
    Route("/projects/evict", evict_project_route, methods=["POST"]),
    Route("/watcher", get_watcher_state_route, methods=["GET"]),
    Route("/watcher/start", start_watcher_route, methods=["POST"]),
    Route("/watcher/stop", stop_watcher_route, methods=["POST"]),
    Route("/watcher/reconfigure", reconfigure_watcher_route, methods=["POST"]),
    Route("/service-state", get_service_state_route, methods=["GET"]),
    Route("/code-file", code_file_route, methods=["POST"]),
    Route("/vault-document", vault_document_route, methods=["POST"]),
    Route("/benchmark", benchmark_route, methods=["POST"]),
    Route("/quality", quality_route, methods=["POST"]),
]
