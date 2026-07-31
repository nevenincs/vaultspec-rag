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
    """
    import pathlib

    from .. import store_schema
    from .._store_models import root_collection_prefix
    from ..generation_survey import survey_generations
    from ..storage_survey import is_temp_rooted
    from ..storage_survey_ops import backend_totals

    # Whole-backend rollup, computed before any filter so consumers see
    # true total size and per-status composition regardless of the view.
    totals = backend_totals(request.surveys)
    status_filter = request.status_filter
    limit = request.limit
    root = request.root
    computed_at = request.computed_at
    source = request.source
    surveys = request.surveys

    if status_filter:
        surveys = [s for s in surveys if s.status == status_filter]
    queried_root: dict[str, str] | None = None
    if root is not None:
        prefix = root_collection_prefix(root)
        queried_root = {
            "root": str(pathlib.Path(root).resolve()),
            "prefix": prefix,
        }
        surveys = [s for s in surveys if s.prefix == prefix]
    total = len(surveys)
    bounded = surveys[:limit]
    # Which code collection each returned root actually serves, and which
    # earlier generations nothing points at any more. Reported only: dropping
    # one needs a granularity the prefix-scoped delete does not have, and a
    # definition of when no reader still holds it. A root whose pointer could
    # not be read contributes no entry at all, so it surfaces as "nothing
    # known" rather than as debt something might later act on.
    generations: dict[str, RootGenerations] = {
        report.root: report
        for report in survey_generations(
            {
                s.root: f"{s.prefix}{store_schema.CODE_COLLECTION}"
                for s in bounded
                if s.root
            },
            [name for s in bounded for name in s.collections],
        )
    }
    payload: dict[str, object] = {
        "namespaces": [
            {
                "prefix": s.prefix,
                "root": s.root,
                "status": s.status,
                "collections": s.collections,
                "points": s.points,
                "vault_points": s.vault_points,
                "code_points": s.code_points,
                "document_points": s.document_points,
                "footprint_bytes": s.footprint_bytes,
                # What produced each collection. An empty map means the
                # namespace predates stamping, which is an unknown rather than
                # a problem - the survey has always reported how much is
                # stored, and this is the first thing it can say about what
                # made it.
                "models": s.models,
                "temp_rooted": is_temp_rooted(s.root),
                **_generation_fields(generations.get(s.root or "")),
            }
            for s in bounded
        ],
        "returned": len(bounded),
        "total": total,
        "limit": limit,
        "computed_at": computed_at,
        "source": source,
        "totals": totals,
    }
    if queried_root is not None:
        payload["queried_root"] = queried_root
    return payload


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
