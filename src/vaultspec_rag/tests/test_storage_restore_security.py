"""Real-filesystem checks at the archive restore read boundary."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ..storage_restore import (
    ArchiveIntegrityError,
    _open_archive_file,
    _open_member_descriptor,
    read_archive,
)
from ._storage_archive import write_archive

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("filename", ["vault.snapshot", "snapshot-manifest.json"])
@pytest.mark.parametrize("inside", [False, True])
def test_read_archive_rejects_linked_members(
    tmp_path: Path, filename: str, inside: bool
) -> None:
    """The original link-following reader failed here with DID NOT RAISE.

    Both inside and outside links passed the original reader; the checked
    opener rejects all four cases at the regular-file assertion.
    """
    archive = write_archive(tmp_path / "archive")
    member = archive / filename
    target = (archive if inside else tmp_path) / "operator-file"
    member.replace(target)
    member.symlink_to(target)

    with pytest.raises(ArchiveIntegrityError, match="regular file"):
        read_archive(archive)


def test_read_archive_rejects_a_linked_root(tmp_path: Path) -> None:
    """The original reader failed with DID NOT RAISE; the checked reader passes."""
    archive = write_archive(tmp_path / "outside")
    linked = tmp_path / "archive"
    linked.symlink_to(archive, target_is_directory=True)

    with pytest.raises(ArchiveIntegrityError, match="non-symlink directory"):
        read_archive(linked)


def test_member_descriptor_does_not_follow_a_link(tmp_path: Path) -> None:
    """Removing the native no-follow flag admits the operator file descriptor.

    Clearing the Windows flag failed on ``assert not samestat``. Restoring
    it passed. The POSIX equivalent fails on DID NOT RAISE when O_NOFOLLOW
    is removed, then passes with it restored.
    """
    outside = tmp_path / "operator-file"
    outside.write_bytes(b"operator-only bytes")
    linked = tmp_path / "snapshot"
    linked.symlink_to(outside)

    if os.name == "nt":
        descriptor = _open_member_descriptor(linked, None)
        try:
            assert not os.path.samestat(outside.stat(), os.fstat(descriptor))
        finally:
            os.close(descriptor)
    else:
        with pytest.raises(OSError):
            _open_member_descriptor(linked, None)


@pytest.mark.parametrize("filename", ["vault.snapshot", "snapshot-manifest.json"])
@pytest.mark.parametrize(
    "kind", ["directory", "fifo"] if os.name == "posix" else ["directory"]
)
def test_read_archive_rejects_a_nonregular_member(
    tmp_path: Path, filename: str, kind: str
) -> None:
    archive = write_archive(tmp_path / "archive")
    member = archive / filename
    member.unlink()
    if kind == "directory":
        member.mkdir()
    else:
        os.mkfifo(member)

    with pytest.raises(ArchiveIntegrityError, match="regular file"):
        read_archive(archive)


def test_open_member_retains_its_descriptor_after_path_replacement(
    tmp_path: Path,
) -> None:
    """Reopening the path after validation would read the operator's bytes."""
    archive = write_archive(tmp_path / "archive", snapshot=b"archived bytes")
    member = archive / "vault.snapshot"
    outside = tmp_path / "operator-file"
    outside.write_bytes(b"operator-only bytes")

    with _open_archive_file(member) as snapshot:
        if os.name == "nt":
            # The Windows sharing mode prevents replacing an open member.
            with pytest.raises(PermissionError):
                member.replace(tmp_path / "original.snapshot")
        else:
            member.replace(tmp_path / "original.snapshot")
            member.symlink_to(outside)
        assert snapshot.read() == b"archived bytes"


def test_open_member_retains_its_descriptor_after_root_replacement(
    tmp_path: Path,
) -> None:
    """Replacing a validated directory cannot redirect the already-open file."""
    archive = write_archive(tmp_path / "archive", snapshot=b"archived bytes")
    outside = write_archive(tmp_path / "outside", snapshot=b"operator-only bytes")

    with _open_archive_file(archive / "vault.snapshot") as snapshot:
        if os.name == "nt":
            with pytest.raises(PermissionError):
                archive.rename(tmp_path / "original")
        else:
            archive.rename(tmp_path / "original")
            archive.symlink_to(outside, target_is_directory=True)
        assert snapshot.read() == b"archived bytes"
