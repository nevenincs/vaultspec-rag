"""Root ownership and fail-closed cleanup of served code pointers."""

from __future__ import annotations

import json
from contextlib import closing
from typing import TYPE_CHECKING, Literal

import pytest

from .._source_types import PublicSourceType
from .._store_models import (
    CodeChunk,
    read_served_pointer,
    resolve_served_code_collection,
    root_collection_prefix,
    served_code_pointer_path,
)
from ..api import clean
from ..config._types import EnvVar
from ..indexer._donor_candidates import CollectionKind, _served_donor_collection
from ..store_runtime import VaultStore
from ._historical_code_layout import historical_generation, write_historical_pointer
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
    write_historical_pointer(tmp_path, collection)
    pointer = read_served_pointer(tmp_path, derived)
    assert pointer.verifiable is True
    assert pointer.collection == collection
    assert resolve_served_code_collection(tmp_path, derived) == collection
    assert (
        _served_donor_collection(str(tmp_path), CollectionKind.CODE, derived)
        == collection
    )


def test_a_root_without_a_pointer_serves_and_donates_its_derived_name(
    tmp_path: Path,
) -> None:
    """The canonical layout writes no pointer, and its code is still a donor.

    Mutation: returning ``None`` for an absent pointer in the donor lookup
    failed the donor assertion; restoring the derived-name fallback passed.
    """
    derived = root_collection_prefix(tmp_path) + "codebase_docs"
    assert read_served_pointer(tmp_path, derived) == (None, True)
    assert resolve_served_code_collection(tmp_path, derived) == derived
    assert (
        _served_donor_collection(str(tmp_path), CollectionKind.CODE, derived) == derived
    )


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
    derived = root_collection_prefix(tmp_path) + "codebase_docs"
    foreign = root_collection_prefix(tmp_path / "foreign") + "codebase_docs_g1"
    _poison(tmp_path, {"collection": foreign})
    pointer = read_served_pointer(tmp_path, derived)
    assert pointer.verifiable is False
    assert pointer.collection is None
    assert resolve_served_code_collection(tmp_path, derived) == derived
    assert _served_donor_collection(str(tmp_path), CollectionKind.CODE, derived) is None


def test_a_code_donor_without_a_root_is_ineligible() -> None:
    """An unresolvable donor must not invent publication authority."""
    assert (
        _served_donor_collection(None, CollectionKind.CODE, "rabc_codebase_docs")
        is None
    )


def test_migrate_reads_the_historical_served_collection(tmp_path: Path) -> None:
    """Migration must copy what a historical root serves, or it copies nothing.

    Keying the source map on the derived name copies a superseded generation,
    or - when the base never existed - silently migrates no code at all while
    reporting success. Other kinds keep their derived names.

    Proven able to fail: returning ``derived`` unconditionally from the
    ``_source`` helper restores the derived key and fails the source-name
    assertion below.
    """
    from ..cli._service_storage import _migrate_name_map
    from ..store_schema import CODE_COLLECTION, VAULT_COLLECTION

    served = historical_generation(CODE_COLLECTION, "served")
    write_historical_pointer(tmp_path, served)
    name_map = _migrate_name_map(str(tmp_path), to_server=True)

    assert served in name_map
    assert CODE_COLLECTION not in name_map
    # The target stays the derived base, which a root without a pointer
    # serves, so no generation history crosses the backend switch.
    assert name_map[served] == root_collection_prefix(tmp_path) + CODE_COLLECTION
    assert VAULT_COLLECTION in name_map


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
        assert read_served_pointer(tmp_path) == (None, False)


def test_unverifiable_pointer_withholds_archive(tmp_path: Path) -> None:
    """Mutation proof: bypassing ownership archived a root with an invalid pointer;
    restoring ownership passed.
    """
    from ..storage_archive import _active_publication_collections

    prefix = root_collection_prefix(tmp_path)
    derived = prefix + "codebase_docs"
    _poison(tmp_path, {"collection": "vault_docs"})
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
            store.discard_source_storage(PublicSourceType.CODE)
        assert store.code_collection_exists()


@pytest.mark.parametrize(
    "target", ["foreign", "vault_docs", "codebase_docs_g", "codebase_docs_extra", ""]
)
def test_a_cached_foreign_target_cannot_reach_code_operations(
    tmp_path: Path, target: str
) -> None:
    """A code name outside the root's code namespace never reaches storage.

    Mutation proof: removing the matcher in the store's code-collection
    accessor failed with DID NOT RAISE ValueError; restoring it passed.
    """
    if target == "foreign":
        target = root_collection_prefix(tmp_path / "foreign") + "codebase_docs"
    with managed_env(**{EnvVar.QDRANT_URL.value: ""}), VaultStore(tmp_path) as store:
        vars(store)["CODE_TABLE_NAME"] = target
        with pytest.raises(ValueError, match="root-owned code collection"):
            store.count_code()
        with pytest.raises(ValueError, match="root-owned code collection"):
            store.upsert_code_chunks([], write_policy=None)
        with pytest.raises(ValueError, match="root-owned code collection"):
            store.delete_publication_points(PublicSourceType.CODE, [])


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
    from ._publication_assertions import publish_empty_vault_proof
    from ._state_fixtures import reset_registry

    with managed_env(**{EnvVar.QDRANT_URL.value: ""}):
        reset_registry()
        try:
            publish_empty_vault_proof(tmp_path)
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
    from ._publication_assertions import publish_empty_vault_proof
    from ._state_fixtures import reset_registry

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
            publish_empty_vault_proof(owner)
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
                    owner_store.delete_publication_points(
                        PublicSourceType.CODE, [owner_chunk.id]
                    )
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
            derived = root_collection_prefix(tmp_path) + "codebase_docs"
            target = derived
            if published:
                target = historical_generation(derived, "a" * 16)
                write_historical_pointer(tmp_path, target)
            with VaultStore(tmp_path) as store:
                assert target == store.CODE_TABLE_NAME
                chunk = CodeChunk(
                    "owned", "file.py", "python", "owned", 1, 1, vector=[1.0] * 1024
                )
                store.upsert_code_chunks([chunk], write_policy=None)
            assert clean(tmp_path, clean_type="code", registry=get_registry()) == [
                "code"
            ]
            with get_registry().lease_store(tmp_path) as cleaned:
                # A clean discards every owned code collection, the served
                # generation included, and recreates only the derived one.
                assert derived == cleaned.DERIVED_CODE_TABLE_NAME
                assert derived == cleaned.CODE_TABLE_NAME
                assert cleaned.owned_code_collections() == (derived,)
                assert cleaned.code_collection_exists()
                assert cleaned.count_code() == 0
        finally:
            reset_registry()


def test_a_code_reset_leaves_another_roots_historical_layout_intact(
    tmp_path: Path, shared_qdrant_url: str
) -> None:
    """One root's explicit code reset discards its own generations only.

    Both roots share one server, serve a historical generation and hold a
    superseded one. Resetting the first leaves the second's collections,
    points and pointer exactly as they were.

    Mutation: matching owned code collections on the bare ``codebase_docs_g``
    suffix without the root prefix discarded the sibling's generations and
    failed the sibling survivor assertion; restoring the root-derived name
    passed.
    """
    from ..registry import get_registry
    from ._historical_code_layout import (
        create_historical_generation,
        write_historical_code_points,
    )
    from ._state_fixtures import reset_registry

    reset_root, sibling_root = tmp_path / "reset", tmp_path / "sibling"
    layouts: dict[Path, tuple[str, str]] = {}
    with managed_env(**{EnvVar.QDRANT_URL.value: shared_qdrant_url}):
        reset_registry()
        try:
            for root in (reset_root, sibling_root):
                derived = root_collection_prefix(root) + "codebase_docs"
                served = historical_generation(derived, "served")
                write_historical_pointer(root, served)
                with VaultStore(root) as store:
                    chunk = CodeChunk(
                        "historical", "a.py", "python", "old", 1, 1, vector=[1.0] * 1024
                    )
                    store.upsert_code_chunks([chunk], write_policy=None)
                    older = create_historical_generation(store, "older")
                    write_historical_code_points(store, older, [chunk])
                layouts[root] = (served, older)

            assert clean(reset_root, clean_type="code", registry=get_registry()) == [
                "code"
            ]

            with VaultStore(sibling_root) as sibling:
                assert layouts[sibling_root][0] == sibling.CODE_TABLE_NAME
                for name in layouts[sibling_root]:
                    assert sibling.client.collection_exists(name), name
                    assert sibling.client.count(name, exact=True).count == 1, name
            assert (
                read_served_pointer(sibling_root).collection
                == (layouts[sibling_root][0])
            )
            with get_registry().lease_store(reset_root) as cleaned:
                assert cleaned.owned_code_collections() == (
                    cleaned.DERIVED_CODE_TABLE_NAME,
                )
                for name in layouts[reset_root]:
                    assert not cleaned.client.collection_exists(name), name
            assert read_served_pointer(reset_root) == (None, True)
        finally:
            reset_registry()


@pytest.mark.parametrize("to_server", [False, True])
def test_backend_migration_serves_the_verified_destination(
    tmp_path: Path, shared_qdrant_url: str, to_server: bool
) -> None:
    """A backend switch must serve and clean the verified destination.

    Mutation proof: removing pointer retirement failed the retired-pointer
    assertion in both directions; restoring retirement passed.
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
        source = historical_generation(derived, "b" * 16)
        write_historical_pointer(tmp_path, source)
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
                assert read_served_pointer(tmp_path) == (None, True)
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
        write_historical_pointer(tmp_path, source)
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
            assert read_served_pointer(tmp_path).collection == source


def test_migration_reports_failed_pointer_retirement(tmp_path: Path) -> None:
    """Mutation proof: reporting retirement failure as migrated failed the status
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


def _seed_code_collection(store: VaultStore, name: str, content: str) -> None:
    """Create *name* beside the store's code collection and give it one point."""
    from ._historical_code_layout import write_historical_code_points

    store.ensure_code_table()
    params = store.client.get_collection(store.DERIVED_CODE_TABLE_NAME).config.params
    store.client.create_collection(
        name,
        vectors_config=params.vectors,
        sparse_vectors_config=params.sparse_vectors,
    )
    chunk = CodeChunk(content, "a.py", "python", content, 1, 1, vector=[1.0] * 1024)
    write_historical_code_points(store, name, [chunk])


@pytest.mark.parametrize("reset_backend", ["server", "local"])
def test_a_code_reset_retires_a_pointer_naming_the_other_backends_collection(
    tmp_path: Path,
    shared_qdrant_url: str,
    reset_backend: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A migration-era pointer to the other backend never blocks a reset.

    The root first served a historical code generation under one backend and
    left the pointer naming it. Under the other backend that name is not this
    backend's to judge, so an explicit code reset there retires the pointer,
    logs it, and empties its own code collection. The named collection is
    never touched: it survives in the backend that owns it, and a same-named
    collection in the resetting backend survives too.

    Mutation: making ``other_backend_code_pointer`` return ``None`` refused
    the reset with ``verifiable served pointer`` in both directions; adding a
    drop of the stale name to the reset dropped the same-named collection and
    failed the ``same-named survivor`` assertion. Restoring each passed.
    """
    from ..registry import get_registry
    from ._state_fixtures import reset_registry

    reset_url = shared_qdrant_url if reset_backend == "server" else ""
    other_url = "" if reset_backend == "server" else shared_qdrant_url
    with managed_env(**{EnvVar.QDRANT_URL.value: other_url}):
        reset_registry()
        with VaultStore(tmp_path) as other_store:
            stale = historical_generation(other_store.DERIVED_CODE_TABLE_NAME, "old")
            write_historical_pointer(tmp_path, stale)
            _seed_code_collection(other_store, stale, "other-backend")
    try:
        with managed_env(**{EnvVar.QDRANT_URL.value: reset_url}):
            reset_registry()
            assert read_served_pointer(tmp_path) == (None, False)
            with VaultStore(tmp_path) as store:
                _seed_code_collection(store, stale, "same-named")
                old = CodeChunk(
                    "old", "b.py", "python", "old", 1, 1, vector=[1.0] * 1024
                )
                store.upsert_code_chunks([old], write_policy=None)
            with caplog.at_level("WARNING", logger="vaultspec_rag.indexer"):
                assert clean(tmp_path, clean_type="code", registry=get_registry()) == [
                    "code"
                ]
            assert not served_code_pointer_path(tmp_path).exists()
            assert any(
                stale in record.getMessage() and "other backend" in record.getMessage()
                for record in caplog.records
            ), caplog.text
            with get_registry().lease_store(tmp_path) as cleaned:
                assert cleaned.CODE_TABLE_NAME == cleaned.DERIVED_CODE_TABLE_NAME
                assert cleaned.count_code() == 0
                assert cleaned.client.collection_exists(stale), "same-named survivor"
                assert cleaned.client.count(stale, exact=True).count == 1
            reset_registry()
        with (
            managed_env(**{EnvVar.QDRANT_URL.value: other_url}),
            VaultStore(tmp_path) as owner,
        ):
            assert owner.client.collection_exists(stale), "other-backend survivor"
            assert owner.client.count(stale, exact=True).count == 1
    finally:
        reset_registry()


@pytest.mark.parametrize("token", [None, "old"])
def test_archive_takes_the_derived_name_over_an_other_backend_pointer(
    tmp_path: Path, token: str | None
) -> None:
    """A pointer to the root's local code never withholds its server archive.

    The archive reads the pointer and never changes it: only an explicit
    reset retires it.

    Mutation: dropping the other-backend branch from
    ``established_served_code_collection`` refused both cases with
    ``ServedPointerUnverifiableError``; restoring it passed.
    """
    from ..storage_archive import _active_publication_collections

    prefix = root_collection_prefix(tmp_path)
    derived = prefix + "codebase_docs"
    stale = (
        "codebase_docs"
        if token is None
        else historical_generation("codebase_docs", token)
    )
    write_historical_pointer(tmp_path, stale)
    before = served_code_pointer_path(tmp_path).read_bytes()

    active = _active_publication_collections(tmp_path, prefix, [derived, stale])

    assert active[PublicSourceType.CODE] == derived
    assert served_code_pointer_path(tmp_path).read_bytes() == before


@pytest.mark.parametrize("server_mode", [False, True])
def test_a_donor_with_an_other_backend_pointer_donates_its_derived_name(
    tmp_path: Path, server_mode: bool
) -> None:
    """A donor's stale other-backend pointer leaves it eligible, untouched.

    Mutation: dropping the other-backend branch from
    ``established_served_code_collection`` made the donor ineligible in both
    backends and failed the donor assertion; restoring it passed.
    """
    prefixed = root_collection_prefix(tmp_path) + "codebase_docs"
    derived, other = (
        (prefixed, "codebase_docs") if server_mode else ("codebase_docs", prefixed)
    )
    write_historical_pointer(tmp_path, historical_generation(other, "old"))
    before = served_code_pointer_path(tmp_path).read_bytes()

    assert (
        _served_donor_collection(str(tmp_path), CollectionKind.CODE, derived) == derived
    )
    assert served_code_pointer_path(tmp_path).read_bytes() == before


def test_an_unverifiable_pointer_refuses_with_the_typed_kind(tmp_path: Path) -> None:
    """The refusal carries a stable kind and names the pointer it read.

    Mutation: raising a bare ``RuntimeError`` from
    ``established_served_code_collection`` escaped the typed ``pytest.raises``;
    restoring the typed error passed.
    """
    from .._job_errors import JobErrorKind
    from .._store_models import (
        ServedPointerUnverifiableError,
        established_served_code_collection,
    )

    derived = root_collection_prefix(tmp_path) + "codebase_docs"
    _poison(tmp_path, {"collection": "vault_docs"})
    with pytest.raises(ServedPointerUnverifiableError) as raised:
        established_served_code_collection(tmp_path, derived)
    assert raised.value.error_kind is JobErrorKind.SERVED_POINTER_UNVERIFIABLE
    assert str(served_code_pointer_path(tmp_path)) in raised.value.detail
