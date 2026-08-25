"""Build a real archive directory on disk for the restore tests.

The archive reader's whole contract is about what it finds on the
filesystem, so the tests hand it a real directory with a real manifest and
real snapshot bytes rather than a description of one. This builder writes
the shape the archiver writes; a test that wants a broken archive builds a
good one and then breaks exactly the thing it is about.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

#: A canonical namespace prefix, in the ``r{hash}_`` shape the survey accepts.
ARCHIVE_PREFIX = "rdeadbeefcafe_"

#: The one collection the default archive carries.
ARCHIVE_COLLECTION = f"{ARCHIVE_PREFIX}vault_docs"


def write_archive(
    path: Path,
    *,
    snapshot: bytes = b"snapshot",
    identity: dict[str, object] | None = None,
    points: int = 7,
    schema_version: int = 2,
) -> Path:
    """Write one complete archive directory and return it.

    Args:
        path: The archive directory to create.
        snapshot: The snapshot artifact's bytes. Empty bytes produce the
            zero-length file the reader must refuse.
        identity: The archived per-collection identity, or ``None`` for the
            identity-less archives every archive written so far carries.
        points: The recorded point count for the archived collection.
        schema_version: The archived storage schema generation, which a
            restore carries verbatim rather than restamping.

    Returns:
        The archive directory, so a caller can build and address it in one
        expression.
    """
    path.mkdir(parents=True)
    (path / "vault.snapshot").write_bytes(snapshot)
    (path / "snapshot-manifest.json").write_text(
        json.dumps(
            {
                "prefix": ARCHIVE_PREFIX,
                "completed_at": "2026-07-27T00:00:00+00:00",
                "storage_schema_version": schema_version,
                "collections": [
                    {
                        "name": ARCHIVE_COLLECTION,
                        "snapshot_file": "vault.snapshot",
                        "points": points,
                        "identity": identity,
                    }
                ],
                "metadata_files": [],
            }
        ),
        encoding="utf-8",
    )
    return path
