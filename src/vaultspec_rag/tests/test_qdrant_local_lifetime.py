"""Real local collection deletion must release its SQLite owner."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from qdrant_client import QdrantClient
from qdrant_client.qdrant_remote import QdrantRemote

from .._qdrant_local_lifetime import close_local_collection
from ._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS

pytestmark = [pytest.mark.unit]


def test_deleted_collection_closes_storage_in_fresh_process() -> None:
    script = """
import gc
import sqlite3
import tempfile
from pathlib import Path
from qdrant_client import QdrantClient, models
from vaultspec_rag._qdrant_local_lifetime import close_local_collection

with tempfile.TemporaryDirectory(prefix="qdrant-delete-lifetime-") as directory:
    client = QdrantClient(
        path=str(Path(directory) / "qdrant"),
        force_disable_check_same_thread=sqlite3.threadsafety == 3,
    )
    try:
        for name in ("keep", "drop"):
            client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=4, distance=models.Distance.COSINE
                ),
            )
            client.upsert(
                collection_name=name,
                points=[models.PointStruct(id=1, vector=[1.0, 0.0, 0.0, 0.0])],
                wait=True,
            )
        close_local_collection(client, "drop")
        assert client.delete_collection(collection_name="drop")
        assert not client.collection_exists("drop")
        assert client.count(collection_name="keep", exact=True).count == 1
    finally:
        client.close()
    gc.collect()
print("deleted-and-kept-points-verified")
"""
    child = subprocess.run(
        [sys.executable, "-W", "error", "-c", script],
        env={**os.environ, "PYTHONWARNINGS": "error"},
        capture_output=True,
        text=True,
        timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    assert child.stderr == "", child.stderr
    assert child.stdout.strip() == "deleted-and-kept-points-verified"


def test_remote_client_has_no_local_collection_to_close() -> None:
    client = QdrantClient(url="http://127.0.0.1:1", check_compatibility=False)
    try:
        close_local_collection(client, "absent")
        assert isinstance(client._client, QdrantRemote)
        assert not client._client.closed
    finally:
        client.close()
