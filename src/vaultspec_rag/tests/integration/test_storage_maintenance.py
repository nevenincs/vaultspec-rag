"""End-to-end test of the scheduled storage-maintenance cycle.

Drives a real background service (server mode) with a seconds-scale
maintenance interval and stages real namespaces in its managed qdrant:
an aged empty orphan must be reclaimed, a fresh orphan must wait out its
grace window, a reappearing root must reset its clock, and every cycle
must be auditable through the ``/jobs`` registry. The grace clocks are
staged through the real manifest in the isolated status dir - the same
file the daemon reads - never through fakes.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import pytest

from ...serviceclient import _do_http_call
from ...storage_manifest import load_manifest, record_root, update_orphan_stamps
from ...store import root_collection_prefix

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration, pytest.mark.subprocess_gpu]

# Seconds-scale cadence so the test observes several cycles quickly.
_INTERVAL_MINUTES = "0.05"


def _make_namespace(qdrant_port: int, prefix: str) -> None:
    """Create a minimal real collection under *prefix* on the managed server."""
    from qdrant_client import QdrantClient, models

    client = QdrantClient(url=f"http://127.0.0.1:{qdrant_port}")
    try:
        client.create_collection(
            collection_name=f"{prefix}vault_docs",
            vectors_config={
                "dense": models.VectorParams(size=4, distance=models.Distance.COSINE)
            },
        )
    finally:
        client.close()


def _collection_names(qdrant_port: int) -> set[str]:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=f"http://127.0.0.1:{qdrant_port}")
    try:
        return {c.name for c in client.get_collections().collections}
    finally:
        client.close()


def _wait_for_maintenance_jobs(
    port: int, *, started_after: float, timeout: float = 120.0
) -> list[dict[str, Any]]:
    """Poll ``/jobs`` until a maintenance cycle that STARTED after the
    given wall-clock instant has finished; return all finished cycles.

    Waiting on start time (not merely on any finished cycle) is what makes
    the assertions deterministic: a cycle that began before the test staged
    its state proves nothing about that state.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _do_http_call(port, "/jobs?limit=50", None)
        raw_jobs = (result or {}).get("jobs", [])
        jobs = [
            j
            for j in cast("list[dict[str, Any]]", raw_jobs)
            if j.get("source") == "maintenance" and j.get("finished_at")
        ]
        if any(float(str(j.get("started_at", 0))) > started_after for j in jobs):
            return jobs
        time.sleep(1.0)
    pytest.fail(f"no maintenance cycle started after the staging within {timeout}s")


def test_maintenance_cycle_reclaims_only_time_confirmed_orphans(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """One live pass over the reclamation contract.

    Aged empty orphan reclaimed; fresh orphan left waiting; reappearing
    root's grace clock cleared; cycles visible in the jobs registry.
    """
    from ...cli import _spawn_service, _terminate_pid, _write_service_status
    from ...config import get_config
    from ._helpers import _get_ephemeral_port, _poll_health, _service_env

    with _service_env(
        tmp_path,
        {"VAULTSPEC_RAG_STORAGE_AUTOPRUNE_INTERVAL_MINUTES": _INTERVAL_MINUTES},
    ):
        # Stage three real roots in the manifest the daemon will read:
        # aged (to be backdated past grace, empty), fresh (just orphaned),
        # returning (orphaned then reappearing). The root dirs must EXIST
        # at spawn so the daemon's startup manifest reconcile keeps their
        # entries (a gone root with no collections would be dropped).
        roots = {
            name: tmp_path / "roots" / name for name in ("aged", "fresh", "returning")
        }
        prefixes: dict[str, str] = {}
        for name, root in roots.items():
            root.mkdir(parents=True)
            record_root(root, backend="server")
            prefixes[name] = root_collection_prefix(root)

        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"
        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        _write_service_status(pid, port)
        _poll_health(port)
        qdrant_port = int(get_config().qdrant_port)

        for name in roots:
            _make_namespace(qdrant_port, prefixes[name])
        for root in roots.values():
            root.rmdir()

        # Backdate the aged root past the empty-tier grace window. The
        # daemon's cycle may stamp a fresh observation first, and the
        # stamp helper deliberately preserves an existing stamp, so force
        # the backdate with a clear-then-set and verify it took (bounded
        # retries close the microscopic interleave window).
        old = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        for _attempt in range(5):
            update_orphan_stamps({prefixes["aged"]: "live"}, now_iso=old)
            update_orphan_stamps({prefixes["aged"]: "orphaned"}, now_iso=old)
            if load_manifest()[prefixes["aged"]].first_seen_orphaned == old:
                break
        else:
            pytest.fail("could not backdate the aged orphan's grace stamp")
        staged_at = time.time()

        _wait_for_maintenance_jobs(port, started_after=staged_at)
        names = _collection_names(qdrant_port)
        assert f"{prefixes['aged']}vault_docs" not in names, (
            "aged empty orphan must be reclaimed"
        )
        assert f"{prefixes['fresh']}vault_docs" in names, (
            "fresh orphan must wait out its grace window"
        )
        assert prefixes["aged"] not in load_manifest(), (
            "reclaimed namespace must be forgotten by the manifest"
        )

        # The returning root reappears: its grace clock must clear on the
        # next full cycle, and its data must survive.
        roots["returning"].mkdir(parents=True)
        recreated_at = time.time()
        jobs = _wait_for_maintenance_jobs(port, started_after=recreated_at)
        entry = load_manifest()[prefixes["returning"]]
        assert entry.first_seen_orphaned == "", (
            "a reappearing root must reset its grace clock"
        )
        assert f"{prefixes['returning']}vault_docs" in _collection_names(qdrant_port)

        # Every cycle is auditable: finished maintenance jobs with the
        # schedule trigger and a rollup summary.
        assert all(j.get("trigger") == "schedule" for j in jobs)
        assert any("removed=" in str(j.get("result", "")) for j in jobs)
