"""End-to-end tests for the read-only storage survey service surface.

Drives the real background service (server mode) and asserts the survey
flows through three consistent surfaces: the daemon's ``/storage/survey``
route, the MCP ``survey_storage`` tool, and the service-first CLI path.
This is the one read-only storage surface the service owns; the
destructive prune / delete / migrate verbs stay CLI-direct and are not
exposed here. No GPU work runs in the survey itself - it is pure storage
classification against the managed server and the persisted manifest.
"""

from __future__ import annotations

import time
import urllib.parse
from typing import TYPE_CHECKING, cast

import pytest

from ..._job_values import count
from ..._store_models import root_collection_prefix
from ...serviceclient._transport import _do_http_call, _try_http_admin

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.subprocess_gpu]


def _survey_root_call(
    port: int, root: Path, *, fresh: bool = False
) -> dict[str, object]:
    """Query the survey route scoped to *root* and return the envelope."""
    quoted = urllib.parse.quote(str(root))
    suffix = "&fresh=true" if fresh else ""
    result = _do_http_call(port, f"/storage/survey?root={quoted}{suffix}", None)
    assert result is not None
    return result


def _wait_for_job(port: int, job_id: str, timeout: float = 120.0) -> None:
    """Poll ``/jobs`` until *job_id* reaches a terminal phase."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs_result = _do_http_call(port, "/jobs?limit=50", None)
        raw_jobs = (jobs_result or {}).get("jobs", [])
        jobs = cast("list[dict[str, object]]", raw_jobs)
        matched = [j for j in jobs if j.get("id") == job_id]
        if matched and matched[0].get("phase") in ("done", "error", "failed"):
            assert matched[0]["phase"] == "done", f"job failed: {matched[0]}"
            return
        time.sleep(0.25)
    pytest.fail(f"job {job_id} did not finish within {timeout}s")


@pytest.mark.usefixtures("live_service")
def test_storage_survey_route_returns_bounded_envelope(
    live_service: tuple[int, Path],
) -> None:
    """The ``/storage/survey`` route answers with the bounded survey envelope.

    A freshly started service has no indexed roots, so the survey is empty,
    but the envelope (namespaces / returned / total / limit) must be shaped
    and bounded regardless.
    """
    port, _status_dir = live_service
    result = _do_http_call(port, "/storage/survey", None)
    assert result is not None
    assert isinstance(result.get("namespaces"), list)
    assert "returned" in result
    assert "total" in result
    # Routed through the canonical reader because a bare int assert admitted
    # exactly the value it existed to reject: isinstance(True, int) and
    # True > 0 both hold, so a published ``limit: True`` passed the pin.
    limit = count(result.get("limit"))
    assert limit is not None
    assert limit > 0


@pytest.mark.usefixtures("live_service")
def test_storage_survey_route_rejects_bad_status(
    live_service: tuple[int, Path],
) -> None:
    """An unknown ``?status=`` value is a 400, not a silent empty survey."""
    port, _status_dir = live_service
    result = _do_http_call(port, "/storage/survey?status=bogus", None)
    assert result is not None
    assert result.get("ok") is False
    assert result.get("error") == "bad_request"


@pytest.mark.usefixtures("live_service")
def test_storage_survey_route_honours_limit(
    live_service: tuple[int, Path],
) -> None:
    """A ``?limit=`` is echoed and clamped into the response envelope."""
    port, _status_dir = live_service
    result = _do_http_call(port, "/storage/survey?limit=5", None)
    assert result is not None
    assert result.get("limit") == 5


@pytest.mark.usefixtures("live_service")
def test_admin_client_maps_storage_survey_filters(
    live_service: tuple[int, Path],
) -> None:
    """The admin client maps status + limit filters onto the survey route."""
    port, _status_dir = live_service
    result = _try_http_admin(
        "get_storage_survey", {"status": "orphaned", "limit": 3}, port
    )
    assert result is not None
    # Filtered to orphaned (empty on a fresh service) but the envelope holds.
    assert result.get("limit") == 3
    assert isinstance(result.get("namespaces"), list)


@pytest.mark.usefixtures("live_service")
def test_storage_survey_root_lookup_unindexed_root(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    """An unindexed root still gets its authoritative prefix, namespaces empty.

    The whole point of the lookup: a consumer never recomputes the blake2b
    derivation, even for a root the manifest has never seen.
    """
    port, _status_dir = live_service
    root = tmp_path / "never-indexed-root"
    root.mkdir()
    result = _survey_root_call(port, root)
    raw_queried = result.get("queried_root")
    assert isinstance(raw_queried, dict)
    queried = cast("dict[str, object]", raw_queried)
    assert queried.get("prefix") == root_collection_prefix(root)
    assert result.get("namespaces") == []


@pytest.mark.usefixtures("live_service")
def test_storage_survey_root_rejects_empty(
    live_service: tuple[int, Path],
) -> None:
    """An empty ``?root=`` is a 400, not a survey of the daemon's cwd."""
    port, _status_dir = live_service
    result = _do_http_call(port, "/storage/survey?root=", None)
    assert result is not None
    assert result.get("ok") is False
    assert result.get("error") == "bad_request"


@pytest.mark.usefixtures("live_service")
def test_admin_client_passes_root_through(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    """The admin client forwards ``root``; the service computes the prefix."""
    port, _status_dir = live_service
    root = tmp_path / "adapter-root"
    root.mkdir()
    result = _try_http_admin("get_storage_survey", {"root": str(root)}, port)
    assert result is not None
    raw_queried = result.get("queried_root")
    assert isinstance(raw_queried, dict)
    queried = cast("dict[str, object]", raw_queried)
    assert queried.get("prefix") == root_collection_prefix(root)


@pytest.mark.usefixtures("live_service")
def test_storage_survey_root_lookup_indexed_root(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    """An indexed root's lookup returns its prefix plus populated namespaces."""
    from ..corpus import build_synthetic_vault

    port, _status_dir = live_service
    root = tmp_path / "indexed-root"
    root.mkdir()
    build_synthetic_vault(root, n_docs=6, seed=77)

    reindex = _do_http_call(
        port,
        "/reindex",
        {"type": "vault", "clean": True, "project_root": str(root)},
    )
    assert reindex is not None and reindex.get("ok") is True, reindex
    job_id = reindex.get("job_id")
    assert isinstance(job_id, str)
    _wait_for_job(port, job_id)

    # fresh=true: the just-indexed namespace must be visible immediately,
    # not after the snapshot's next scheduled refresh.
    result = _survey_root_call(port, root, fresh=True)
    raw_queried = result.get("queried_root")
    assert isinstance(raw_queried, dict)
    queried = cast("dict[str, object]", raw_queried)
    prefix = root_collection_prefix(root)
    assert queried.get("prefix") == prefix
    raw_namespaces = result.get("namespaces")
    assert isinstance(raw_namespaces, list) and raw_namespaces, (
        "indexed root must surface its namespace"
    )
    namespaces = cast("list[dict[str, object]]", raw_namespaces)
    assert all(ns.get("prefix") == prefix for ns in namespaces)


@pytest.mark.usefixtures("live_service")
def test_storage_survey_reports_freshness_metadata(
    live_service: tuple[int, Path],
) -> None:
    """Every survey answer carries ``computed_at`` and ``source``."""
    port, _status_dir = live_service
    result = _do_http_call(port, "/storage/survey", None)
    assert result is not None
    assert result.get("source") in ("cache", "fresh")
    computed_at = result.get("computed_at")
    assert isinstance(computed_at, str) and computed_at


@pytest.mark.usefixtures("live_service")
def test_storage_survey_serves_cache_after_warmup(
    live_service: tuple[int, Path],
) -> None:
    """The startup warmer fills the snapshot, then the route answers O(1).

    Polls past the warmup delay; once the snapshot is warm, consecutive
    plain calls are cache-served with a stable ``computed_at``.
    """
    port, _status_dir = live_service
    deadline = time.monotonic() + 60.0
    result: dict[str, object] | None = None
    while time.monotonic() < deadline:
        result = _do_http_call(port, "/storage/survey", None)
        if result is not None and result.get("source") == "cache":
            break
        time.sleep(0.5)
    assert result is not None and result.get("source") == "cache", (
        f"snapshot never warmed: {result}"
    )
    again = _do_http_call(port, "/storage/survey", None)
    assert again is not None
    assert again.get("source") == "cache"
    # Read the stamp before comparing: two absent stamps are equal, so a
    # response that dropped the field entirely would satisfy a bare
    # comparison while proving nothing about the snapshot being reused.
    warmed_at = result.get("computed_at")
    assert warmed_at is not None, f"warmed response carried no stamp: {result}"
    assert again.get("computed_at") == warmed_at


def _expected_totals(
    namespaces: list[dict[str, object]],
) -> tuple[int, int, int]:
    """Recompute ``collections``, ``ephemeral_backlog_bytes``, and
    ``points_unverified_namespaces`` client-side.

    Independent of the route's own aggregation, so a snapshot's reported
    ``totals`` can be checked for internal consistency against the very
    per-namespace list it was computed from, rather than against a second,
    separately timed call that a live daemon's own background writes (WAL
    checkpoints, manifest flushes) can drift out from under.
    """
    collections = sum(len(cast("list[object]", ns["collections"])) for ns in namespaces)
    backlog = sum(
        count(ns.get("footprint_bytes")) or 0
        for ns in namespaces
        if ns.get("status") == "orphaned" and ns.get("temp_rooted") is True
    )
    unverified = sum(1 for ns in namespaces if ns.get("points_verified") is False)
    return collections, backlog, unverified


@pytest.mark.usefixtures("live_service")
def test_storage_survey_totals_report_collections_and_ephemeral_backlog(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    """``totals`` reports the whole-backend collection count and backlog.

    ``collections`` sums every Qdrant collection across every namespace -
    distinct from ``namespaces``, since one root can hold several
    collections. ``ephemeral_backlog_bytes`` is the footprint of namespaces
    that are both orphaned and temp-rooted: the population the ephemeral
    grace window drains first. A namespace that is still live must not
    count toward that backlog, even though its root sits under the same OS
    temp directory pytest itself uses. Every namespace also carries its own
    ``points_verified``, and ``totals`` rolls that up into
    ``points_unverified_namespaces`` - a freshly indexed namespace has a
    verified count, so it must not be counted there.

    Each check recomputes the expected figures from the very namespace list
    the same response carried, rather than from an earlier response: the
    shared daemon this suite reuses is a live system whose other namespaces
    keep changing footprint between calls (WAL checkpoints, manifest
    flushes), so only a same-snapshot comparison is not itself flaky.
    """
    import shutil

    from ..corpus import build_synthetic_vault

    port, _status_dir = live_service

    # tmp_path lives under the OS temp directory, so this root classifies
    # temp-rooted once indexed.
    root = tmp_path / "ephemeral-status-root"
    root.mkdir()
    build_synthetic_vault(root, n_docs=4, seed=91)
    reindex = _do_http_call(
        port,
        "/reindex",
        {"type": "vault", "clean": True, "project_root": str(root)},
    )
    assert reindex is not None and reindex.get("ok") is True, reindex
    job_id = reindex.get("job_id")
    assert isinstance(job_id, str)
    _wait_for_job(port, job_id)

    # Still live: temp-rooted, but not yet orphaned, so it must not be
    # counted in the backlog. A namespace this survey just counted itself
    # has a verified count.
    live_check = _survey_root_call(port, root, fresh=True)
    live_namespaces = cast("list[dict[str, object]]", live_check["namespaces"])
    assert live_namespaces and live_namespaces[0]["status"] == "live"
    assert live_namespaces[0]["temp_rooted"] is True
    assert live_namespaces[0]["points_verified"] is True

    still_live = _do_http_call(port, "/storage/survey?limit=1000&fresh=true", None)
    assert still_live is not None
    still_live_totals = cast("dict[str, object]", still_live["totals"])
    still_live_namespaces = cast("list[dict[str, object]]", still_live["namespaces"])
    expected_collections, expected_backlog, expected_unverified = _expected_totals(
        still_live_namespaces
    )
    assert still_live_totals.get("collections") == expected_collections
    assert still_live_totals.get("ephemeral_backlog_bytes") == expected_backlog
    assert still_live_totals.get("points_unverified_namespaces") == expected_unverified
    prefix = live_namespaces[0]["prefix"]
    assert not any(
        ns["prefix"] == prefix
        and ns.get("status") == "orphaned"
        and ns.get("temp_rooted") is True
        for ns in still_live_namespaces
    ), "a still-live namespace must not be counted in its own backlog"
    assert not any(
        ns["prefix"] == prefix and ns.get("points_verified") is False
        for ns in still_live_namespaces
    ), "a namespace this survey just counted must not read as unverified"

    # Orphan it: the root is gone, the namespace remains, still temp-rooted.
    shutil.rmtree(root)
    orphaned = _survey_root_call(port, root, fresh=True)
    orphaned_namespaces = cast("list[dict[str, object]]", orphaned["namespaces"])
    assert orphaned_namespaces, "the namespace must survive its root's removal"
    entry = orphaned_namespaces[0]
    assert entry["status"] == "orphaned"
    assert entry["temp_rooted"] is True
    footprint = count(entry.get("footprint_bytes"))
    assert footprint is not None and footprint > 0

    after = _do_http_call(port, "/storage/survey?limit=1000&fresh=true", None)
    assert after is not None
    after_totals = cast("dict[str, object]", after["totals"])
    after_namespaces = cast("list[dict[str, object]]", after["namespaces"])
    after_expected_collections, after_expected_backlog, after_expected_unverified = (
        _expected_totals(after_namespaces)
    )
    assert after_totals.get("collections") == after_expected_collections
    assert after_totals.get("ephemeral_backlog_bytes") == after_expected_backlog
    assert after_totals.get("points_unverified_namespaces") == after_expected_unverified
    # Now that it is orphaned, its own footprint is part of the backlog.
    assert after_expected_backlog >= footprint


@pytest.mark.usefixtures("live_service")
def test_storage_survey_fresh_recomputes_and_reseeds_cache(
    live_service: tuple[int, Path],
) -> None:
    """``?fresh=true`` recomputes and its result becomes the new snapshot."""
    port, _status_dir = live_service
    fresh = _do_http_call(port, "/storage/survey?fresh=true", None)
    assert fresh is not None
    assert fresh.get("source") == "fresh"
    cached = _do_http_call(port, "/storage/survey", None)
    assert cached is not None
    assert cached.get("source") == "cache"
    # As above: the stamp must exist before equality means anything, or a
    # recompute that published no stamp would read as a successful reseed.
    fresh_at = fresh.get("computed_at")
    assert fresh_at is not None, f"fresh response carried no stamp: {fresh}"
    assert cached.get("computed_at") == fresh_at
