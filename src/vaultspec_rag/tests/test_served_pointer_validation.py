"""Root ownership and fail-closed cleanup of served code pointers."""

from __future__ import annotations

import json
from contextlib import closing
from typing import TYPE_CHECKING, Literal

import pytest

from .._source_types import PublicSourceType
from .._store_models import (
    CodeChunk,
    generation_code_collection,
    publish_generation_as_served,
    publish_served_code_collection,
    read_served_code_collection,
    read_served_pointer,
    resolve_served_code_collection,
    root_collection_prefix,
    served_code_pointer_path,
)
from ..api import clean
from ..config._types import EnvVar
from ..store_runtime import VaultStore
from .conftest import managed_env
from .integration._helpers import provisioned_qdrant_binary, serve_qdrant

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest import TempPathFactory

pytestmark = pytest.mark.unit


def _poison(root: Path, value: object) -> None:
    path = served_code_pointer_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.mark.parametrize("server_mode", [False, True])
@pytest.mark.parametrize("suffix", ["", "_g1", "_g" + "a" * 16, "_gÅ\uff19"])
def test_owned_pointer_resolves_without_changing_its_name(
    tmp_path: Path, server_mode: bool, suffix: str
) -> None:
    derived = (
        root_collection_prefix(tmp_path) if server_mode else ""
    ) + "codebase_docs"
    collection = derived + suffix
    publish_served_code_collection(tmp_path, collection)
    pointer = read_served_pointer(tmp_path, derived)
    assert pointer.verifiable is True
    assert pointer.collection == collection
    assert resolve_served_code_collection(tmp_path, derived) == collection


@pytest.mark.parametrize(
    "suffix",
    [
        "_g",
        "_g" + "a" * 17,
        "_gfirst_gsecond",
        "_gabc-extra",
        "_gabc/",
        "_gabc\n",
        " ",
        "_extra_gabc",
    ],
)
def test_unsupported_generation_pointer_is_unverifiable(
    tmp_path: Path, suffix: str
) -> None:
    """A pointer must match the writer's bounded, single-suffix grammar.

    Mutation proof: accepting any suffix failed all eight verifiability
    assertions; restoring the matcher passed.
    """
    derived = root_collection_prefix(tmp_path) + "codebase_docs"
    _poison(tmp_path, {"collection": derived + suffix})
    pointer = read_served_pointer(tmp_path, derived)
    assert pointer.verifiable is False
    assert pointer.collection is None
    assert resolve_served_code_collection(tmp_path, derived) == derived


@pytest.mark.parametrize(
    "value",
    [None, [], "name", {}, {"collection": None}, {"collection": 1}, {"collection": ""}],
)
def test_malformed_pointer_is_unverifiable(tmp_path: Path, value: object) -> None:
    """Only file absence proves that no served pointer has been published.

    Mutation proof: marking rejected shapes verifiable failed all seven
    verifiability assertions; restoring the rejection branches passed.
    """
    _poison(tmp_path, value)
    pointer = read_served_pointer(tmp_path)
    assert pointer.verifiable is False
    assert pointer.collection is None


def test_foreign_pointer_cannot_resolve_or_become_a_donor(tmp_path: Path) -> None:
    """A pointer must not turn foreign data into a root's served index.

    Mutation proof: replacing the ownership predicate with True failed the
    verifiability assertion; restoring the predicate passed.
    """
    from ..indexer._donor_candidates import CollectionKind, _served_donor_collection

    derived = root_collection_prefix(tmp_path) + "codebase_docs"
    foreign = root_collection_prefix(tmp_path / "foreign") + "codebase_docs_g1"
    _poison(tmp_path, {"collection": foreign})
    pointer = read_served_pointer(tmp_path, derived)
    assert pointer.verifiable is False
    assert pointer.collection is None
    assert read_served_code_collection(tmp_path) is None
    assert resolve_served_code_collection(tmp_path, derived) == derived
    assert _served_donor_collection(str(tmp_path), CollectionKind.CODE, derived) is None


@pytest.mark.parametrize(
    "collection_kind", ["vault_docs", "document_docs", "codebase_docs"]
)
def test_shared_backend_rejects_wrong_kind_and_bare_names(
    tmp_path: Path, collection_kind: str
) -> None:
    """Mutation proof: bypassing ownership failed all three rejection assertions;
    restoring ownership passed.
    """
    derived = root_collection_prefix(tmp_path) + "codebase_docs"
    _poison(tmp_path, {"collection": collection_kind})
    assert read_served_pointer(tmp_path, derived).verifiable is False
    assert resolve_served_code_collection(tmp_path, derived) == derived


def test_invalid_publication_leaves_pointer_and_breadth_untouched(
    tmp_path: Path,
) -> None:
    """An invalid publication cannot replace the pointer or record breadth.

    Mutation proof: bypassing root ownership failed with DID NOT RAISE
    ValueError; removing preflight also failed the unchanged-breadth assertion.
    Restoring both guards passed.
    """
    served = "codebase_docs_g1"
    publish_served_code_collection(tmp_path, served)
    foreign = root_collection_prefix(tmp_path / "foreign") + "codebase_docs_g2"
    recorded: list[bool] = []
    with pytest.raises(ValueError, match="root-owned code collection"):
        publish_served_code_collection(tmp_path, foreign)
    with pytest.raises(ValueError, match="root-owned code collection"):
        publish_generation_as_served(
            tmp_path, collection=foreign, record_breadth=lambda: recorded.append(True)
        )
    assert recorded == []
    assert read_served_code_collection(tmp_path) == served


@pytest.mark.parametrize("server_mode", [False, True])
def test_default_reader_rejects_a_pointer_from_the_other_backend(
    tmp_path: Path, server_mode: bool
) -> None:
    """Mutation proof: bypassing ownership failed both verifiability assertions;
    restoring ownership passed.
    """
    foreign_backend = "codebase_docs"
    if not server_mode:
        foreign_backend = root_collection_prefix(tmp_path) + foreign_backend
    url = "http://127.0.0.1:1" if server_mode else ""
    with managed_env(**{EnvVar.QDRANT_URL.value: url}):
        _poison(tmp_path, {"collection": foreign_backend})
        assert read_served_pointer(tmp_path).verifiable is False
        assert read_served_code_collection(tmp_path) is None


def test_unverifiable_pointer_withholds_archive_and_reclamation(tmp_path: Path) -> None:
    """Mutation proof: bypassing ownership reported a root with an invalid pointer;
    restoring ownership passed.
    """
    from ..generation_survey import survey_generations
    from ..storage_archive import _active_publication_collections
    from .test_generation_survey import _publish_code_proof

    _publish_code_proof(tmp_path)
    prefix = root_collection_prefix(tmp_path)
    derived = prefix + "codebase_docs"
    _poison(tmp_path, {"collection": "vault_docs"})
    assert survey_generations({str(tmp_path): derived}, [derived + "_gold"]) == ()
    with pytest.raises(RuntimeError, match="verifiable served pointer"):
        _active_publication_collections(tmp_path, prefix, [derived])


def test_default_drop_refuses_a_pointer_poisoned_after_store_open(
    tmp_path: Path,
) -> None:
    """A cached read target cannot authorize deletion after pointer corruption.

    Mutation proof: removing the fresh pointer gate failed with DID NOT RAISE
    RuntimeError; restoring the gate passed.
    """
    with managed_env(**{EnvVar.QDRANT_URL.value: ""}), VaultStore(tmp_path) as store:
        store.ensure_code_table()
        _poison(tmp_path, {"collection": "vault_docs"})
        with pytest.raises(RuntimeError, match="verifiable served pointer"):
            store.drop_code_table()
        assert store.code_collection_exists()


def test_explicit_and_cached_foreign_targets_cannot_reach_code_operations(
    tmp_path: Path,
) -> None:
    """Explicit and cached targets must remain in the root's code namespace.

    Mutation proof: removing the per-call matcher failed with DID NOT RAISE
    ValueError; restoring the matcher passed.
    """
    foreign = root_collection_prefix(tmp_path / "foreign") + "codebase_docs"
    with managed_env(**{EnvVar.QDRANT_URL.value: ""}), VaultStore(tmp_path) as store:
        for target in (foreign, "vault_docs", "codebase_docs_g", ""):
            with pytest.raises(ValueError, match="root-owned code collection"):
                store.count_code(target)
            with pytest.raises(ValueError, match="root-owned code collection"):
                store.upsert_code_chunks([], write_policy=None, collection=target)
            with pytest.raises(ValueError, match="root-owned code collection"):
                store.delete_code_chunks([], collection=target)
            with pytest.raises(ValueError, match="root-owned code collection"):
                store.drop_code_table(target)
        vars(store)["CODE_TABLE_NAME"] = foreign
        with pytest.raises(ValueError, match="root-owned code collection"):
            store.count_code()


@pytest.mark.parametrize("clean_type", ["code", "all"])
def test_clean_refuses_before_changing_publication_state(
    tmp_path: Path, clean_type: Literal["code", "all"]
) -> None:
    """An invalid pointer must be refused before any selected domain is mutated.

    Mutation proof: removing preflight failed both cleanup variants with
    DID NOT RAISE RuntimeError; restoring preflight passed.
    """
    from .._publication_state import acquire_publication_snapshot
    from ..registry import get_registry
    from ._state_fixtures import reset_registry
    from .test_api_clean_admission import _publish_empty_vault_proof

    with managed_env(**{EnvVar.QDRANT_URL.value: ""}):
        reset_registry()
        try:
            _publish_empty_vault_proof(tmp_path)
            snapshot = acquire_publication_snapshot(tmp_path, PublicSourceType.VAULT)
            with get_registry().lease_store(tmp_path) as store:
                store.ensure_code_table()
            _poison(tmp_path, {"collection": "vault_docs"})
            with pytest.raises(RuntimeError, match="verifiable served pointer"):
                clean(tmp_path, clean_type=clean_type, registry=get_registry())
            snapshot.validate()
            with get_registry().lease_store(tmp_path) as store:
                assert store.code_collection_exists()
        finally:
            reset_registry()


def test_reclamation_only_reports_exact_owned_generation_names(tmp_path: Path) -> None:
    """Unknown suffix forms cannot enter the automatic deletion candidate set.

    Mutation proof: using a prefix-only match added three unsupported names
    to the unreferenced tuple; restoring the exact matcher passed.
    """
    from ..generation_survey import survey_generations
    from .test_generation_survey import _publish_code_proof

    _publish_code_proof(tmp_path)
    derived = root_collection_prefix(tmp_path) + "codebase_docs"
    served = derived + "_gserved"
    publish_served_code_collection(tmp_path, served)
    names = [
        served,
        derived + "_gold",
        derived + "_gfirst_gsecond",
        derived + "_extra_gabc",
        derived + "_g" + "a" * 17,
    ]
    reports = survey_generations({str(tmp_path): derived}, names)
    assert reports[0].unreferenced == (derived + "_gold",)


@pytest.fixture(scope="module")
def shared_qdrant_url(tmp_path_factory: TempPathFactory) -> Iterator[str]:
    binary = provisioned_qdrant_binary()
    with closing(
        serve_qdrant(binary, tmp_path_factory.mktemp("pointer-qdrant"))
    ) as servers:
        yield next(servers).url


@pytest.mark.parametrize("clean_type", ["code", "all"])
def test_poisoned_shared_pointer_cannot_read_write_delete_or_clean_foreign_data(
    tmp_path: Path, shared_qdrant_url: str, clean_type: Literal["code", "all"]
) -> None:
    """A poisoned pointer cannot redirect operations to another root.

    Mutation proof: bypassing ownership failed the served/derived namespace
    assertion for both cleanup variants; restoring ownership passed.
    """
    from .._publication_state import acquire_publication_snapshot
    from ..registry import get_registry
    from ._state_fixtures import reset_registry
    from .test_api_clean_admission import _publish_empty_vault_proof

    owner = tmp_path / "owner"
    victim = tmp_path / "victim"
    victim_chunk = CodeChunk(
        "shared-id", "file.py", "python", "victim", 1, 1, vector=[1.0] * 1024
    )
    owner_chunk = CodeChunk(
        "shared-id", "file.py", "python", "owner", 1, 1, vector=[1.0] * 1024
    )
    with managed_env(**{EnvVar.QDRANT_URL.value: shared_qdrant_url}):
        reset_registry()
        try:
            _publish_empty_vault_proof(owner)
            proof = acquire_publication_snapshot(owner, PublicSourceType.VAULT)
            with VaultStore(victim) as victim_store:
                victim_store.upsert_code_chunks([victim_chunk], write_policy=None)
                _poison(owner, {"collection": victim_store.CODE_TABLE_NAME})
                with VaultStore(owner) as owner_store:
                    assert (
                        owner_store.CODE_TABLE_NAME
                        == owner_store.DERIVED_CODE_TABLE_NAME
                    )
                    assert owner_store.count_code() == 0, (
                        "foreign data leaked into the owner"
                    )
                    owner_store.upsert_code_chunks([owner_chunk], write_policy=None)
                    assert owner_store.count_code() == 1
                    owner_store.delete_code_chunks([owner_chunk.id])
                    assert owner_store.count_code() == 0
                with pytest.raises(RuntimeError, match="verifiable served pointer"):
                    clean(owner, clean_type=clean_type, registry=get_registry())
                proof.validate()
                assert victim_store.count_code() == 1
                rows, _ = victim_store.scroll_code_content()
                assert [row["payload"]["content"] for row in rows] == ["victim"]
        finally:
            reset_registry()


@pytest.mark.parametrize("published", [False, True])
def test_clean_keeps_valid_base_and_generation_workflows(
    tmp_path: Path, shared_qdrant_url: str, published: bool
) -> None:
    from ..registry import get_registry
    from ._state_fixtures import reset_registry

    with managed_env(**{EnvVar.QDRANT_URL.value: shared_qdrant_url}):
        reset_registry()
        try:
            with VaultStore(tmp_path) as store:
                target = store.DERIVED_CODE_TABLE_NAME
                if published:
                    target = generation_code_collection(target, "a" * 32)
                    publish_served_code_collection(tmp_path, target)
                chunk = CodeChunk(
                    "owned", "file.py", "python", "owned", 1, 1, vector=[1.0] * 1024
                )
                store.upsert_code_chunks([chunk], collection=target, write_policy=None)
            assert clean(tmp_path, clean_type="code", registry=get_registry()) == [
                "code"
            ]
            with get_registry().lease_store(tmp_path) as cleaned:
                assert target == cleaned.CODE_TABLE_NAME
                assert cleaned.code_collection_exists()
                assert cleaned.count_code() == 0
        finally:
            reset_registry()


@pytest.mark.parametrize("to_server", [False, True])
def test_backend_migration_publishes_the_verified_destination(
    tmp_path: Path, shared_qdrant_url: str, to_server: bool
) -> None:
    """A backend switch must serve and clean the verified destination.

    Mutation proof: removing pointer publication failed verifiability in both
    directions; restoring publication passed.
    """
    from typer.testing import CliRunner

    from ..cli import app
    from ..registry import get_registry
    from ._state_fixtures import reset_registry

    source_url = "" if to_server else shared_qdrant_url
    target_url = shared_qdrant_url if to_server else ""
    target_backend = "server" if to_server else "local"
    with managed_env(**{EnvVar.QDRANT_URL.value: source_url}):
        derived = (
            root_collection_prefix(tmp_path) if source_url else ""
        ) + "codebase_docs"
        source = generation_code_collection(derived, "b" * 32)
        publish_served_code_collection(tmp_path, source)
        with VaultStore(tmp_path) as store:
            chunk = CodeChunk(
                "migrated", "file.py", "python", "migrated", 1, 1, vector=[1.0] * 1024
            )
            store.upsert_code_chunks([chunk], write_policy=None)
    with managed_env(**{EnvVar.QDRANT_URL.value: shared_qdrant_url}):
        result = CliRunner().invoke(
            app,
            [
                "server",
                "storage",
                "migrate",
                str(tmp_path),
                "--to",
                target_backend,
                "--yes",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        outcomes = json.loads(result.stdout)["data"]["results"]
        assert any(
            item["source"] == source and item["status"] == "migrated"
            for item in outcomes
        )
    with managed_env(**{EnvVar.QDRANT_URL.value: target_url}):
        reset_registry()
        try:
            with VaultStore(tmp_path) as migrated:
                assert migrated.DERIVED_CODE_TABLE_NAME == migrated.CODE_TABLE_NAME
                assert read_served_pointer(tmp_path).verifiable is True
                assert migrated.count_code() == 1
            assert clean(tmp_path, clean_type="code", registry=get_registry()) == [
                "code"
            ]
        finally:
            reset_registry()


@pytest.mark.parametrize("preview", [False, True])
def test_uncopied_migration_cannot_move_the_served_pointer(
    tmp_path: Path, preview: bool
) -> None:
    """Previews and skipped targets cannot authorize a pointer handoff.

    Mutation proof: permitting preview and skipped outcomes changed the
    selected collection in both cases; restoring both gates passed.
    """
    from qdrant_client import QdrantClient, models

    from ..storage_migration import migrate_collections

    source = "codebase_docs_gsource"
    target = root_collection_prefix(tmp_path) + "codebase_docs"
    with managed_env(**{EnvVar.QDRANT_URL.value: ""}):
        publish_served_code_collection(tmp_path, source)
        with (
            closing(QdrantClient(":memory:")) as src,
            closing(QdrantClient(":memory:")) as dst,
        ):
            vectors = models.VectorParams(size=2, distance=models.Distance.COSINE)
            src.create_collection(source, vectors_config=vectors)
            if not preview:
                dst.create_collection(target, vectors_config=vectors)
            outcomes = migrate_collections(
                src, dst, {source: target}, root_dir=tmp_path, dry_run=preview
            )
            assert outcomes[0].status == ("would_migrate" if preview else "skipped")
            assert read_served_code_collection(tmp_path) == source


def test_migration_reports_failed_pointer_publication(tmp_path: Path) -> None:
    """Mutation proof: reporting publication failure as migrated failed the status
    assertion; restoring failure reporting passed.
    """
    from qdrant_client import QdrantClient, models

    from ..storage_migration import migrate_collections

    source = "codebase_docs_gsource"
    target = root_collection_prefix(tmp_path) + "codebase_docs"
    served_code_pointer_path(tmp_path).mkdir(parents=True)
    with (
        closing(QdrantClient(":memory:")) as src,
        closing(QdrantClient(":memory:")) as dst,
    ):
        src.create_collection(
            source,
            vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE),
        )
        outcomes = migrate_collections(
            src, dst, {source: target}, root_dir=tmp_path, dry_run=False
        )
        assert outcomes[0].status == "failed"
        assert outcomes[0].reason is not None
        assert outcomes[0].reason.startswith("served_pointer_failed:")
