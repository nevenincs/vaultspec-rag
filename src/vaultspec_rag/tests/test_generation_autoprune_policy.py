"""Maintenance disable policy and reset isolation against real CPU-local Qdrant."""

from __future__ import annotations

import json
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from qdrant_client import models

from .._qdrant_local_client import open_local_client
from .._source_types import PublicSourceType
from .._store_models import read_served_pointer
from ..config._types import EnvVar
from ..indexer._rebuild_lifecycle import capture_reset_epoch
from ..server._lifecycle import _build_reclaim_policy
from ..storage_manifest import record_root
from ..storage_reclamation import MaintenanceCycleRequest, run_maintenance_cycle
from ..store_runtime import configured_backend_identity
from ..store_schema import CODE_COLLECTION, DENSE_VECTOR_NAME
from ._historical_code_layout import historical_generation, write_historical_pointer
from ._storage_archive import write_archive
from .conftest import managed_env

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("isolated_singleton_dirs")]


@pytest.mark.parametrize("autoprune", [False, True])
def test_maintenance_leaves_a_live_roots_historical_code_layout_intact(
    tmp_path: Path, autoprune: bool
) -> None:
    """Only an explicit code reset of its root discards a historical layout.

    The root is live and attributed, serves a historical generation through
    its pointer, and still holds a superseded one. A full maintenance cycle,
    with autoprune on or off, deletes none of it, leaves the pointer naming the
    served generation, and records no reset of the root's code.

    Mutation: dropping a live root's generation collections inside
    ``run_maintenance_cycle`` failed the survivor assertion with autoprune on
    and off; restoring the cycle passed.
    """
    root = tmp_path / "project"
    root.mkdir()
    prefix = record_root(root, backend="server").prefix
    derived = f"{prefix}{CODE_COLLECTION}"
    served = historical_generation(derived, "served")
    superseded = historical_generation(derived, "superseded")
    names = (derived, served, superseded)
    write_historical_pointer(root, served)
    with (
        managed_env(
            **{
                EnvVar.STORAGE_AUTOPRUNE.value: "1" if autoprune else "0",
                EnvVar.STORAGE_RECONCILE.value: "1",
            }
        ),
        closing(open_local_client(tmp_path / "qdrant")) as client,
    ):
        policy = _build_reclaim_policy()
        assert (policy.max_per_cycle > 0) is autoprune
        for name in names:
            client.create_collection(
                collection_name=name,
                vectors_config={
                    DENSE_VECTOR_NAME: models.VectorParams(
                        size=8, distance=models.Distance.COSINE
                    )
                },
            )
            client.upsert(
                collection_name=name,
                points=[
                    models.PointStruct(id=1, vector={DENSE_VECTOR_NAME: [1.0] * 8})
                ],
                wait=True,
            )
        result = run_maintenance_cycle(
            MaintenanceCycleRequest(
                client=client,
                now=datetime.now(UTC),
                policy=policy,
                storage_dir=None,
                snapshots_dir=tmp_path / "snapshots",
                archive_dir=tmp_path / "archives",
            )
        )
        survivors = {
            name: client.count(collection_name=name, exact=True).count
            for name in names
            if client.collection_exists(name)
        }
    assert survivors == dict.fromkeys(names, 1)
    assert [survey.status for survey in result.surveys] == ["live"]
    assert read_served_pointer(root, derived) == (served, True)
    fence = capture_reset_epoch(
        root, PublicSourceType.CODE, configured_backend_identity(root)
    )
    assert (fence.epoch, fence.phase) == (0, None)


@pytest.mark.parametrize("reason", ["retention", "capacity"])
@pytest.mark.parametrize("autoprune", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
def test_archive_retention_obeys_autoprune_without_disabling_reconciliation(
    tmp_path: Path, reason: str, autoprune: bool, dry_run: bool
) -> None:
    now = datetime.now(UTC)
    archive_root = tmp_path / "archives"
    completed = write_archive(archive_root / "completed")
    manifest = completed / "snapshot-manifest.json"
    contents = json.loads(manifest.read_text(encoding="utf-8"))
    contents["completed_at"] = (
        now - timedelta(days=31 if reason == "retention" else 1)
    ).isoformat()
    manifest.write_text(json.dumps(contents), encoding="utf-8")
    before = {path.name: path.read_bytes() for path in completed.iterdir()}
    with (
        managed_env(
            **{
                EnvVar.STORAGE_AUTOPRUNE.value: "1" if autoprune else "0",
                EnvVar.STORAGE_RECONCILE.value: "1",
                EnvVar.STORAGE_AUTOPRUNE_ARCHIVE_MAX_GB.value: (
                    "0.000000001" if reason == "capacity" else "64"
                ),
            }
        ),
        closing(open_local_client(tmp_path / "qdrant")) as client,
    ):
        result = run_maintenance_cycle(
            MaintenanceCycleRequest(
                client=client,
                now=now,
                policy=_build_reclaim_policy(),
                storage_dir=None,
                snapshots_dir=tmp_path / "snapshots",
                archive_dir=archive_root,
                dry_run=dry_run,
            )
        )
    assert result.reconcile is not None
    assert result.reconcile.dry_run is dry_run
    expected_removal = autoprune and not dry_run
    assert completed.exists() is not expected_removal
    assert result.swept == ([completed] if expected_removal else [])
    if not expected_removal:
        assert {path.name: path.read_bytes() for path in completed.iterdir()} == before
