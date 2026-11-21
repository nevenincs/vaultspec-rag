"""Donor admission ranks, bounds and gates real donor roots.

Every donor is a real project root. A donor holds a real published code
rebuild on a real Qdrant server, so its proof, ledger and collection come from
the production path. The manifest is written through the production recorder,
and a defective donor is made by damaging the real artefact admission reads.
Admission itself is observed through its results and through the debug record
the pointer reader leaves when it meets an unreadable pointer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from .. import storage_manifest
from .._store_models import (
    CodeChunk,
    root_collection_prefix,
    served_code_pointer_path,
)
from .._store_writes import workspace_volume_path
from ..config._types import EnvVar
from ..indexer import CodebaseIndexer, _reuse
from ..indexer import _donor_candidates as candidates
from ..indexer._chunk_worker import chunk_and_hash_file
from ..indexer._run_ledger_models import index_run_ledger_path
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore
from .conftest import managed_env
from .integration._helpers import provisioned_qdrant_binary, serve_qdrant
from .test_code_rebuild_stale_evidence import (
    _configure,
    _open_rebuild,
    _request,
    _run,
)
from .test_live_checkpoint_resilience import build_unloaded_model

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest import TempPathFactory

    from ..embeddings import EmbeddingModel
    from ..qdrant_runtime._supervise import QdrantSupervisor

pytestmark = pytest.mark.unit

_CURRENT_MODEL = "dense/current"
_OTHER_MODEL = "dense/other"
_SOURCE = "def shared():\n    return 1\n"
_GOOD_DONORS = 4
_OTHER_MODEL_DONORS = 6
_POINTER_LOGGER = "vaultspec_rag._store_models"


@dataclass(frozen=True)
class _Pool:
    """Real donors published under the current model, and under another one."""

    current: tuple[Path, ...]
    other: tuple[Path, ...]
    epoch: str


def _collection(root: Path) -> str:
    suffix = candidates.CollectionKind.CODE.collection_suffix
    return root_collection_prefix(root) + suffix


def _publish_donor(root: Path, model: str, url: str, encoder: EmbeddingModel) -> None:
    """Publish one real code rebuild of *root* under *model* to the server."""
    root.mkdir(parents=True)
    source = root / "shared.py"
    source.write_text(_SOURCE, encoding="utf-8")
    _configure(model, url)
    with VaultStore(root, embedding_dim=2) as store:
        indexer = CodebaseIndexer(root, encoder, store)
        checkpoint = _open_rebuild(indexer, _request(root))
        _run(indexer, checkpoint, [source])
        indexer._lifecycle.publish(
            checkpoint, reporter=NullProgressReporter(), phase_label="publish donor"
        )


@pytest.fixture(scope="module")
def real_qdrant_binary() -> Path:
    """Provision (or reuse) the pinned real Qdrant binary."""
    return provisioned_qdrant_binary()


@pytest.fixture(scope="module")
def qdrant_server(
    real_qdrant_binary: Path, tmp_path_factory: TempPathFactory
) -> Iterator[QdrantSupervisor]:
    """One real qdrant server on ephemeral ports with temp storage."""
    yield from serve_qdrant(
        real_qdrant_binary, tmp_path_factory.mktemp("qdrant-donor-admission")
    )


@pytest.fixture(scope="module")
def pool(qdrant_server: QdrantSupervisor, tmp_path_factory: TempPathFactory) -> _Pool:
    """Publish the donors once; every case reads them without changing them."""
    base = tmp_path_factory.mktemp("donor-pool")
    overrides = {
        EnvVar.QDRANT_STORAGE_DIR.value: str(base / "qdrant-state"),
        EnvVar.STATUS_DIR.value: str(base / "managed"),
    }
    with managed_env(**overrides):
        # Built first: it resets configuration to local storage.
        encoder = build_unloaded_model()
        current = tuple(base / f"current-{index}" for index in range(_GOOD_DONORS))
        other = tuple(base / f"other-{index}" for index in range(_OTHER_MODEL_DONORS))
        for root in current:
            _publish_donor(root, _CURRENT_MODEL, qdrant_server.url, encoder)
        for root in other:
            _publish_donor(root, _OTHER_MODEL, qdrant_server.url, encoder)
        # A proof belongs to the backend its donor was published to.
        state = candidates.read_donor_recorded_state(
            current[0], candidates.CollectionKind.CODE
        )
    assert state is not None, "a published donor must have a readable proof"
    return _Pool(current, other, state.content_identity)


@dataclass
class _Admission:
    root: Path
    store: VaultStore
    pool: _Pool
    workdir: Path

    def rank(self, *ordered: Path) -> None:
        """Record *ordered* in the manifest, newest first, as real roots."""
        for position, donor in enumerate(ordered):
            stamp = f"2026-10-{99 - position:02}T00:00:00+00:00"
            storage_manifest.record_root(donor, backend="server", last_indexed=stamp)

    def defective(self, name: str, defect: str) -> Path:
        """A donor root whose pointer or proof is damaged for real."""
        donor = self.workdir / name
        donor.mkdir()
        pointer = served_code_pointer_path(donor)
        if defect == "pointer-garbage":
            pointer.parent.mkdir(parents=True, exist_ok=True)
            pointer.write_text("not json", encoding="utf-8")
        elif defect == "pointer-directory":
            pointer.mkdir(parents=True)
        elif defect == "ledger-garbage":
            ledger = index_run_ledger_path(workspace_volume_path(donor.resolve()))
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_bytes(b"this is not a sqlite database" * 64)
        else:
            assert defect == "no-proof", defect
        return donor

    def resolve(
        self,
    ) -> tuple[_reuse.ReuseStats | None, _reuse.DonorReuseContext | None]:
        return _reuse.resolve_donor_reuse(
            self.root,
            candidates.CollectionKind.CODE,
            self.store,
            expected_content_epoch=self.pool.epoch,
        )


@pytest.fixture
def admission(
    tmp_path: Path,
    pool: _Pool,
    qdrant_server: QdrantSupervisor,
    isolated_status_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> Iterator[_Admission]:
    del isolated_status_dir
    state_dir = str(tmp_path / "qdrant-state")
    with managed_env(**{EnvVar.QDRANT_STORAGE_DIR.value: state_dir}):
        _configure(_CURRENT_MODEL, qdrant_server.url)
        root = tmp_path / "target"
        root.mkdir()
        workdir = tmp_path / "donors"
        workdir.mkdir()
        caplog.set_level(logging.DEBUG, logger=_POINTER_LOGGER)
        with VaultStore(root, embedding_dim=2) as store:
            yield _Admission(root, store, pool, workdir)


def _inspected(caplog: pytest.LogCaptureFixture, donor: Path) -> bool:
    """Whether admission read *donor*'s pointer, as its unreadable pointer logs."""
    pointer = str(served_code_pointer_path(donor))
    return any(pointer in record.getMessage() for record in caplog.records)


def test_incompatible_three_do_not_starve_fourth_donor(admission: _Admission) -> None:
    """Incompatible donors ranked first use the window; a fourth still qualifies.

    Mutation: sizing the inspection window to the three-donor selection cap
    failed the starvation assertion; restoring six passed.
    """
    pool = admission.pool
    admission.rank(*pool.other[:3], *pool.current[:4])
    stats, context = admission.resolve()
    assert context is not None, (
        "eligible fourth donor was starved by incompatible first three"
    )
    assert context.donor_collections == tuple(
        _collection(root) for root in pool.current[:3]
    ), "incompatible model passed canonical donor gate"
    assert stats is not None and not stats.donor_absent


def test_six_inspections_bound_incompatible_candidates(
    admission: _Admission, caplog: pytest.LogCaptureFixture
) -> None:
    """Six incompatible donors exhaust the window; later donors are not reached.

    Mutation: growing the window to twelve inspections reached the compatible
    donors past it and failed the bound assertion; restoring six passed.
    """
    pool = admission.pool
    beyond = admission.defective("beyond-window", "pointer-garbage")
    admission.rank(*pool.other, *pool.current[:2], beyond)
    stats, context = admission.resolve()
    # Compatible donors sit just past the window, so an unbounded inspection
    # would reach them and select one.
    assert context is None and stats is not None and stats.donor_absent, (
        "incompatible model passed canonical donor gate or the window grew"
    )
    assert not _inspected(caplog, beyond), "donor inspections exceeded six"


def test_three_selected_donors_stop_io_and_remain_frozen(
    admission: _Admission,
    caplog: pytest.LogCaptureFixture,
    qdrant_server: QdrantSupervisor,
) -> None:
    """Selection stops at three donors, and the chosen set no longer reads admission.

    Removing the manifest and changing the model after resolution leaves the
    donors the context holds adopting real stored vectors.

    Mutation: inspecting on after the third donor and trimming the result
    afterwards read the fourth pointer and failed the stop-I/O assertion.
    """
    pool = admission.pool
    unread = admission.defective("after-selection", "pointer-garbage")
    admission.rank(*pool.current[:3], unread, pool.current[3])
    stats, context = admission.resolve()
    assert context is not None and stats is not None
    assert context.donor_collections == tuple(
        _collection(root) for root in pool.current[:3]
    ), "selected vector donors exceeded three"
    assert not _inspected(caplog, unread), (
        "selected three donors failed to stop admission I/O"
    )

    # The context is frozen: removing the manifest it was resolved from, and
    # switching the model its donors had to match, changes nothing it reads.
    storage_manifest.manifest_path().unlink()
    _configure(_OTHER_MODEL, qdrant_server.url)
    source = admission.root / "shared.py"
    source.write_text(_SOURCE, encoding="utf-8")
    shared = chunk_and_hash_file(source, admission.root).chunks[0]
    assert isinstance(shared, CodeChunk)
    unheld = CodeChunk("held.py:0", "held.py", "python", "def held(): ...", 1, 1)
    assert context.adopt_verified_vectors([shared, unheld], sparse_required=False) == [
        True,
        False,
    ]
    assert shared.vector == [0.0, 1.0], "donor vector was not adopted"
    assert unheld.vector == [], "a chunk no donor holds must remain an encode miss"
    assert stats.reuse_hits == 1 and stats.reuse_misses == 1


def test_missing_and_failed_evidence_consume_inspection_window(
    admission: _Admission, caplog: pytest.LogCaptureFixture
) -> None:
    """Unverifiable, unreadable and absent evidence each use an inspection.

    Mutation: growing the window to twelve inspections failed the window
    assertion; restoring six passed.
    """
    pool = admission.pool
    unverifiable = admission.defective("pointer-garbage", "pointer-garbage")
    unreadable = admission.defective("pointer-directory", "pointer-directory")
    absent = admission.defective("no-proof", "no-proof")
    corrupt = admission.defective("ledger-garbage", "ledger-garbage")
    beyond = admission.defective("beyond-window", "pointer-garbage")
    admission.rank(
        unverifiable,
        unreadable,
        absent,
        corrupt,
        *pool.current[:2],
        beyond,
        pool.current[2],
    )
    stats, context = admission.resolve()
    # The four unreadable donors used four of the six inspections, so only two
    # sound donors fit; a window that did not count them would reach a third.
    assert context is not None and stats is not None
    assert context.donor_collections == tuple(
        _collection(root) for root in pool.current[:2]
    ), "unreadable donors expanded inspection window"
    assert _inspected(caplog, unverifiable) and _inspected(caplog, unreadable)
    assert not _inspected(caplog, beyond)


def test_filtering_and_family_newest_prefix_order_precede_pointer_io(
    admission: _Admission, caplog: pytest.LogCaptureFixture
) -> None:
    """Own, wrong-backend and wrong-kind donors are dropped before any pointer read.

    Mutation: ranking oldest first failed the ranking assertion; restoring
    newest first passed.
    """
    family = admission.workdir / "family.git"
    family.mkdir()

    def linked(name: str, common: Path) -> Path:
        """A real linked-worktree layout resolving to *common*."""
        root = admission.workdir / name
        root.mkdir()
        gitdir = common / "worktrees" / name
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..", encoding="utf-8")
        (root / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        return root

    near = [linked(name, family) for name in ("near-new", "near-a", "near-z")]
    far = linked("far", admission.workdir / "other-family.git")
    # The target belongs to the same repository as the near donors.
    (admission.root / ".git").write_text(
        (near[0] / ".git").read_text(encoding="utf-8"), encoding="utf-8"
    )
    wrong_kind = admission.defective("wrong-kind", "pointer-garbage")
    local = admission.defective("local", "pointer-garbage")
    excluded = [
        admission.defective("own-pointer", "pointer-garbage"),
        local,
        wrong_kind,
    ]
    # Each excluded donor holds an unreadable pointer, so reading it would show.
    served_code_pointer_path(admission.root).parent.mkdir(parents=True, exist_ok=True)
    served_code_pointer_path(admission.root).write_text("not json", encoding="utf-8")
    for donor, stamp in (
        (admission.root, "9999"),
        (far, "9999"),
        (near[0], "2001"),
        (near[1], "2000"),
        (near[2], "2000"),
        (wrong_kind, "9999"),
    ):
        storage_manifest.record_root(donor, backend="server", last_indexed=stamp)
    storage_manifest.record_root(local, backend="local", last_indexed="9999")
    prefix = root_collection_prefix(wrong_kind)
    assert storage_manifest.retain_collections(prefix, {_collection(wrong_kind)})
    del excluded

    found = list(
        candidates.iter_donor_candidates(admission.root, candidates.CollectionKind.CODE)
    )
    assert not _inspected(caplog, admission.root), (
        "own-root donor resolved a publication pointer"
    )
    assert not _inspected(caplog, local), (
        "wrong-backend donor resolved a publication pointer"
    )
    assert not _inspected(caplog, wrong_kind), (
        "wrong-kind donor resolved a publication pointer"
    )
    tied = sorted(near[1:], key=root_collection_prefix)
    assert [candidate.root for candidate in found] == [
        str(donor.resolve()) for donor in (near[0], *tied)
    ], "donor filtering or family/newest/prefix ranking changed"
    assert str(far.resolve()) not in {candidate.root for candidate in found}


def test_disabled_reuse_and_failed_manifest_do_not_read_pointers(
    admission: _Admission,
    caplog: pytest.LogCaptureFixture,
    qdrant_server: QdrantSupervisor,
) -> None:
    """Neither a disabled switch nor an unreadable manifest reaches a donor pointer.

    Mutation: ignoring the reuse switch resolved donors and failed the
    disabled assertion; restoring it passed.
    """
    unread = admission.defective("unread", "pointer-garbage")
    admission.rank(unread, *admission.pool.current[:3])
    _configure(_CURRENT_MODEL, qdrant_server.url, index_reuse_enabled=False)
    assert admission.resolve() == (None, None)
    assert not _inspected(caplog, unread)

    _configure(_CURRENT_MODEL, qdrant_server.url)
    storage_manifest.manifest_path().write_text("{not json", encoding="utf-8")
    stats, context = admission.resolve()
    assert context is None and stats is not None and stats.donor_absent
    assert not _inspected(caplog, unread)
