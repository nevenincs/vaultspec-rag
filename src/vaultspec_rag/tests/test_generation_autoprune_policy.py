"""Maintenance disable policy against real CPU-local Qdrant and run ledgers."""

from __future__ import annotations

import json
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from qdrant_client import models

from .._qdrant_local_client import open_local_client
from .._store_models import (
    generation_code_collection,
    publish_served_code_collection,
    root_collection_prefix,
)
from ..config._types import EnvVar
from ..generation_stamps import load_generation_stamps, record_generation_stamps
from ..server._lifecycle import _build_reclaim_policy
from ..storage_reclamation import (
    MaintenanceCycleRequest,
    _reclaim_generations_for_cycle,
    run_maintenance_cycle,
)
from ..storage_survey import NamespaceSurvey
from ..store_schema import CODE_COLLECTION
from ._storage_archive import write_archive
from .conftest import managed_env
from .test_generation_survey import _publish_code_proof

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("isolated_singleton_dirs")]


@pytest.mark.parametrize("autoprune", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
def test_generation_deletion_obeys_configured_autoprune_and_explicit_dry_run(
    tmp_path: Path, autoprune: bool, dry_run: bool
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    prefix = root_collection_prefix(root)
    derived = f"{prefix}{CODE_COLLECTION}"
    served = f"{derived}_gserved"
    old = f"{derived}_gsuperseded"
    now = datetime.now(UTC)
    with managed_env(
        **{
            EnvVar.STORAGE_AUTOPRUNE.value: "1" if autoprune else "0",
            EnvVar.STORAGE_RECONCILE.value: "1",
        }
    ):
        proof_collection = generation_code_collection(
            derived, _publish_code_proof(root)
        )
        publish_served_code_collection(root, served)
        names = [derived, served, proof_collection, old]
        policy = _build_reclaim_policy()
        assert policy.reconcile is True
        assert (policy.max_per_cycle > 0) is autoprune
        record_generation_stamps({old: (now - timedelta(hours=200)).isoformat()})
        before = load_generation_stamps()
        with closing(open_local_client(tmp_path / "qdrant")) as client:
            for name in names:
                client.create_collection(
                    collection_name=name,
                    vectors_config=models.VectorParams(
                        size=8, distance=models.Distance.COSINE
                    ),
                )
            results = _reclaim_generations_for_cycle(
                client,
                surveys=[
                    NamespaceSurvey(
                        prefix=prefix,
                        root=str(root.resolve()),
                        status="live",
                        collections=names,
                    )
                ],
                now=now,
                policy=policy,
                dry_run=dry_run,
            )
            live = {entry.name for entry in client.get_collections().collections}
        assert {derived, served, proof_collection} <= live
        expected_removal = autoprune and not dry_run
        assert (old not in live) is expected_removal
        assert [(result.prefix, result.status) for result in results] == [
            (old, "removed" if expected_removal else "would_remove")
        ]
        assert load_generation_stamps() == ({} if expected_removal else before)


def test_disabled_autoprune_still_persists_new_generation_grace_observation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    prefix = root_collection_prefix(root)
    derived = f"{prefix}{CODE_COLLECTION}"
    old = f"{derived}_gsuperseded"
    now = datetime.now(UTC)
    with managed_env(**{EnvVar.STORAGE_AUTOPRUNE.value: "0"}):
        _publish_code_proof(root)
        record_generation_stamps({})
        with closing(open_local_client(tmp_path / "qdrant")) as client:
            client.create_collection(
                collection_name=old,
                vectors_config=models.VectorParams(
                    size=8, distance=models.Distance.COSINE
                ),
            )
            results = _reclaim_generations_for_cycle(
                client,
                surveys=[NamespaceSurvey(prefix=prefix, root=str(root), status="live")],
                now=now,
                policy=_build_reclaim_policy(),
                dry_run=False,
            )
            assert client.collection_exists(old)
        assert load_generation_stamps() == {old: now.isoformat()}
        assert [(result.prefix, result.status) for result in results] == [
            (old, "skipped")
        ]


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
