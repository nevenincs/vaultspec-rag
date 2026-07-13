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
from typing import TYPE_CHECKING, Any, cast

import pytest

from ...serviceclient import _do_http_call, _try_http_admin
from ...store import root_collection_prefix

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.subprocess_gpu]


def _survey_root_call(port: int, root: Path) -> dict[str, Any]:
    """Query the survey route scoped to *root* and return the envelope."""
    quoted = urllib.parse.quote(str(root))
    result = _do_http_call(port, f"/storage/survey?root={quoted}", None)
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
    limit = result.get("limit")
    assert isinstance(limit, int)
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

    result = _survey_root_call(port, root)
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
