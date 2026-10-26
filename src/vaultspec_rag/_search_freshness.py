"""Bounded checks of delivered hits against canonical file evidence on disk."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._publication_state import acquire_publication_snapshot
from ._source_types import IndexSource, PublicSourceType
from .indexer._file_state import validate_rel_path
from .indexer._source_file import open_source_file, source_file_stat

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ._publication_state import PublicationSnapshot
    from .search._models import DocumentSearchResult, SearchResult

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_PAGE_BYTES = 8 * 1024 * 1024
MAX_CHECK_SECONDS = 0.1


@dataclass(frozen=True, slots=True)
class DriftedFile:
    """A confirmed disk difference relative to one published file identity."""

    source: IndexSource
    path: str
    reason: str


def capture_hit_publications(
    root: Path, sources: tuple[IndexSource, ...]
) -> dict[IndexSource, PublicationSnapshot]:
    """Capture proof fences before retrieval; unavailable evidence stays unknown."""
    snapshots: dict[IndexSource, PublicationSnapshot] = {}
    for source in sources:
        try:
            snapshots[source] = acquire_publication_snapshot(
                root, PublicSourceType(source)
            )
        except Exception:
            # A failed optional read cannot make an otherwise usable hit fail.
            continue
    return snapshots


def _source(result: SearchResult | DocumentSearchResult) -> IndexSource:
    return "code" if result.source == "codebase" else result.source


def _path(result: SearchResult | DocumentSearchResult) -> str:
    return getattr(result, "source_path", None) or result.path


def _identity(path: Path, root: Path, source: IndexSource, data: bytes) -> str:
    if source == "vault":
        from .indexer._vault_fingerprint import fingerprint_bytes

        return fingerprint_bytes(path, root, data)
    return hashlib.blake2b(data).hexdigest()


def _matches(source: IndexSource, expected: str, current: str) -> bool:
    if source == "vault":
        from .indexer._vault_fingerprint import VaultDelta, classify

        return classify(expected, current) is VaultDelta.UNCHANGED
    return expected == current


def _stable_stat(observed: os.stat_result) -> tuple[int, ...]:
    return (
        observed.st_dev,
        observed.st_ino,
        observed.st_size,
        observed.st_mtime_ns,
        observed.st_ctime_ns,
    )


def _read_file(
    path: Path,
    root: Path,
    budget: int,
) -> tuple[bytes | None, str | None, int]:
    consumed = 0
    try:
        named_before = source_file_stat(path, root)
        with open_source_file(path, root) as stream:
            before = os.fstat(stream.fileno())
            if before.st_size > min(MAX_FILE_BYTES, budget):
                return None, None, consumed
            data = stream.read(min(MAX_FILE_BYTES, budget) + 1)
            consumed = len(data)
            after = os.fstat(stream.fileno())
        named = source_file_stat(path, root)
        if (
            len(data) > min(MAX_FILE_BYTES, budget)
            or not (
                _stable_stat(before) == _stable_stat(after)
                and _stable_stat(named_before) == _stable_stat(named)
                # Windows descriptor and path stat expose different ctime semantics.
                and _stable_stat(after)[:-1] == _stable_stat(named)[:-1]
            )
        ):
            return None, None, consumed
        return data, None, consumed
    except FileNotFoundError:
        # A missing project/mount is not proof that an individual file was deleted.
        try:
            canonical = path.resolve() == path
        except OSError:
            return None, None, consumed
        reason = "file_missing" if root.is_dir() and canonical else None
        return None, reason, consumed
    except OSError:
        return None, None, consumed


@dataclass(slots=True)
class _PageBudget:
    root: Path
    started: float = field(default_factory=time.monotonic)
    remaining: int = MAX_PAGE_BYTES
    files: dict[str, tuple[bytes | None, str | None]] = field(default_factory=dict)


def _check_paths(
    budget: _PageBudget,
    source: IndexSource,
    expected: dict[str, str],
) -> dict[str, tuple[str, str | None]]:
    checks: dict[str, tuple[str, str | None]] = {}
    for relative, identity in expected.items():
        path = budget.root / relative
        if relative not in budget.files:
            if (
                time.monotonic() - budget.started >= MAX_CHECK_SECONDS
                or budget.remaining <= 0
            ):
                continue
            data, reason, consumed = _read_file(path, budget.root, budget.remaining)
            budget.remaining -= consumed
            budget.files[relative] = (data, reason)
        data, reason = budget.files[relative]
        if data is not None:
            current = _identity(path, budget.root, source, data)
            reason = None if _matches(source, identity, current) else "content_changed"
            checks[relative] = ("current" if reason is None else "stale", reason)
        elif reason is not None:
            checks[relative] = ("stale", reason)
    return checks


def _source_checks(
    budget: _PageBudget,
    source: IndexSource,
    snapshot: PublicationSnapshot,
    paths: tuple[str, ...],
) -> dict[str, tuple[str, str | None]]:
    try:
        for path in paths:
            validate_rel_path(path)
        expected = snapshot.ledger.publication_content_for_paths(
            snapshot.proof.compatibility_key, paths
        )
        expected = {path: expected[path] for path in paths if path in expected}
        checks = _check_paths(budget, source, expected)
        snapshot.validate()
        return checks
    except Exception:
        return {}


def verify_search_hits(
    root: Path,
    results: Sequence[SearchResult | DocumentSearchResult],
    snapshots: dict[IndexSource, PublicationSnapshot],
) -> tuple[DriftedFile, ...]:
    """Check only the delivered page, once per file, with no cross-request cache.

    A changed proof fence invalidates all checks for that source. Stat evidence
    detects writes during reads, but never substitutes for a content comparison.
    """
    budget = _PageBudget(root.resolve())
    checks: dict[tuple[IndexSource, str], tuple[str, str | None]] = {}
    for source, snapshot in snapshots.items():
        selected = [result for result in results if _source(result) == source]
        paths = tuple(dict.fromkeys(_path(result) for result in selected))
        checks.update(
            {
                (source, path): observation
                for path, observation in _source_checks(
                    budget, source, snapshot, paths
                ).items()
            }
        )
    drift: dict[tuple[IndexSource, str], DriftedFile] = {}
    for result in results:
        key = (_source(result), _path(result))
        freshness, reason = checks.get(key, ("unverifiable", None))
        if freshness == "current":
            result.freshness = "current"
        elif freshness == "stale":
            result.freshness = "stale"
            drift[key] = DriftedFile(key[0], key[1], reason or "content_changed")
        else:
            result.freshness = "unverifiable"
        result.stale_reason = reason
    return tuple(drift.values())
