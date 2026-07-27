"""Filesystem-only contract checks for the archive reader and restore preview."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ..storage_restore import read_archive

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _write_archive(path: Path, *, snapshot: bytes = b"snapshot") -> None:
    path.mkdir(parents=True)
    (path / "vault.snapshot").write_bytes(snapshot)
    (path / "snapshot-manifest.json").write_text(
        json.dumps(
            {
                "prefix": "rdeadbeefcafe_",
                "completed_at": "2026-07-27T00:00:00+00:00",
                "storage_schema_version": 2,
                "collections": [
                    {
                        "name": "rdeadbeefcafe_vault_docs",
                        "snapshot_file": "vault.snapshot",
                        "points": 7,
                        "identity": None,
                    }
                ],
                "metadata_files": [],
            }
        ),
        encoding="utf-8",
    )


def test_read_archive_accepts_a_complete_namespace_without_mutation(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    _write_archive(archive)

    read = read_archive(archive)

    assert read.prefix == "rdeadbeefcafe_"
    assert read.schema_version == 2
    assert [(item.source, item.points, item.identity) for item in read.collections] == [
        ("rdeadbeefcafe_vault_docs", 7, None)
    ]


def test_read_archive_refuses_a_missing_snapshot_before_restore(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    _write_archive(archive)
    (archive / "vault.snapshot").unlink()

    with pytest.raises(RuntimeError, match="missing or empty"):
        read_archive(archive)


def test_read_archive_refuses_an_unparseable_completion_stamp(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    _write_archive(archive)
    manifest = archive / "snapshot-manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["completed_at"] = "not-a-timestamp"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="incomplete"):
        read_archive(archive)
