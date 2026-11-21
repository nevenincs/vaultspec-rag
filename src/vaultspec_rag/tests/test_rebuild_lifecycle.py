"""Durable selected-source reset against real temporary local storage.

Every test opens a real embedded Qdrant store and a real run ledger under the
test's temporary root. Nothing here loads a model or touches a GPU. A crash is
reproduced by leaving exactly the durable state a process dying at that point
leaves behind, then reopening the store the way a restarted process does.
"""

from __future__ import annotations

import shutil
from contextlib import ExitStack
from typing import TYPE_CHECKING

import pytest

from .._source_types import PublicSourceType
from ..indexer._rebuild_lifecycle import (
    CONCRETE_SOURCES,
    ResetEpochFence,
    capture_reset_epoch,
    enter_rebuild_ingestion,
    reset_selected_sources,
)
from ..indexer._run_ledger_models import (
    SourceResetEpochError,
    SourceResetPhase,
    SourceResetState,
    index_run_ledger_path,
)
from ..indexer._run_ledger_runtime import RunLedger
from ._ledger_fixtures import continue_rebuild

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from .._store_models import VaultChunk
    from ..indexer._run_ledger_models import CommitUnit
    from ..indexer._vault_checkpoint import VaultRunCheckpoint
    from ..store_runtime import VaultStore

pytestmark = [pytest.mark.unit]


def _open(root: Path) -> VaultStore:
    from ..store_runtime import VaultStore

    return VaultStore(root, embedding_dim=2)


@pytest.fixture
def local_config() -> None:
    """Configure local storage with two-wide dense vectors and no sparse ones."""
    from ..config._settings import get_config

    get_config({"qdrant_url": None, "embedding_dimension": 2, "sparse_enabled": False})


@pytest.fixture
def store(tmp_path: Path, local_config: None) -> Generator[VaultStore]:
    """Open a real local store holding all three canonical collections."""
    del local_config
    with _open(tmp_path) as opened:
        opened.ensure_table()
        opened.ensure_code_table()
        opened.ensure_document_table()
        yield opened


def _collection(store: VaultStore, source: PublicSourceType) -> str:
    if source is PublicSourceType.VAULT:
        return store.TABLE_NAME
    if source is PublicSourceType.CODE:
        return store.CODE_TABLE_NAME
    return store.DOCUMENT_TABLE_NAME


def _seed(store: VaultStore, collection: str, point_id: int = 1) -> None:
    from qdrant_client import models

    from .. import store_schema

    store.client.upsert(
        collection,
        points=[
            models.PointStruct(
                id=point_id,
                vector={store_schema.DENSE_VECTOR_NAME: [1.0, 0.0]},
                payload={"content": f"old content {point_id}"},
            )
        ],
        wait=True,
    )


def _points(store: VaultStore, collection: str) -> int:
    return store.client.count(collection, exact=True).count


def _ledger(store: VaultStore) -> RunLedger:
    from .._store_writes import workspace_volume_path

    return RunLedger(
        index_run_ledger_path(workspace_volume_path(store.root_dir.resolve()))
    )


def _state(store: VaultStore, source: PublicSourceType) -> SourceResetState | None:
    return _ledger(store).source_reset_state(
        source, str(store.root_dir.resolve()), store.backend_identity
    )


def _fence(store: VaultStore, source: PublicSourceType) -> ResetEpochFence:
    return capture_reset_epoch(store.root_dir, source, store.backend_identity)


def _local_dir(store: VaultStore, collection: str) -> Path:
    from pathlib import Path

    return Path(store.db_path) / "collection" / collection


@pytest.mark.parametrize("source", CONCRETE_SOURCES)
def test_reset_empties_only_the_selected_source(
    store: VaultStore, source: PublicSourceType
) -> None:
    """The selected source ends empty and recreated; its siblings keep points.

    Mutation: resetting every concrete source regardless of selection failed
    the sibling count assertion; restoring the selection passed.
    """
    collections = {kind: _collection(store, kind) for kind in CONCRETE_SOURCES}
    for collection in collections.values():
        _seed(store, collection)

    (state,) = reset_selected_sources(store, source, generation_id="rebuild-1")

    assert state.complete
    assert state.epoch == 1
    assert store.client.collection_exists(collections[source])
    for kind, collection in collections.items():
        assert _points(store, collection) == int(kind is not source), kind


def test_reset_leaves_other_roots_and_sibling_ledger_partitions_intact(
    tmp_path: Path, local_config: None
) -> None:
    """A vault reset of one root keeps another root's points and proof.

    Its own document and code partitions record no reset either.
    """
    from .._publication_state import acquire_publication_snapshot
    from ..indexer._publication_proof import ProofMissingError
    from ._publication_assertions import publish_empty_vault_proof

    del local_config
    reset_root, other_root = tmp_path / "reset", tmp_path / "other"
    for root in (reset_root, other_root):
        publish_empty_vault_proof(root)
    with ExitStack() as stack:
        reset_store = stack.enter_context(_open(reset_root))
        other_store = stack.enter_context(_open(other_root))
        for opened in (reset_store, other_store):
            opened.ensure_table()
            _seed(opened, opened.TABLE_NAME)

        reset_selected_sources(reset_store, PublicSourceType.VAULT, generation_id="r1")

        assert _points(reset_store, reset_store.TABLE_NAME) == 0
        assert _points(other_store, other_store.TABLE_NAME) == 1
        assert _state(other_store, PublicSourceType.VAULT) is None
        for sibling in (PublicSourceType.CODE, PublicSourceType.DOCUMENT):
            assert _state(reset_store, sibling) is None
    acquire_publication_snapshot(other_root, PublicSourceType.VAULT)
    with pytest.raises(ProofMissingError):
        acquire_publication_snapshot(reset_root, PublicSourceType.VAULT)


def test_code_reset_discards_generation_collections_and_retires_the_pointer(
    store: VaultStore,
) -> None:
    """Every owned code collection is discarded and reads return to the base.

    Mutation: dropping only the served collection left the older generation
    in the owned set; restoring the full owned-set discard passed.
    """
    from .._store_models import served_code_pointer_path
    from ._historical_code_layout import (
        create_historical_generation,
        write_historical_pointer,
    )

    derived = store.DERIVED_CODE_TABLE_NAME
    older = create_historical_generation(store, "a" * 16)
    served = create_historical_generation(store, "b" * 16)
    for collection in (derived, older, served):
        _seed(store, collection)
    write_historical_pointer(store.root_dir, served)
    store.CODE_TABLE_NAME = served

    reset_selected_sources(store, PublicSourceType.CODE, generation_id="rebuild-1")

    assert store.owned_code_collections() == (derived,)
    assert not served_code_pointer_path(store.root_dir).exists()
    served_after = store.CODE_TABLE_NAME
    assert served_after == derived
    assert _points(store, derived) == 0


def test_only_a_code_reset_discards_historical_generations(
    store: VaultStore,
) -> None:
    """Vault and document resets leave the historical code layout serving.

    Mutation: discarding every source's owned collections on any reset
    dropped both generations during the vault reset and failed the first
    survivor assertion; restoring the per-source discard passed.
    """
    from .._store_models import read_served_pointer
    from ._historical_code_layout import (
        create_historical_generation,
        write_historical_pointer,
    )

    older = create_historical_generation(store, "old")
    served = create_historical_generation(store, "served")
    for collection in (older, served):
        _seed(store, collection)
    write_historical_pointer(store.root_dir, served)

    for sibling in (PublicSourceType.VAULT, PublicSourceType.DOCUMENT):
        reset_selected_sources(store, sibling, generation_id=f"{sibling.value}-1")
        for collection in (older, served):
            assert store.client.collection_exists(collection), (sibling, collection)
            assert _points(store, collection) == 1, (sibling, collection)
        assert read_served_pointer(store.root_dir).collection == served, sibling
        assert _state(store, PublicSourceType.CODE) is None, sibling

    reset_selected_sources(store, PublicSourceType.CODE, generation_id="code-1")

    for collection in (older, served):
        assert not store.client.collection_exists(collection), collection
    assert read_served_pointer(store.root_dir) == (None, True)


def test_code_reset_refuses_to_touch_names_it_does_not_own(store: VaultStore) -> None:
    """Unknown and foreign code-shaped names survive a code reset untouched.

    Mutation: widening ownership to any name starting with the derived name
    dropped ``codebase_docs_old`` and failed the survivor assertion;
    restoring the exact generation-suffix predicate passed. Accepting any
    ``_g`` token dropped ``codebase_docs_g-tmp`` and failed the same
    assertion; restoring the bounded alphanumeric token passed.
    """
    derived = store.DERIVED_CODE_TABLE_NAME
    foreign = (
        f"{derived}_old",
        f"{derived}_g-tmp",
        f"{derived}_g" + "a" * 17,
        f"{derived}_gfirst_gsecond",
        f"{derived}_extra_gabc",
        f"other_{derived}",
    )
    for name in foreign:
        store.client.create_collection(
            name,
            vectors_config=store.client.get_collection(derived).config.params.vectors,
        )
        _seed(store, name)

    reset_selected_sources(store, PublicSourceType.CODE, generation_id="rebuild-1")

    for name in foreign:
        assert store.client.collection_exists(name), name
        assert _points(store, name) == 1, name


def test_unverifiable_code_pointer_refuses_before_any_source_records_intent(
    store: VaultStore,
) -> None:
    """A combined reset with unestablished code ownership changes nothing.

    Mutation: moving the ownership preflight after the first source's reset
    let vault record intent and lose its point; restoring the preflight passed.
    """
    from .._store_models import served_code_pointer_path

    _seed(store, store.TABLE_NAME)
    served_code_pointer_path(store.root_dir).write_text("{not json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="verifiable served pointer"):
        reset_selected_sources(
            store, PublicSourceType.COMBINED, generation_id="rebuild-1"
        )

    assert _points(store, store.TABLE_NAME) == 1
    for source in CONCRETE_SOURCES:
        assert _state(store, source) is None


def test_reset_retires_only_the_selected_sources_publication(
    store: VaultStore,
) -> None:
    """A document reset keeps the vault proof; a vault reset retires it."""
    from .._publication_state import acquire_publication_snapshot
    from ..indexer._publication_proof import ProofMissingError
    from ._publication_assertions import publish_empty_vault_proof

    publish_empty_vault_proof(store.root_dir)

    reset_selected_sources(store, PublicSourceType.DOCUMENT, generation_id="r1")
    acquire_publication_snapshot(store.root_dir, PublicSourceType.VAULT)

    reset_selected_sources(store, PublicSourceType.VAULT, generation_id="r2")
    with pytest.raises(ProofMissingError):
        acquire_publication_snapshot(store.root_dir, PublicSourceType.VAULT)


def test_epoch_fence_rejects_work_that_began_before_a_reset(
    store: VaultStore,
) -> None:
    """Work captured before a reset is stale after it; siblings are not.

    The second reset reaches the same phase as the first, so only the epoch
    tells the fences apart.

    Mutation: comparing the captured phase instead of the epoch let the
    fence captured after the first completed reset validate after the second
    and failed the last ``pytest.raises``; restoring the epoch check passed.
    """
    before = _fence(store, PublicSourceType.CODE)
    sibling = _fence(store, PublicSourceType.VAULT)
    assert before.epoch == 0
    assert before.phase is None

    reset_selected_sources(store, PublicSourceType.CODE, generation_id="rebuild-1")

    with pytest.raises(SourceResetEpochError):
        before.validate()
    sibling.validate()
    after = _fence(store, PublicSourceType.CODE)
    assert after.epoch == 1
    assert after.phase is SourceResetPhase.COMPLETE
    after.validate()

    reset_selected_sources(store, PublicSourceType.CODE, generation_id="rebuild-2")

    with pytest.raises(SourceResetEpochError):
        after.validate()


def test_capturing_an_epoch_creates_no_ledger(tmp_path: Path) -> None:
    """A read on a never-indexed root leaves no durable state behind."""
    fence = capture_reset_epoch(tmp_path, PublicSourceType.VAULT, "local:test")

    assert fence.epoch == 0
    assert not fence.ledger_path.exists()
    fence.validate()


def test_rebuild_ingestion_rejects_a_writer_from_before_a_reset(
    store: VaultStore,
) -> None:
    """A rebuild planned before another reset may not write into its replacement.

    Mutation: deleting the entry's fence validation let the stale rebuild
    through and failed the ``pytest.raises``; restoring it passed.
    """
    stale = _fence(store, PublicSourceType.VAULT)
    reset_selected_sources(store, PublicSourceType.VAULT, generation_id="newer")
    _seed(store, store.TABLE_NAME, point_id=9)

    with pytest.raises(SourceResetEpochError, match="after this work began"):
        enter_rebuild_ingestion(
            store, PublicSourceType.VAULT, began_under=stale, generation_id="stale"
        )

    assert _points(store, store.TABLE_NAME) == 1
    enter_rebuild_ingestion(
        store,
        PublicSourceType.VAULT,
        began_under=_fence(store, PublicSourceType.VAULT),
        generation_id="newer",
    )
    assert _points(store, store.TABLE_NAME) == 1


def test_a_first_rebuild_discards_content_from_before_any_ledger(
    store: VaultStore,
) -> None:
    """A rebuild of a root that never recorded a reset still discards first."""
    _seed(store, store.TABLE_NAME)
    fence = _fence(store, PublicSourceType.VAULT)
    assert not fence.ledger_path.exists()

    state = enter_rebuild_ingestion(
        store, PublicSourceType.VAULT, began_under=fence, generation_id="first"
    )

    assert (state.epoch, state.generation_id, state.phase) == (
        1,
        "first",
        SourceResetPhase.COMPLETE,
    )
    assert _points(store, store.TABLE_NAME) == 0


def _crash_after_intent(store: VaultStore, source: PublicSourceType) -> None:
    _ledger(store).begin_source_reset(
        source, str(store.root_dir.resolve()), store.backend_identity, "crashed"
    )


def _crash_after_discard(store: VaultStore, source: PublicSourceType) -> None:
    ledger = _ledger(store)
    state = ledger.begin_source_reset(
        source, str(store.root_dir.resolve()), store.backend_identity, "crashed"
    )
    store.discard_source_storage(source)
    ledger.advance_source_reset(state, SourceResetPhase.DISCARDED)


def _crash_after_empty_creation(store: VaultStore, source: PublicSourceType) -> None:
    _crash_after_discard(store, source)
    store.recreate_empty_source(source)


@pytest.mark.parametrize(
    ("crash", "recorded_phase"),
    [
        (_crash_after_intent, SourceResetPhase.INTENT),
        (_crash_after_discard, SourceResetPhase.DISCARDED),
        (_crash_after_empty_creation, SourceResetPhase.DISCARDED),
    ],
    ids=["after-intent", "after-deletion", "after-empty-creation"],
)
@pytest.mark.parametrize("source", CONCRETE_SOURCES)
def test_rebuild_ingestion_finishes_a_reset_a_crash_interrupted(
    tmp_path: Path,
    local_config: None,
    source: PublicSourceType,
    crash: Callable[[VaultStore, PublicSourceType], None],
    recorded_phase: SourceResetPhase,
) -> None:
    """The crashed rebuild's next attempt finishes its own reset under its epoch.

    Old points are gone and the canonical collection exists and is empty
    before the rebuild writes anything; the epoch the crash left is kept, so
    a fence captured after the crash stays valid and the reset is not
    repeated as a new one.

    Mutation: returning a reset its own generation recorded without
    finishing it left the phase short of complete (and, after intent, the
    old point in place) and failed the phase assertion; restoring it passed.
    """
    del local_config
    with _open(tmp_path) as crashed:
        crashed.ensure_table()
        crashed.ensure_code_table()
        crashed.ensure_document_table()
        _seed(crashed, _collection(crashed, source))
        crash(crashed, source)
        assert _state(crashed, source) == SourceResetState(
            source_type=source,
            root_identity=str(tmp_path.resolve()),
            backend_identity=crashed.backend_identity,
            epoch=1,
            generation_id="crashed",
            phase=recorded_phase,
        )

    with _open(tmp_path) as restarted:
        fence = _fence(restarted, source)
        assert fence.phase is not SourceResetPhase.COMPLETE

        enter_rebuild_ingestion(
            restarted, source, began_under=fence, generation_id="crashed"
        )

        state = _state(restarted, source)
        assert state is not None
        assert (state.epoch, state.generation_id, state.phase) == (
            1,
            "crashed",
            SourceResetPhase.COMPLETE,
        )
        collection = _collection(restarted, source)
        assert restarted.client.collection_exists(collection)
        assert _points(restarted, collection) == 0
        fence.validate()


def test_a_surviving_local_directory_blocks_ingestion_and_resurrects_nothing(
    tmp_path: Path, local_config: None
) -> None:
    """A collection directory outliving its deletion stops the reset short.

    The crash leaves the reset after its recorded deletion; the old
    collection's directory is then back on disk, which is what an ``rmtree``
    defeated by an open handle leaves. Recovery must refuse before it
    recreates the name, because a local create re-reads that directory and
    returns the deleted points.

    Mutation: removing the canonical-directory check from
    ``discard_source_storage`` let recovery recreate the collection over the
    directory, and the recreated-count guard raised ``holds 1 points``
    instead of the ``survived`` refusal this test names; restoring it passed.
    """
    del local_config
    saved = tmp_path / "saved-collection"
    with _open(tmp_path) as crashed:
        crashed.ensure_document_table()
        collection = crashed.DOCUMENT_TABLE_NAME
        _seed(crashed, collection)
    with _open(tmp_path) as crashed:
        shutil.copytree(_local_dir(crashed, collection), saved)
        _crash_after_discard(crashed, PublicSourceType.DOCUMENT)
        resurrected_dir = _local_dir(crashed, collection)
    shutil.copytree(saved, resurrected_dir)

    with _open(tmp_path) as restarted:
        fence = _fence(restarted, PublicSourceType.DOCUMENT)
        with pytest.raises(RuntimeError, match="survived delete_collection"):
            enter_rebuild_ingestion(
                restarted,
                PublicSourceType.DOCUMENT,
                began_under=fence,
                generation_id="crashed",
            )

        state = _state(restarted, PublicSourceType.DOCUMENT)
        assert state is not None
        assert state.phase is SourceResetPhase.DISCARDED
        assert not restarted.client.collection_exists(collection)
        assert (
            _fence(restarted, PublicSourceType.DOCUMENT).phase
            is SourceResetPhase.DISCARDED
        )


def test_replaying_a_completed_reset_keeps_confirmed_replacement_work(
    store: VaultStore,
) -> None:
    """Only a new generation discards again; a replay of the same one never does.

    Mutation: removing the completed short-cut discarded the replacement
    collection on the same-generation replay and failed the existence
    assertion (the replay then also raised, refusing to move the phase
    back); restoring it passed.
    """
    collection = store.TABLE_NAME
    reset_selected_sources(store, PublicSourceType.VAULT, generation_id="rebuild-1")
    _seed(store, collection, point_id=7)

    try:
        (replayed,) = reset_selected_sources(
            store, PublicSourceType.VAULT, generation_id="rebuild-1"
        )
    finally:
        # Checked even when the replay raises: a replay that discards has
        # already lost the replacement before any later step can object.
        assert store.client.collection_exists(collection)
        assert _points(store, collection) == 1
    assert replayed.epoch == 1

    (fresh,) = reset_selected_sources(
        store, PublicSourceType.VAULT, generation_id="rebuild-2"
    )
    assert fresh.epoch == 2
    assert _points(store, collection) == 0


def test_a_rebuild_retires_an_open_in_place_publication_with_its_reset(
    store: VaultStore,
) -> None:
    """The receipt an interrupted incremental left open goes with the reset.

    A second entry of the same rebuild finds its own reset complete and
    discards nothing further, so replacement work written after the first
    entry survives it.
    """
    from ..indexer._run_ledger_models import RunAuthority
    from ..indexer._run_ledger_publication_identity import (
        compatibility_for_signature,
    )
    from ._run_ledger_test_support import (
        ledger_test_publish_and_compact,
        ledger_test_signature,
    )

    ledger = _ledger(store)
    signature = ledger_test_signature(
        store.root_dir, backend_identity=store.backend_identity
    )
    parent = ledger.start_generation(signature)
    proof = ledger.establish_verified_publication(
        parent.generation_id, RunAuthority.REBUILD, ()
    )
    ledger_test_publish_and_compact(ledger, parent.generation_id)
    successor = ledger.start_generation(signature)
    ledger.reserve_publication_receipt(
        compatibility_for_signature(signature),
        successor.generation_id,
        expected_parent_revision=proof.revision,
    )
    collection = store.CODE_TABLE_NAME
    _seed(store, collection)
    identity = (str(store.root_dir.resolve()), store.backend_identity)

    state = enter_rebuild_ingestion(
        store,
        PublicSourceType.CODE,
        began_under=_fence(store, PublicSourceType.CODE),
        generation_id="rebuild-1",
    )

    assert (state.epoch, state.generation_id) == (1, "rebuild-1")
    assert (
        ledger.recoverable_publication_receipt(
            source_type=PublicSourceType.CODE,
            root_identity=identity[0],
            backend_identity=identity[1],
        )
        is None
    )
    assert _points(store, collection) == 0
    _seed(store, collection, point_id=5)

    enter_rebuild_ingestion(
        store,
        PublicSourceType.CODE,
        began_under=_fence(store, PublicSourceType.CODE),
        generation_id="rebuild-1",
    )

    assert _state(store, PublicSourceType.CODE) == state
    assert _points(store, collection) == 1


def test_a_superseded_reset_cannot_advance(store: VaultStore) -> None:
    """An older reset owner is fenced once a newer one records intent."""
    ledger = _ledger(store)
    identity = (str(store.root_dir.resolve()), store.backend_identity)
    older = ledger.begin_source_reset(PublicSourceType.CODE, *identity, "old")
    ledger.begin_source_reset(PublicSourceType.CODE, *identity, "new")

    with pytest.raises(SourceResetEpochError, match="superseded"):
        ledger.advance_source_reset(older, SourceResetPhase.DISCARDED)


def test_reset_intent_invalidates_other_resumable_generations(
    store: VaultStore,
) -> None:
    """No checkpoint recorded before the reset can seed the replacement."""
    from ..indexer._run_ledger_models import RunTerminalState
    from ._run_ledger_test_support import ledger_test_signature

    ledger = _ledger(store)
    signature = ledger_test_signature(store.root_dir)
    stale = ledger.start_generation(signature)
    identity = signature.root_identity, signature.backend_identity

    ledger.begin_source_reset(signature.source_type, *identity, "rebuild-1")

    assert ledger.generation(stale.generation_id).terminal_state is (
        RunTerminalState.INVALIDATED
    )


def test_a_new_generation_supersedes_a_reset_a_crash_interrupted(
    tmp_path: Path, local_config: None
) -> None:
    """A different rebuild does not finish another's reset; it resets anew."""
    del local_config
    with _open(tmp_path) as crashed:
        crashed.ensure_table()
        _seed(crashed, crashed.TABLE_NAME)
        _crash_after_intent(crashed, PublicSourceType.VAULT)

    with _open(tmp_path) as restarted:
        state = enter_rebuild_ingestion(
            restarted,
            PublicSourceType.VAULT,
            began_under=_fence(restarted, PublicSourceType.VAULT),
            generation_id="successor",
        )

        assert (state.epoch, state.generation_id, state.phase) == (
            2,
            "successor",
            SourceResetPhase.COMPLETE,
        )
        assert _points(restarted, restarted.TABLE_NAME) == 0


def test_a_rebuild_resumes_only_work_written_after_its_own_reset(
    store: VaultStore,
) -> None:
    """Confirmed units under a generation that never owned the reset are retired.

    A rebuild writes nothing before its reset completes, so units recorded
    under a generation whose completed reset is not its own describe storage
    the reset discards. Resuming would skip them and certify an index
    missing their points.

    Mutation: removing the own-reset check from the shared generation start
    resumed the generation holding pre-reset work and failed the
    generation-id inequality; restoring it passed.
    """
    from ..indexer._run_ledger_models import (
        RunAuthority,
        RunOperation,
        RunTerminalState,
    )
    from ..indexer._vault_checkpoint import VaultRunCheckpoint
    from ..job_control import NO_RUN_CONTROL
    from ._run_ledger_test_support import ledger_test_unit

    def open_rebuild() -> VaultRunCheckpoint:
        return VaultRunCheckpoint.open(
            store.root_dir,
            backend_identity=store.backend_identity,
            authority=RunAuthority.REBUILD,
            operation=RunOperation.FULL,
            run_control=NO_RUN_CONTROL,
        )

    unit = ledger_test_unit("doc", 0, 1)
    unreset = open_rebuild()
    unreset.ledger.record_storage_confirmed_units(unreset.generation_id, (unit,))
    unreset.ledger.finish_generation(unreset.generation_id, RunTerminalState.FAILED)

    replacement = open_rebuild()

    assert replacement.generation_id != unreset.generation_id
    assert (
        unreset.ledger.generation(unreset.generation_id).terminal_state
        is RunTerminalState.INVALIDATED
    )

    reset_selected_sources(
        store, PublicSourceType.VAULT, generation_id=replacement.generation_id
    )
    replacement.ledger.record_storage_confirmed_units(
        replacement.generation_id, (unit,)
    )
    replacement.ledger.finish_generation(
        replacement.generation_id, RunTerminalState.FAILED
    )

    with continue_rebuild(replacement.generation_id):
        assert open_rebuild().generation_id == replacement.generation_id


def _open_vault_rebuild(store: VaultStore) -> VaultRunCheckpoint:
    from ..indexer._run_ledger_models import RunAuthority, RunOperation
    from ..indexer._vault_checkpoint import VaultRunCheckpoint
    from ..job_control import NO_RUN_CONTROL

    return VaultRunCheckpoint.open(
        store.root_dir,
        backend_identity=store.backend_identity,
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=NO_RUN_CONTROL,
    )


def _paused_rebuild(store: VaultStore) -> tuple[VaultRunCheckpoint, CommitUnit]:
    """Leave a rebuild paused after one confirmed replacement unit.

    The replacement point is written after the rebuild's own completed reset
    and recorded under its generation, which is the state a paused or
    interrupted rebuild leaves for its next attempt.
    """
    from ..indexer._run_ledger_models import RunTerminalState
    from ._run_ledger_test_support import ledger_test_unit

    checkpoint = _open_vault_rebuild(store)
    checkpoint.reset_for_rebuild(
        store, began_under=_fence(store, PublicSourceType.VAULT)
    )
    _seed(store, store.TABLE_NAME, point_id=3)
    unit = ledger_test_unit("doc", 0, 1)
    checkpoint.ledger.record_storage_confirmed_units(checkpoint.generation_id, (unit,))
    checkpoint.ledger.finish_generation(
        checkpoint.generation_id, RunTerminalState.REBUILD_INCOMPLETE
    )
    return checkpoint, unit


def test_a_new_rebuild_resets_again_instead_of_continuing_an_earlier_one(
    store: VaultStore,
) -> None:
    """A new request never continues the generation an earlier rebuild left.

    Mutation: treating an unclaimed rebuild as the owner of whatever
    generation the ledger resumes (``rebuild.generation_id in (None,
    generation.generation_id)``) reopened the paused generation and failed
    the generation-id inequality; restoring the claim check passed.
    """
    from ..indexer._run_ledger_models import RunTerminalState

    earlier, _unit = _paused_rebuild(store)

    replacement = _open_vault_rebuild(store)

    assert replacement.generation_id != earlier.generation_id
    assert earlier.ledger.generation(earlier.generation_id).terminal_state is (
        RunTerminalState.INVALIDATED
    )
    replacement.reset_for_rebuild(
        store, began_under=_fence(store, PublicSourceType.VAULT)
    )
    state = _state(store, PublicSourceType.VAULT)
    assert state is not None
    assert (state.epoch, state.generation_id) == (2, replacement.generation_id)
    assert _points(store, store.TABLE_NAME) == 0


def test_a_resumed_rebuild_keeps_the_work_its_generation_confirmed(
    store: VaultStore,
) -> None:
    """The claimed generation reopens over its confirmed unit and never resets.

    Mutation: ignoring the context's claim in the shared generation start
    (opening every rebuild as a new one) retired the paused generation and
    failed the generation-id equality; restoring it passed.
    """
    paused, unit = _paused_rebuild(store)

    with continue_rebuild(paused.generation_id):
        resumed = _open_vault_rebuild(store)
        resumed.reset_for_rebuild(
            store, began_under=_fence(store, PublicSourceType.VAULT)
        )

    assert resumed.generation_id == paused.generation_id
    assert resumed.ledger.unit_committed(resumed.generation_id, unit)
    state = _state(store, PublicSourceType.VAULT)
    assert state is not None
    assert state.epoch == 1
    assert _points(store, store.TABLE_NAME) == 1


def test_a_claim_on_a_replaced_rebuild_is_refused_and_changes_nothing(
    store: VaultStore,
) -> None:
    """A retry of a rebuild a newer rebuild replaced may not resume it.

    Mutation: deleting the supersession refusal from the shared generation
    start let the stale claim open a generation and failed with DID NOT
    RAISE; restoring it passed.
    """
    from ..indexer._rebuild_lifecycle import RebuildSupersededError
    from ..indexer._run_ledger_models import RunTerminalState

    replaced, _unit = _paused_rebuild(store)
    newer = _open_vault_rebuild(store)
    newer.reset_for_rebuild(store, began_under=_fence(store, PublicSourceType.VAULT))
    newer.ledger.finish_generation(
        newer.generation_id, RunTerminalState.REBUILD_INCOMPLETE
    )
    before = _state(store, PublicSourceType.VAULT)

    with (
        continue_rebuild(replaced.generation_id),
        pytest.raises(RebuildSupersededError, match="was replaced"),
    ):
        _open_vault_rebuild(store)

    assert _state(store, PublicSourceType.VAULT) == before
    assert newer.ledger.generation(newer.generation_id).terminal_state is (
        RunTerminalState.REBUILD_INCOMPLETE
    )


def test_a_claim_recorded_before_its_own_reset_still_resumes(
    store: VaultStore,
) -> None:
    """A generation bound before its reset is not mistaken for a replaced one.

    The job records its generation before the reset, so a crash in between
    leaves the source's recorded reset owned by the earlier rebuild while the
    claimed generation is still resumable.

    Mutation: refusing every claim whose generation does not own the
    recorded reset (dropping the resumable check) raised the supersession
    refusal here; restoring it passed.
    """
    from ..indexer._run_ledger_models import RunTerminalState

    _paused_rebuild(store)
    bound = _open_vault_rebuild(store)
    bound.ledger.finish_generation(bound.generation_id, RunTerminalState.FAILED)

    with continue_rebuild(bound.generation_id):
        resumed = _open_vault_rebuild(store)
        resumed.reset_for_rebuild(
            store, began_under=_fence(store, PublicSourceType.VAULT)
        )

    assert resumed.generation_id == bound.generation_id
    state = _state(store, PublicSourceType.VAULT)
    assert state is not None
    assert (state.epoch, state.generation_id) == (2, bound.generation_id)


def _vault_chunk(doc_id: str) -> VaultChunk:
    from .._store_models import VaultChunk

    return VaultChunk(
        doc_id=doc_id,
        ordinal=0,
        chunk_count=1,
        text="replacement body",
        doc_content="replacement body",
        path=f"{doc_id}.md",
        doc_type="adr",
        feature="rebuild",
        date="2026-10-12",
        tags=[],
        related=[],
        title="Replacement",
        vector=[1.0, 0.0],
    )


def test_a_writer_from_before_a_later_reset_stops_before_its_next_write(
    store: VaultStore,
) -> None:
    """An old attempt cannot write into the replacement a later reset opened.

    The stale writer's write policy validates its reset epoch before every
    store write, and its ledger commit refuses because the later reset
    invalidated its generation.

    Mutation: removing the write admission from the store retry loop let
    the stale upsert land in the replacement and failed with DID NOT RAISE;
    restoring it passed.
    """
    from ..indexer._run_ledger_models import RunLedgerStateError
    from ._run_ledger_test_support import ledger_test_unit

    stale = _open_vault_rebuild(store)
    stale.reset_for_rebuild(store, began_under=_fence(store, PublicSourceType.VAULT))
    replacement = _open_vault_rebuild(store)
    replacement.reset_for_rebuild(
        store, began_under=_fence(store, PublicSourceType.VAULT)
    )

    with pytest.raises(SourceResetEpochError, match="after this work began"):
        store.upsert_document_chunks(
            [_vault_chunk("stale")],
            write_policy=stale.run_policy.store_write_policy,
        )
    assert _points(store, store.TABLE_NAME) == 0
    with pytest.raises(RunLedgerStateError, match="immutable"):
        stale.ledger.record_storage_confirmed_units(
            stale.generation_id, (ledger_test_unit("stale", 0, 1),)
        )

    store.upsert_document_chunks(
        [_vault_chunk("fresh")],
        write_policy=replacement.run_policy.store_write_policy,
    )
    assert _points(store, store.TABLE_NAME) == 1


def test_an_incremental_writer_is_fenced_to_the_epoch_it_opened_under(
    store: VaultStore,
) -> None:
    """An incremental or watcher update cannot write into a later replacement.

    Mutation: deleting the open-time fence of non-rebuild checkpoints let
    the incremental upsert land after the reset and failed with DID NOT
    RAISE; restoring it passed.
    """
    from ..indexer._run_ledger_models import RunAuthority, RunOperation
    from ..indexer._vault_checkpoint import VaultRunCheckpoint
    from ..job_control import NO_RUN_CONTROL
    from ._run_ledger_test_support import ledger_test_publish_and_compact

    published = _open_vault_rebuild(store)
    published.reset_for_rebuild(
        store, began_under=_fence(store, PublicSourceType.VAULT)
    )
    published.ledger.establish_verified_publication(
        published.generation_id, RunAuthority.REBUILD, ()
    )
    ledger_test_publish_and_compact(published.ledger, published.generation_id)
    incremental = VaultRunCheckpoint.open(
        store.root_dir,
        backend_identity=store.backend_identity,
        authority=RunAuthority.PUBLICATION,
        operation=RunOperation.INCREMENTAL,
        run_control=NO_RUN_CONTROL,
    )
    replacement = _open_vault_rebuild(store)
    replacement.reset_for_rebuild(
        store, began_under=_fence(store, PublicSourceType.VAULT)
    )

    with pytest.raises(SourceResetEpochError, match="after this work began"):
        store.upsert_document_chunks(
            [_vault_chunk("incremental")],
            write_policy=incremental.run_policy.store_write_policy,
        )
    assert _points(store, store.TABLE_NAME) == 0
