"""Storage-survey shaping helpers for the ``/storage/survey`` route.

Pure, read-only survey transforms: the ``?limit=`` clamp, the short-lived
managed-server survey walk, and the bounded/filterable payload shaper. The
``storage_survey_route`` handler and the snapshot-aware ``_gather_storage_survey``
orchestrator in :mod:`._routes` compose these.

Lifecycle-inert by construction:
this module is read/drop-free and must never import :mod:`vaultspec_rag.cli` or
any service-lifecycle helper. All heavy imports (qdrant client, config,
storage ops, store) stay function-local so the routes layer stays off the torch
and CLI import paths.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..generation_survey import RootGenerations
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
    from ..storage_ops import backend_totals
    from ..storage_survey import is_temp_rooted

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
    payload: dict[str, Any] = {
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
