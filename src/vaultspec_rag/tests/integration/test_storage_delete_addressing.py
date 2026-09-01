"""``server storage delete --root`` against a real managed Qdrant server.

The verb resolves its own server address and opens its own client here, so
addressing, deletion and idempotency are answered by the running system rather
than by a client handed in from the test.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from qdrant_client import QdrantClient, models

from ...config._settings import reset_config
from ...config._types import EnvVar
from .._cli_helpers import app, runner
from ._helpers import provisioned_qdrant_binary, serve_qdrant

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path

    from _pytest.tmpdir import TempPathFactory

    from ...qdrant_runtime._supervise import QdrantSupervisor

pytestmark = [pytest.mark.integration]


@pytest.fixture(scope="module")
def real_qdrant_binary() -> Path:
    """Provision (or reuse) the pinned real Qdrant binary."""
    return provisioned_qdrant_binary()


@pytest.fixture(scope="module")
def qdrant_server(
    real_qdrant_binary: Path,
    tmp_path_factory: TempPathFactory,
) -> Iterator[QdrantSupervisor]:
    """One real qdrant server on ephemeral ports with temp storage."""
    yield from serve_qdrant(
        real_qdrant_binary, tmp_path_factory.mktemp("storage-adversarial")
    )


@pytest.fixture
def server_mode(qdrant_server: QdrantSupervisor) -> Iterator[QdrantSupervisor]:
    """Point the storage verbs at the running server via the URL knob."""
    import os as _os

    prev = _os.environ.get(EnvVar.QDRANT_URL.value)
    _os.environ[EnvVar.QDRANT_URL.value] = qdrant_server.url
    reset_config()
    try:
        yield qdrant_server
    finally:
        if prev is None:
            _os.environ.pop(EnvVar.QDRANT_URL.value, None)
        else:
            _os.environ[EnvVar.QDRANT_URL.value] = prev
        reset_config()


class TestDeleteRootAddressing:
    """``server storage delete --root``: resolution parity and idempotency.

    Every collection here lives on a real running Qdrant and the removal is
    the real ``delete_prefix``, reached through the verb's own client against
    the address it resolved for itself. What these assertions read is what
    actually survived on the server.

    This moved out of the unit suite to get there. Held as a unit test it had
    to hand the verb a local client, which meant the resolution and the
    connection - the two steps most likely to break - were the only parts not
    exercised.
    """

    @pytest.fixture
    def storage(
        self,
        server_mode: QdrantSupervisor,
        isolated_status_dir: Path,
    ) -> Generator[QdrantClient]:
        """Run the verb against a real managed server and a relocated manifest.

        Nothing is redirected. ``server_mode`` points the URL knob at a real
        Qdrant, so the verb resolves that address itself, opens its own client
        and reaches the same server this test inspects afterwards - which is
        what makes "what survived" an answer about the running system rather
        than about a client the test handed in.
        """
        del isolated_status_dir
        client = QdrantClient(url=server_mode.url)
        try:
            yield client
        finally:
            client.close()

    @staticmethod
    def _create(client: QdrantClient, *names: str) -> None:
        for name in names:
            client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=4, distance=models.Distance.COSINE
                ),
            )

    @staticmethod
    def _live(client: QdrantClient) -> set[str]:
        return {c.name for c in client.get_collections().collections}

    @staticmethod
    def _registered_root(tmp_path: Path, name: str) -> tuple[Path, str]:
        """Create a root, record it in the manifest, return it and its prefix."""
        from ..._store_models import root_collection_prefix
        from ...storage_manifest import record_root

        root = tmp_path / name
        root.mkdir()
        record_root(root, backend="server")
        return root, root_collection_prefix(root)

    def test_both_prefix_and_root_are_rejected(self) -> None:
        result = runner.invoke(
            app,
            ["server", "storage", "delete", "rdeadbeef0000_", "--root", ".", "-y"],
        )
        assert result.exit_code == 2

    def test_neither_prefix_nor_root_is_rejected_as_json_envelope(self) -> None:
        result = runner.invoke(app, ["server", "storage", "delete", "--json", "--yes"])
        assert result.exit_code == 2
        envelope = json.loads(result.output)
        assert envelope["ok"] is False
        assert envelope["error"] == "bad_request"

    def test_root_deletes_exactly_the_namespace_registration_derived(
        self, storage: QdrantClient, tmp_path: Path
    ) -> None:
        """``--root`` reaches the registered namespace and no neighbour's.

        Both roots are registered and both hold real collections, so a
        derivation that drifted from the one registration uses would either
        miss the target or take the bystander with it - and the store is
        asked afterwards which of the two is still there.

        Proven able to fail: replacing the verb's derivation with a fixed
        canonical prefix leaves the target collection standing, failing the
        assertion that it is gone. Restored, it passes.
        """
        root, prefix = self._registered_root(tmp_path, "target")
        _, bystander = self._registered_root(tmp_path, "bystander")
        self._create(storage, f"{prefix}vault_docs", f"{bystander}vault_docs")

        result = runner.invoke(
            app,
            ["server", "storage", "delete", "--root", str(root), "--yes", "--json"],
        )

        assert result.exit_code == 0, result.output
        live = self._live(storage)
        assert f"{prefix}vault_docs" not in live
        assert f"{bystander}vault_docs" in live
        envelope = json.loads(result.output)
        assert envelope["ok"] is True
        assert envelope["data"]["status"] == "removed"
        assert envelope["data"]["queried_root"]["prefix"] == prefix

    def test_a_torn_down_root_keeps_no_claim_over_deleted_collections(
        self, storage: QdrantClient, tmp_path: Path
    ) -> None:
        """A claim outliving its data makes every later run address a ghost.

        The served pointer and the published metadata are read ahead of any
        derivation, so a namespace deleted underneath them leaves the next run
        resolving to a collection the store does not hold - a 404 it can
        neither retry nor explain, repeating for as long as the files sit
        there, and surviving a restart because they are on disk.
        """
        from ..._index_breadth import index_meta_path
        from ..._source_types import PublicSourceType
        from ..._store_models import (
            publish_served_code_collection,
            served_code_pointer_path,
        )

        root, prefix = self._registered_root(tmp_path, "torn-down")
        generation = f"{prefix}codebase_docs_g{'a' * 16}"
        self._create(storage, f"{prefix}vault_docs", generation)
        pointer = served_code_pointer_path(root)
        pointer.parent.mkdir(parents=True, exist_ok=True)
        publish_served_code_collection(root, generation)
        code_meta = index_meta_path(root, PublicSourceType.CODE)
        code_meta.parent.mkdir(parents=True, exist_ok=True)
        code_meta.write_text("{}", encoding="utf-8")
        assert pointer.is_file()
        assert code_meta.is_file()

        result = runner.invoke(
            app,
            ["server", "storage", "delete", "--root", str(root), "--yes"],
        )

        assert result.exit_code == 0, result.output
        assert not any(name.startswith(prefix) for name in self._live(storage))
        # The exact assertion: nothing on disk still names what was deleted.
        assert not pointer.is_file(), "served pointer outlived its collection"
        assert not code_meta.is_file(), "published claim outlived its collection"

    def test_absent_namespace_is_an_idempotent_success(
        self, storage: QdrantClient, tmp_path: Path
    ) -> None:
        """A root the store never held tears down as a success, not a fault.

        The store is genuinely empty here, so ``no_such_namespace`` is the
        real gate's own finding rather than a stated one.

        Proven able to fail: dropping the remap of that finding leaves the
        raw ``skipped``/``no_such_namespace`` pair in the envelope, failing
        the ``already_absent`` assertion. Restored, it passes.
        """
        del storage
        root, _ = self._registered_root(tmp_path, "never-stored")

        result = runner.invoke(
            app,
            ["server", "storage", "delete", "--root", str(root), "--yes", "--json"],
        )

        assert result.exit_code == 0, result.output
        envelope = json.loads(result.output)
        assert envelope["ok"] is True
        assert envelope["data"]["status"] == "already_absent"
        assert envelope["data"]["reason"] is None

    def test_absent_namespace_exits_zero_in_human_mode_too(
        self, storage: QdrantClient, tmp_path: Path
    ) -> None:
        """The operator reading prose is told the same thing as the broker.

        Proven able to fail: under the same mutation as the sibling test
        the line reads "Skipped ...: no_such_namespace", failing the phrase
        assertion. Restored, it passes.
        """
        del storage
        root, _ = self._registered_root(tmp_path, "never-stored")
        result = runner.invoke(
            app, ["server", "storage", "delete", "--root", str(root), "--yes"]
        )
        assert result.exit_code == 0, result.output
        assert "already absent" in result.output

    def test_unattributable_namespace_survives_the_delete(
        self, storage: QdrantClient, tmp_path: Path
    ) -> None:
        """Data the manifest cannot vouch for is reported, never destroyed.

        The root is deliberately left out of the manifest while its
        collection really exists, which is the shape of a namespace written
        by something this installation does not know about. The load-bearing
        assertion is the survival, not the envelope: a refusal that still
        deleted would be the worst outcome and reads identically otherwise.

        Proven able to fail: dropping the manifest-attribution gate in
        ``delete_prefix`` removes the collection, failing the survival
        assertion. Restored, it passes.
        """
        from ..._store_models import root_collection_prefix

        root = tmp_path / "unattributable"
        root.mkdir()
        prefix = root_collection_prefix(root)
        self._create(storage, f"{prefix}vault_docs")

        result = runner.invoke(
            app,
            ["server", "storage", "delete", "--root", str(root), "--yes", "--json"],
        )

        assert result.exit_code == 0, result.output
        assert f"{prefix}vault_docs" in self._live(storage)
        envelope = json.loads(result.output)
        assert envelope["data"]["status"] == "skipped"
        assert envelope["data"]["reason"] == "unknown_namespace"

    def test_prefix_form_deletes_and_reports_no_queried_root(
        self, storage: QdrantClient, tmp_path: Path
    ) -> None:
        """Addressing by prefix removes the same namespace, minus the echo.

        ``queried_root`` answers "which namespace did my path resolve to",
        a question a caller that supplied the prefix never asked; emitting
        it anyway would let a consumer read a path it never gave.
        """
        _, prefix = self._registered_root(tmp_path, "by-prefix")
        self._create(storage, f"{prefix}vault_docs")

        result = runner.invoke(
            app, ["server", "storage", "delete", prefix, "--yes", "--json"]
        )

        assert result.exit_code == 0, result.output
        envelope = json.loads(result.output)
        assert envelope["data"]["status"] == "removed"
        assert "queried_root" not in envelope["data"]
        assert f"{prefix}vault_docs" not in self._live(storage)

    def test_prefix_deletion_retains_its_root_for_resident_eviction(
        self, storage: QdrantClient, tmp_path: Path
    ) -> None:
        """A prefix teardown keeps its attributed root after manifest removal."""
        from ...storage_manifest import load_manifest
        from ...storage_survey_ops import delete_prefix

        root, prefix = self._registered_root(tmp_path, "prefix-eviction")
        self._create(storage, f"{prefix}vault_docs")

        result = delete_prefix(storage, prefix, dry_run=False)

        assert result.status == "removed"
        assert prefix not in load_manifest()
        # The manifest lookup used to happen after its own removal, so prefix
        # deletion had no root to pass to resident-service eviction.
        assert result.root == str(root.resolve())
