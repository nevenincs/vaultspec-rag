"""Long storage paths must not break the managed qdrant server.

Qdrant's storage engine fails every collection create on Windows once a
plainly-passed storage dir exceeds ~105 characters (the internal
``collections/<name>/segments/<uuid>/...`` layout crosses the classic
260-character MAX_PATH). The supervisor therefore hands the child
extended-length (``\\\\?\\``) paths. This regression test spawns a real
supervised qdrant against a storage dir padded past 140 characters and
creates a real collection with the production schema - the exact
operation that used to fail with "os error 3".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ... import store_schema
from ..._qdrant_server_client import open_server_client
from ...config._types import EnvVar
from ...qdrant_runtime._credential import read_managed_api_key
from ...qdrant_runtime._supervise import QdrantSupervisor
from .._fake_qdrant_binary import unpinned
from ..conftest import managed_env
from ._helpers import _get_ephemeral_qdrant_port, _resolve_host_provisioned_qdrant

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration]


def test_collection_create_succeeds_on_a_long_storage_path(tmp_path: Path) -> None:
    from qdrant_client import models

    host_qdrant = _resolve_host_provisioned_qdrant()
    assert host_qdrant is not None, (
        "a provisioned managed qdrant binary is required; run "
        "`vaultspec-rag server qdrant install`"
    )
    binary, _manifest = host_qdrant

    # Pad the storage dir well past the plain-path failure threshold
    # (~105 chars; plain paths were measured failing at 140).
    pad = "x" * max(1, 150 - len(str(tmp_path)) - len("storage") - 2)
    storage = tmp_path / pad / "storage"
    assert len(str(storage)) >= 140

    supervisor = QdrantSupervisor(
        unpinned(binary),
        http_port=_get_ephemeral_qdrant_port(),
        storage_dir=storage,
        log_path=tmp_path / "qdrant.log",
    )
    supervisor.spawn()
    try:
        assert supervisor.wait_ready(timeout=60.0), "qdrant did not become ready"
        # The child is addressed by URL on an ephemeral port, so the key it
        # published reaches the client as the configured key.
        with managed_env(
            **{EnvVar.QDRANT_API_KEY.value: read_managed_api_key(storage)}
        ):
            client = open_server_client(supervisor.url, timeout=60)
        try:
            client.create_collection(
                collection_name="r0123456789ab_vault_docs",
                vectors_config={
                    store_schema.DENSE_VECTOR_NAME: models.VectorParams(
                        size=1024,
                        distance=models.Distance(store_schema.DENSE_DISTANCE),
                    )
                },
                sparse_vectors_config={
                    store_schema.SPARSE_VECTOR_NAME: models.SparseVectorParams()
                },
            )
            assert client.collection_exists("r0123456789ab_vault_docs")
        finally:
            client.close()
    finally:
        supervisor.stop()
