"""Storage-survey shaping helpers for the ``/storage/survey`` route.

Pure, read-only survey transforms: the ``?limit=`` clamp, the short-lived
managed-server survey walk, and the bounded/filterable payload shaper. The
``storage_survey_route`` handler and the snapshot-aware ``_gather_storage_survey``
orchestrator in :mod:`._routes` compose these.

Lifecycle-inert by construction (``storage-maintenance-is-lifecycle-inert``):
this module is read/drop-free and must never import :mod:`vaultspec_rag.cli` or
any service-lifecycle helper. All heavy imports (qdrant client, config,
storage ops, store) stay function-local so the routes layer stays off the torch
and CLI import paths.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..storage_survey import NamespaceSurvey

__all__ = [
    "_clamp_survey_limit",
    "_fetch_surveys",
    "_shape_survey_payload",
]

_STORAGE_SURVEY_DEFAULT_LIMIT = 200
_STORAGE_SURVEY_MAX_LIMIT = 1000


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

    from ..config import get_config
    from ..storage_ops import gather_survey, server_storage_collections_dir

    cfg = get_config()
    url = str(cfg.qdrant_url or "") or f"http://127.0.0.1:{cfg.qdrant_port}"
    client = QdrantClient(url=url)
    try:
        return gather_survey(client, server_storage_collections_dir())
    finally:
        client.close()


def _shape_survey_payload(
    surveys: list[NamespaceSurvey],
    status_filter: str | None,
    limit: int,
    root: str | None,
    *,
    computed_at: str,
    source: str,
) -> dict[str, Any]:
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
    """
    import pathlib

    from ..storage_ops import backend_totals
    from ..storage_survey import is_temp_rooted
    from ..store import root_collection_prefix

    # Whole-backend rollup, computed before any filter so consumers see
    # true total size and per-status composition regardless of the view.
    totals = backend_totals(surveys)

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
    payload: dict[str, Any] = {
        "namespaces": [
            {
                "prefix": s.prefix,
                "root": s.root,
                "status": s.status,
                "collections": s.collections,
                "points": s.points,
                "footprint_bytes": s.footprint_bytes,
                "temp_rooted": is_temp_rooted(s.root),
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
