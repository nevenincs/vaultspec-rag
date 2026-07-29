"""Unit tests for read-only donor candidacy and eligibility.

Pure filesystem logic: no GPU, no Qdrant, no service. The managed service
directory is isolated to a temp path through the real
``VAULTSPEC_RAG_STATUS_DIR`` / ``VAULTSPEC_RAG_QDRANT_STORAGE_DIR``
environment seams, and every donor sidecar is a real file built in tmp -
no mocks stand in for the recorded state the gates read.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from .. import store_schema
from .._index_breadth import index_meta_path
from .._store_models import (
    generation_code_collection,
    publish_served_code_collection,
    root_collection_prefix,
)
from ..config._settings import get_config, reset_config
from ..indexer._code_meta import (
    CODE_EMBED_SCHEMA,
    CONTENT_EPOCH_KEY,
    EMBED_SCHEMA_KEY,
)
from ..indexer._document_meta import (
    DocumentIndexMetadata,
    document_metadata_path,
    write_document_meta,
)
from ..indexer._donor_candidates import (
    DONOR_CANDIDATE_CAP,
    CollectionKind,
    DonorCandidate,
    IneligibilityReason,
    ModelIdentity,
    VectorSchema,
    discover_donor_candidates,
    evaluate_donor_eligibility,
    index_meta_source,
    read_donor_recorded_state,
)
from ..indexer._vault_meta import (
    VAULT_CONTENT_EPOCH_KEY as _VAULT_EPOCH_KEY,
)
from ..indexer._vault_meta import (
    VAULT_POINT_SCHEMA as _VAULT_SCHEMA,
)
from ..indexer._vault_meta import (
    VAULT_POINT_SCHEMA_KEY as _VAULT_SCHEMA_KEY,
)
from ..storage_manifest import ManifestEntry, record_root

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def isolated_managed_dirs(tmp_path: Path) -> Iterator[None]:
    """Isolate the managed service and qdrant storage dirs to tmp."""
    keys = {
        "VAULTSPEC_RAG_STATUS_DIR": str(tmp_path / "managed"),
        "VAULTSPEC_RAG_QDRANT_STORAGE_DIR": str(
            tmp_path / "managed" / "qdrant-server" / "storage"
        ),
    }
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(keys)
    reset_config()
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


def _make_root(base: Path, name: str) -> Path:
    root = base / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_code_sidecar(
    root: Path,
    *,
    epoch: str = "epoch-current",
    marker: str = CODE_EMBED_SCHEMA,
    drop_epoch_key: bool = False,
) -> Path:
    cfg = get_config()
    path = root / cfg.data_dir / cfg.code_index_metadata_file
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, str] = {EMBED_SCHEMA_KEY: marker}
    if not drop_epoch_key:
        payload[CONTENT_EPOCH_KEY] = epoch
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_vault_sidecar(
    root: Path, *, epoch: str, marker: str = _VAULT_SCHEMA
) -> Path:
    cfg = get_config()
    path = root / cfg.data_dir / cfg.index_metadata_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({_VAULT_SCHEMA_KEY: marker, _VAULT_EPOCH_KEY: epoch}),
        encoding="utf-8",
    )
    return path


_EXPECTED_SCHEMA = VectorSchema(
    dense_name="dense", dense_dim=1024, sparse_name="sparse"
)
_EXPECTED_MODEL = ModelIdentity(
    dense_model="dense-model",
    sparse_model="sparse-model",
    embed_schema=CODE_EMBED_SCHEMA,
)


def _make_candidate(
    root: Path,
    *,
    kind: CollectionKind = CollectionKind.CODE,
    storage_schema_version: int = store_schema.STORAGE_SCHEMA_VERSION,
) -> DonorCandidate:
    prefix = "r0donor_"
    return DonorCandidate(
        prefix=prefix,
        root=str(root),
        backend="server",
        kind=kind,
        collection=prefix + kind.collection_suffix,
        last_indexed="2026-07-24T00:00:00",
        storage_schema_version=storage_schema_version,
        family_rank=2,
    )


def _evaluate(
    candidate: DonorCandidate,
    *,
    expected_epoch: str = "epoch-current",
    probe_schema: VectorSchema | None = _EXPECTED_SCHEMA,
    use_probe: bool = True,
):
    return evaluate_donor_eligibility(
        candidate,
        kind=CollectionKind.CODE,
        expected_content_epoch=expected_epoch,
        expected_schema=_EXPECTED_SCHEMA,
        donor_schema_probe=(lambda _collection: probe_schema) if use_probe else None,
        expected_model=_EXPECTED_MODEL,
    )


def _make_worktree(base: Path, repo: Path, name: str) -> Path:
    """Lay out a linked-worktree root by files alone (no git subprocess)."""
    worktree = base / name
    worktree.mkdir(parents=True)
    gitdir = repo / ".git" / "worktrees" / name
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..", encoding="utf-8")
    (worktree / ".git").write_text(f"gitdir: {gitdir}", encoding="utf-8")
    return worktree


class TestDiscovery:
    def test_excludes_own_prefix(self, tmp_path: Path) -> None:
        target = _make_root(tmp_path, "target")
        donor = _make_root(tmp_path, "donor")
        record_root(target, backend="server", last_indexed="2026-07-24T01:00:00")
        record_root(donor, backend="server", last_indexed="2026-07-24T02:00:00")

        found = discover_donor_candidates(target, CollectionKind.CODE)

        prefixes = {candidate.prefix for candidate in found}
        assert root_collection_prefix(target) not in prefixes
        assert root_collection_prefix(donor) in prefixes

    def test_filters_backend(self, tmp_path: Path) -> None:
        target = _make_root(tmp_path, "target")
        local_donor = _make_root(tmp_path, "local-donor")
        record_root(local_donor, backend="local", last_indexed="2026-07-24T02:00:00")

        assert discover_donor_candidates(target, CollectionKind.CODE) == []

    def test_skips_entries_without_the_kind_collection(self, tmp_path: Path) -> None:
        target = _make_root(tmp_path, "target")
        donor = _make_root(tmp_path, "donor")
        prefix = "rlegacy_"
        # A legacy-shaped entry that never stored the document collection.
        manifest = {
            prefix: ManifestEntry(
                prefix=prefix,
                root=str(donor),
                backend="server",
                last_indexed="2026-07-24T02:00:00",
                collections=(
                    prefix + store_schema.VAULT_COLLECTION,
                    prefix + store_schema.CODE_COLLECTION,
                ),
            )
        }

        documents = discover_donor_candidates(
            target, CollectionKind.DOCUMENT, manifest=manifest
        )
        code = discover_donor_candidates(target, CollectionKind.CODE, manifest=manifest)

        assert documents == []
        assert [candidate.prefix for candidate in code] == [prefix]
        assert code[0].collection == prefix + store_schema.CODE_COLLECTION

    def test_published_rebuild_is_consulted_at_its_served_collection(
        self, tmp_path: Path
    ) -> None:
        """A donor that rebuilt is discovered, at the collection it serves.

        The manifest declares a namespace under the derived base names only,
        so requiring the *served* generation name to appear there rejects
        every donor that has ever published a rebuild. Mutate the membership
        check to ask about ``collection`` instead of ``derived`` and this
        fails on the emptiness assertion below.
        """
        target = _make_root(tmp_path, "target")
        donor = _make_root(tmp_path, "donor")
        record_root(donor, backend="server", last_indexed="2026-07-24T02:00:00")
        prefix = root_collection_prefix(donor)
        served = generation_code_collection(prefix + store_schema.CODE_COLLECTION, "g1")
        publish_served_code_collection(donor, served)

        found = discover_donor_candidates(target, CollectionKind.CODE)

        assert [candidate.prefix for candidate in found] == [prefix]
        assert found[0].collection == served

    def test_worktree_family_sibling_outranks_newer_stranger(
        self, tmp_path: Path
    ) -> None:
        repo = _make_root(tmp_path, "repo")
        worktrees = tmp_path / "worktrees"
        target = _make_worktree(worktrees, repo, "main")
        sibling = _make_worktree(worktrees, repo, "feature")
        stranger = _make_root(tmp_path / "elsewhere", "other-project")
        record_root(sibling, backend="server", last_indexed="2026-01-01T00:00:00")
        record_root(stranger, backend="server", last_indexed="2026-07-24T00:00:00")

        found = discover_donor_candidates(target, CollectionKind.CODE)

        assert [candidate.root for candidate in found] == [
            str(sibling.resolve()),
            str(stranger.resolve()),
        ]
        assert found[0].family_rank == 0

    def test_path_family_fallback_ranks_shared_parent_before_stranger(
        self, tmp_path: Path
    ) -> None:
        parent = tmp_path / "projects"
        target = _make_root(parent, "target")
        neighbour = _make_root(parent, "neighbour")
        stranger = _make_root(tmp_path / "elsewhere", "stranger")
        record_root(neighbour, backend="server", last_indexed="2026-01-01T00:00:00")
        record_root(stranger, backend="server", last_indexed="2026-07-24T00:00:00")

        found = discover_donor_candidates(target, CollectionKind.CODE)

        assert [candidate.root for candidate in found] == [
            str(neighbour.resolve()),
            str(stranger.resolve()),
        ]
        assert found[0].family_rank == 1

    def test_newest_last_indexed_first_within_a_rank(self, tmp_path: Path) -> None:
        parent = tmp_path / "projects"
        target = _make_root(parent, "target")
        older = _make_root(parent, "older")
        newer = _make_root(parent, "newer")
        record_root(older, backend="server", last_indexed="2026-01-01T00:00:00")
        record_root(newer, backend="server", last_indexed="2026-07-24T00:00:00")

        found = discover_donor_candidates(target, CollectionKind.CODE)

        assert [candidate.root for candidate in found] == [
            str(newer.resolve()),
            str(older.resolve()),
        ]

    def test_candidate_cap_is_enforced(self, tmp_path: Path) -> None:
        parent = tmp_path / "projects"
        target = _make_root(parent, "target")
        for ordinal in range(DONOR_CANDIDATE_CAP + 2):
            donor = _make_root(parent, f"donor-{ordinal}")
            record_root(
                donor,
                backend="server",
                last_indexed=f"2026-07-{ordinal + 1:02d}T00:00:00",
            )

        assert len(discover_donor_candidates(target, CollectionKind.CODE)) == (
            DONOR_CANDIDATE_CAP
        )
        assert len(discover_donor_candidates(target, CollectionKind.CODE, cap=1)) == 1
        assert discover_donor_candidates(target, CollectionKind.CODE, cap=0) == []


class TestEligibilityGates:
    def test_fully_eligible_donor_passes_every_gate(self, tmp_path: Path) -> None:
        donor = _make_root(tmp_path, "donor")
        _write_code_sidecar(donor)

        verdict = _evaluate(_make_candidate(donor))

        assert verdict.eligible
        assert verdict.reasons == ()

    def test_wrong_collection_kind_is_rejected(self, tmp_path: Path) -> None:
        donor = _make_root(tmp_path, "donor")
        _write_code_sidecar(donor)

        verdict = _evaluate(_make_candidate(donor, kind=CollectionKind.VAULT))

        # Binds the kind-equality comparison specifically: every other gate
        # passes, so a kind gate deleted or weakened turns this reason absent.
        assert not verdict.eligible
        assert verdict.reasons == (IneligibilityReason.KIND_MISMATCH,)

    def test_storage_schema_generation_mismatch_is_rejected(
        self, tmp_path: Path
    ) -> None:
        donor = _make_root(tmp_path, "donor")
        _write_code_sidecar(donor)

        verdict = _evaluate(
            _make_candidate(
                donor,
                storage_schema_version=store_schema.STORAGE_SCHEMA_VERSION - 1,
            )
        )

        assert not verdict.eligible
        assert verdict.reasons == (IneligibilityReason.STORAGE_SCHEMA_MISMATCH,)

    def test_dense_dimensionality_mismatch_is_rejected(self, tmp_path: Path) -> None:
        donor = _make_root(tmp_path, "donor")
        _write_code_sidecar(donor)

        verdict = _evaluate(
            _make_candidate(donor),
            probe_schema=VectorSchema(
                dense_name="dense", dense_dim=768, sparse_name="sparse"
            ),
        )

        # Binds the dims/layout equality specifically: only the probed donor
        # schema differs (dimension 768 vs 1024).
        assert not verdict.eligible
        assert verdict.reasons == (IneligibilityReason.VECTOR_LAYOUT_MISMATCH,)

    def test_named_vector_layout_mismatch_is_rejected(self, tmp_path: Path) -> None:
        donor = _make_root(tmp_path, "donor")
        _write_code_sidecar(donor)

        verdict = _evaluate(
            _make_candidate(donor),
            probe_schema=VectorSchema(
                dense_name="dense", dense_dim=1024, sparse_name=None
            ),
        )

        assert not verdict.eligible
        assert verdict.reasons == (IneligibilityReason.VECTOR_LAYOUT_MISMATCH,)

    def test_unreachable_donor_schema_fails_closed(self, tmp_path: Path) -> None:
        donor = _make_root(tmp_path, "donor")
        _write_code_sidecar(donor)

        verdict = _evaluate(_make_candidate(donor), probe_schema=None)

        assert not verdict.eligible
        assert verdict.reasons == (IneligibilityReason.SCHEMA_UNAVAILABLE,)

    def test_model_identity_mismatch_is_rejected(self, tmp_path: Path) -> None:
        donor = _make_root(tmp_path, "donor")
        # The embed-input format marker is the per-root recorded model
        # identity; a donor stamped with an older marker must be refused.
        _write_code_sidecar(donor, marker="1")

        verdict = _evaluate(_make_candidate(donor))

        # Binds the embed-marker comparison specifically: the epoch matches,
        # so only the identity gate can produce this rejection.
        assert not verdict.eligible
        assert verdict.reasons == (IneligibilityReason.MODEL_IDENTITY_MISMATCH,)

    def test_content_epoch_mismatch_is_rejected(self, tmp_path: Path) -> None:
        donor = _make_root(tmp_path, "donor")
        _write_code_sidecar(donor, epoch="epoch-stale")

        verdict = _evaluate(_make_candidate(donor), expected_epoch="epoch-current")

        # Binds the sentinel equality specifically: marker and schema match,
        # so only the epoch gate can produce this rejection.
        assert not verdict.eligible
        assert verdict.reasons == (IneligibilityReason.CONTENT_EPOCH_MISMATCH,)

    def test_missing_sidecar_fails_closed(self, tmp_path: Path) -> None:
        donor = _make_root(tmp_path, "donor")

        verdict = _evaluate(_make_candidate(donor))

        assert not verdict.eligible
        assert verdict.reasons == (IneligibilityReason.SIDECAR_UNAVAILABLE,)

    def test_malformed_sidecar_fails_closed(self, tmp_path: Path) -> None:
        donor = _make_root(tmp_path, "donor")
        path = _write_code_sidecar(donor)
        path.write_text("not json {", encoding="utf-8")

        verdict = _evaluate(_make_candidate(donor))

        assert not verdict.eligible
        assert verdict.reasons == (IneligibilityReason.SIDECAR_UNAVAILABLE,)

    def test_legacy_sidecar_without_epoch_key_fails_closed(
        self, tmp_path: Path
    ) -> None:
        donor = _make_root(tmp_path, "donor")
        _write_code_sidecar(donor, drop_epoch_key=True)

        verdict = _evaluate(_make_candidate(donor))

        assert not verdict.eligible
        assert verdict.reasons == (IneligibilityReason.SIDECAR_UNAVAILABLE,)


class TestRecordedState:
    def test_both_kinds_read_the_shared_resolver_path(self, tmp_path: Path) -> None:
        """Each sidecar kind reads the file the shared resolver names.

        The donor read and the breadth readers must land on one file per
        domain. The helpers above spell the sidecar path independently, from
        config, so pinning that spelling against the resolver and then reading
        through the production entry point fails if either side moves - which
        a second inline spelling of the same resolution would not.

        Writing both sidecars with distinct epochs also pins the discrimination:
        a crossing that returned the neighbouring domain would resolve the
        other file, and each read would find the keys it wants absent.
        """
        donor = _make_root(tmp_path, "donor")
        code_path = _write_code_sidecar(donor, epoch="code-epoch")
        vault_path = _write_vault_sidecar(donor, epoch="vault-epoch")

        assert code_path == index_meta_path(
            donor, index_meta_source(CollectionKind.CODE)
        )
        assert vault_path == index_meta_path(
            donor, index_meta_source(CollectionKind.VAULT)
        )

        code = read_donor_recorded_state(donor, CollectionKind.CODE)
        vault = read_donor_recorded_state(donor, CollectionKind.VAULT)

        assert code is not None
        assert code.content_epoch == "code-epoch"
        assert code.embed_schema == CODE_EMBED_SCHEMA
        assert vault is not None
        assert vault.content_epoch == "vault-epoch"
        assert vault.embed_schema == _VAULT_SCHEMA

    def test_vault_sidecar_round_trip(self, tmp_path: Path) -> None:
        donor = _make_root(tmp_path, "donor")
        _write_vault_sidecar(donor, epoch="vault-epoch")

        state = read_donor_recorded_state(donor, CollectionKind.VAULT)

        assert state is not None
        assert state.content_epoch == "vault-epoch"
        assert state.embed_schema == "2"

    def test_vault_sidecar_without_epoch_reads_as_unavailable(
        self, tmp_path: Path
    ) -> None:
        donor = _make_root(tmp_path, "donor")
        cfg = get_config()
        path = donor / cfg.data_dir / cfg.index_metadata_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({_VAULT_SCHEMA_KEY: _VAULT_SCHEMA}), encoding="utf-8"
        )

        assert read_donor_recorded_state(donor, CollectionKind.VAULT) is None

    def test_document_sidecar_round_trip(self, tmp_path: Path) -> None:
        donor = _make_root(tmp_path, "donor")
        write_document_meta(
            document_metadata_path(donor),
            DocumentIndexMetadata(
                membership_fingerprint="mf",
                content_fingerprint="doc-epoch",
                policy_snapshot="ps",
                files=(),
                generation_id="g1",
            ),
        )

        state = read_donor_recorded_state(donor, CollectionKind.DOCUMENT)

        assert state is not None
        assert state.content_epoch == "doc-epoch"

    def test_incomplete_document_publication_reads_as_unavailable(
        self, tmp_path: Path
    ) -> None:
        donor = _make_root(tmp_path, "donor")
        write_document_meta(
            document_metadata_path(donor),
            DocumentIndexMetadata(
                membership_fingerprint="mf",
                content_fingerprint="doc-epoch",
                policy_snapshot="ps",
                files=(),
                generation_id="g1",
                complete=False,
            ),
        )

        assert read_donor_recorded_state(donor, CollectionKind.DOCUMENT) is None


def test_import_never_loads_torch() -> None:
    """The donor module must stay importable on the CPU-only import chain."""
    code = (
        "import sys; import vaultspec_rag.indexer._donor_candidates; "
        "sys.exit(1 if 'torch' in sys.modules else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
