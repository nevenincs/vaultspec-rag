"""The ``GET /storage/survey`` route and its shaping helpers.

Pure, read-only survey transforms - the ``?limit=`` clamp, the short-lived
managed-server survey walk, and the bounded/filterable payload shaper - plus
the snapshot-aware ``_gather_storage_survey`` orchestrator and the
``storage_survey_route`` handler that composes them. The daemon-held snapshot
(published by the startup warmer, every maintenance cycle, and every fresh
compute here) makes the common path O(1) at any namespace count;
``?fresh=true`` or a cold snapshot triggers the full walk.

Lifecycle-inert by construction:
this module is read/drop-free and must never import :mod:`vaultspec_rag.cli` or
any service-lifecycle helper. All heavy imports (qdrant client, config,
storage ops, store) stay function-local so the routes layer stays off the torch
and CLI import paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse

from ._auth import require_token
from ._utils import _TRUTHY_QUERY_VALUES

if TYPE_CHECKING:
    from starlette.requests import Request

    from ..generation_survey import RootGenerations
    from ..storage_survey import NamespaceSurvey

__all__ = [
    "_clamp_survey_limit",
    "_fetch_surveys",
    "_gather_storage_survey",
    "_publish_and_shape_survey",
    "_serve_survey_from_snapshot",
    "_shape_survey_payload",
    "storage_survey_route",
]

_STORAGE_SURVEY_DEFAULT_LIMIT = 200
_STORAGE_SURVEY_MAX_LIMIT = 1000
_STORAGE_SURVEY_STATUSES = frozenset({"live", "orphaned", "unknown", "unverifiable"})


@dataclass(frozen=True, slots=True)
class _SurveyPayloadRequest:
    surveys: list[NamespaceSurvey]
    status_filter: str | None
    limit: int
    root: str | None
    computed_at: str
    source: str


def _clamp_survey_limit(raw: str | None) -> int:
    """Parse and clamp the survey ``?limit=`` to a bounded window."""
    if raw is None:
        return _STORAGE_SURVEY_DEFAULT_LIMIT
    try:
        value = int(raw)
    except ValueError:
        return _STORAGE_SURVEY_DEFAULT_LIMIT
    if value <= 0:
        return _STORAGE_SURVEY_DEFAULT_LIMIT
    return min(value, _STORAGE_SURVEY_MAX_LIMIT)


def _fetch_surveys() -> list[NamespaceSurvey]:
    """Run the full read-only storage survey against the managed server.

    Opens a short-lived client, classifies every per-root namespace through
    the persisted manifest, and returns the classified records. Pure storage
    IO, never touches the GPU. This is the O(namespaces) footprint walk; the
    route prefers the daemon-held snapshot and only calls this on
    ``?fresh=true`` or a cold cache.
    """
    from qdrant_client import QdrantClient

    from ..config._settings import get_config
    from ..storage_survey_ops import gather_survey, server_storage_collections_dir

    cfg = get_config()
    url = cfg.effective_qdrant_url
    client = QdrantClient(url=url)
    try:
        return gather_survey(client, server_storage_collections_dir())
    finally:
        client.close()


def _generation_fields(report: RootGenerations | None) -> dict[str, Any]:
    """Shape one namespace's served-collection and generation-debt fields.

    ``None`` - an unattributable namespace, or a root whose served pointer
    could not be read - reports ``null`` for both rather than an empty debt
    list. "Nothing is known about this root" and "this root is carrying
    nothing" are different facts, and a consumer that flattened them would
    read an offline share as a clean bill of health.
    """
    if report is None:
        return {"served_code_collection": None, "unreferenced_generations": None}
    return {
        "served_code_collection": report.served,
        "unreferenced_generations": list(report.unreferenced),
    }


def _shape_survey_payload(request: _SurveyPayloadRequest) -> dict[str, Any]:
    """Shape a classified survey as the bounded route response.

    Applies the optional status and root filters, truncates to the clamped
    limit, and stamps freshness metadata: ``computed_at`` is when the
    underlying survey ran, ``source`` is ``"cache"`` (daemon snapshot) or
    ``"fresh"`` (computed for this request).

    With ``root``, the namespace list is narrowed to the root's own prefix
    and the response carries a top-level ``queried_root`` object holding the
    authoritative computed prefix - derived through the one real
    ``root_collection_prefix`` derivation, so consumers never recompute the
    hash. An unindexed root still gets its prefix, with an empty namespace
    list. ``total`` always counts the post-filter namespaces, so under a
    root (or status) filter it is not the server-wide count.

    Each namespace also reports ``served_code_collection`` and
    ``unreferenced_generations``. Both are ``null`` - never ``[]`` - for a
    namespace with no attributed root, and for a root whose served pointer
    could not be read. That distinction is part of the contract and an adapter
    must carry it through rather than default it: ``null`` means nothing is
    known about this root, ``[]`` means the root is known to be carrying
    nothing. Coercing the first into the second reports an offline share or a
    permissions blip as a clean bill of health, which is precisely the evidence
    a later reclamation pass must never be handed.

    ``totals`` also carries ``collections`` - the total Qdrant collection
    count across every surveyed namespace, distinct from ``namespaces`` (one
    namespace can hold several collections) - ``ephemeral_backlog_bytes``,
    the footprint still held by orphaned temp-rooted namespaces (exactly the
    population that becomes eligible for reclamation on the very next cycle),
    and ``points_unverified_namespaces``, the count of namespaces whose point
    count could not be fully read. All three are pure reporting derived from
    the same unfiltered survey as the rest of ``totals`` and feed no gate or
    reclaim decision.

    Each namespace also reports its own ``points_verified``: ``False`` means
    at least one of its collections could not be counted, so ``points`` is a
    partial floor rather than the namespace total. A consumer must carry this
    through rather than default it - it is exactly the fact an uncounted
    collection would otherwise silently report as a verified zero.
    """
    surveys, queried_root = _filtered_surveys(
        request.surveys, request.status_filter, request.root
    )
    bounded = surveys[: request.limit]
    generations = _generation_reports(bounded)
    payload: dict[str, object] = {
        "namespaces": [
            _namespace_entry(s, generations.get(s.root or "")) for s in bounded
        ],
        "returned": len(bounded),
        "total": len(surveys),
        "limit": request.limit,
        "computed_at": request.computed_at,
        "source": request.source,
        "totals": _backend_rollup(request.surveys),
    }
    if queried_root is not None:
        payload["queried_root"] = queried_root
    return payload


def _backend_rollup(surveys: list[NamespaceSurvey]) -> dict[str, object]:
    """Roll up the whole backend, before any view filter narrows it.

    Consumers see true total size and per-status composition regardless of
    which view they asked for. ``collections``,
    ``ephemeral_backlog_bytes``, and ``points_unverified_namespaces`` are pure
    observability so unbounded growth (and unread state) is visible before it
    is expensive, never a threshold anything downstream compares against.
    """
    from ..storage_survey import is_temp_rooted
    from ..storage_survey_ops import backend_totals

    return {
        **backend_totals(surveys),
        "collections": sum(len(s.collections) for s in surveys),
        "ephemeral_backlog_bytes": sum(
            s.footprint_bytes
            for s in surveys
            if s.status == "orphaned" and is_temp_rooted(s.root)
        ),
        "points_unverified_namespaces": sum(
            1 for s in surveys if not s.points_verified
        ),
    }


def _filtered_surveys(
    surveys: list[NamespaceSurvey],
    status_filter: str | None,
    root: str | None,
) -> tuple[list[NamespaceSurvey], dict[str, str] | None]:
    """Narrow a survey to the requested view, and describe the root asked for.

    The root view carries the authoritative computed prefix back to the caller,
    derived through the one real derivation, so no consumer recomputes the
    hash. An unindexed root still gets its prefix, with an empty list.
    """
    import pathlib

    from .._store_models import root_collection_prefix

    if status_filter:
        surveys = [s for s in surveys if s.status == status_filter]
    if root is None:
        return surveys, None
    prefix = root_collection_prefix(root)
    queried_root = {"root": str(pathlib.Path(root).resolve()), "prefix": prefix}
    return [s for s in surveys if s.prefix == prefix], queried_root


def _generation_reports(
    bounded: list[NamespaceSurvey],
) -> dict[str, RootGenerations]:
    """Report which code collection each root serves, and what nothing points at.

    Reported only: dropping one needs a granularity the prefix-scoped delete
    does not have, and a definition of when no reader still holds it. A root
    whose pointer could not be read contributes no entry at all, so it
    surfaces as "nothing known" rather than as debt something might later act
    on.
    """
    from .. import store_schema
    from ..generation_survey import survey_generations

    served = {
        s.root: f"{s.prefix}{store_schema.CODE_COLLECTION}" for s in bounded if s.root
    }
    known = [name for s in bounded for name in s.collections]
    return {report.root: report for report in survey_generations(served, known)}


def _namespace_entry(
    survey: NamespaceSurvey, generations: RootGenerations | None
) -> dict[str, Any]:
    """Shape one namespace as the route reports it."""
    from ..storage_survey import is_temp_rooted

    return {
        "prefix": survey.prefix,
        "root": survey.root,
        "status": survey.status,
        "collections": survey.collections,
        "points": survey.points,
        "vault_points": survey.vault_points,
        "code_points": survey.code_points,
        "document_points": survey.document_points,
        "footprint_bytes": survey.footprint_bytes,
        "points_verified": survey.points_verified,
        # What produced each collection. An empty map means the namespace
        # predates stamping, which is an unknown rather than a problem - the
        # survey has always reported how much is stored, and this is the first
        # thing it can say about what made it.
        "models": survey.models,
        "temp_rooted": is_temp_rooted(survey.root),
        **_generation_fields(generations),
    }


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
        _SurveyPayloadRequest(
            surveys=list(snapshot.surveys),
            status_filter=status_filter,
            limit=limit,
            root=root,
            computed_at=snapshot.computed_at,
            source="cache",
        )
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
        _SurveyPayloadRequest(
            surveys=surveys,
            status_filter=status_filter,
            limit=limit,
            root=root,
            computed_at=computed_at,
            source="fresh",
        )
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
    from ..config._settings import get_config

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
    fresh = raw_fresh is not None and raw_fresh.strip().lower() in _TRUTHY_QUERY_VALUES

    def _run() -> dict[str, Any]:
        return _gather_storage_survey(raw_status, limit, raw_root, fresh=fresh)

    from anyio.to_thread import run_sync as _run_in_thread

    result = await _run_in_thread(_run)
    return JSONResponse(result)
