"""Storage survey: classify stored namespaces as live, orphaned, or unknown.

The survey is the read-only half of the storage lifecycle surface and the
safe prerequisite for every destructive verb. It groups the managed
server's collections by their per-root prefix (``r{hash}_``), joins each
prefix to the persisted prefix-to-root manifest, and labels it:

- ``live`` - the manifest maps the prefix to a root that still exists on
  disk.
- ``orphaned`` - the manifest maps it to a root that is gone (a removed
  worktree or deleted project); a prune candidate.
- ``unknown`` - no manifest entry attributes the prefix to any root; it is
  reported but never auto-pruned, because deleting an unattributable
  namespace could destroy live data.

The classification is pure: it takes the collection names, the manifest,
and optional per-collection point counts and footprints, and returns
structured records. Gathering those inputs from a live server or the
on-disk storage tree is a thin separate concern, so the classification is
fully testable without a server or GPU.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from . import store_schema
from .storage_manifest import ManifestEntry, classify_root

__all__ = [
    "NamespaceSurvey",
    "_prefix_of",
    "classify_namespaces",
    "is_temp_rooted",
]

_PREFIX_RE = re.compile(r"^(r[0-9a-f]{12}_)")


def is_temp_rooted(root: str | None) -> bool:
    """Return whether a namespace root lives under an OS temp directory.

    A live temp-rooted namespace is the shared-backend leak signature: a test or
    demo harness indexed a throwaway directory into the shared server backend
    and never tore it down, and because the directory still exists it
    classifies ``live`` and survives pruning forever. The flag is report-only
    operator visibility - it never feeds any destructive path, per the
    time-confirmed-danglingness rule.
    """
    if root is None:
        return False
    import os
    import pathlib
    import tempfile

    candidates = {tempfile.gettempdir()}
    for env_name in ("TEMP", "TMP", "TMPDIR"):
        env_value = os.environ.get(env_name)
        if env_value:
            candidates.add(env_value)
    candidates.update(("/tmp", "/var/tmp"))

    try:
        root_resolved = pathlib.Path(os.path.normcase(root)).resolve()
    except OSError:
        return False
    for candidate in candidates:
        try:
            base = pathlib.Path(os.path.normcase(candidate)).resolve()
        except OSError:
            continue
        if root_resolved == base or root_resolved.is_relative_to(base):
            return True
    return False


@dataclass(frozen=True)
class NamespaceSurvey:
    """One root namespace's survey record.

    Attributes:
        prefix: The collection prefix (``r{hash}_``).
        root: The resolved root path, or ``None`` when unattributable.
        status: ``"live"``, ``"orphaned"``, or ``"unknown"``.
        collections: The stored collection names sharing this prefix.
        points: Total point count across the namespace's collections.
        footprint_bytes: Total on-disk footprint, when known.
    """

    prefix: str
    root: str | None
    status: str
    collections: list[str] = field(default_factory=list)
    points: int = 0
    vault_points: int = 0
    code_points: int = 0
    document_points: int = 0
    footprint_bytes: int = 0


def _kind_points(names: list[str], counts: dict[str, int], suffix: str) -> int:
    """Return the bounded integer count for one declared collection kind."""
    return sum(counts.get(name, 0) for name in names if name.endswith(suffix))


def _prefix_of(collection_name: str) -> str:
    """Return the ``r{hash}_`` prefix of a collection name, or the name.

    A name without the namespacing prefix (e.g. a bare local-mode name)
    is returned unchanged so it surfaces as its own unattributable entry
    rather than being silently dropped.
    """
    match = _PREFIX_RE.match(collection_name)
    return match.group(1) if match else collection_name


def classify_namespaces(
    collection_names: list[str],
    manifest: dict[str, ManifestEntry],
    *,
    point_counts: dict[str, int] | None = None,
    footprints: dict[str, int] | None = None,
) -> list[NamespaceSurvey]:
    """Group collections by prefix and classify each namespace.

    Args:
        collection_names: All stored collection names to survey.
        manifest: Prefix-to-entry mapping from
            :func:`storage_manifest.load_manifest`.
        point_counts: Optional per-collection-name point counts.
        footprints: Optional per-collection-name byte footprints.

    Returns:
        One :class:`NamespaceSurvey` per prefix, sorted with orphaned and
        unknown (the actionable states) before live, then by prefix.
    """
    counts = point_counts or {}
    sizes = footprints or {}
    grouped: dict[str, list[str]] = defaultdict(list)
    for name in collection_names:
        grouped[_prefix_of(name)].append(name)

    surveys: list[NamespaceSurvey] = []
    for prefix, names in grouped.items():
        entry = manifest.get(prefix)
        if entry is None:
            root, status = None, "unknown"
        else:
            root, status = entry.root, classify_root(entry)
        surveys.append(
            NamespaceSurvey(
                prefix=prefix,
                root=root,
                status=status,
                collections=sorted(names),
                points=sum(counts.get(n, 0) for n in names),
                vault_points=_kind_points(
                    names,
                    counts,
                    store_schema.VAULT_COLLECTION,
                ),
                code_points=_kind_points(
                    names,
                    counts,
                    store_schema.CODE_COLLECTION,
                ),
                document_points=_kind_points(
                    names,
                    counts,
                    store_schema.DOCUMENT_COLLECTION,
                ),
                footprint_bytes=sum(sizes.get(n, 0) for n in names),
            )
        )

    # Bias the view toward actionable state: orphaned, then unknown and
    # unverifiable (both need operator attention), then live.
    status_rank = {"orphaned": 0, "unknown": 1, "unverifiable": 2, "live": 3}
    surveys.sort(key=lambda s: (status_rank.get(s.status, 4), s.prefix))
    return surveys
