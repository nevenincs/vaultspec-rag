"""Admission exercises real ranking and gates with isolated evidence readers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from .. import _store_models, storage_manifest
from ..config import _settings
from ..indexer import _donor_candidates as candidates
from ..indexer import _reuse
from ..storage_manifest import ManifestEntry

if TYPE_CHECKING:
    from ..store_runtime import DonorPoint, VaultStore

pytestmark = pytest.mark.unit

_MODEL = candidates.ModelIdentity("dense/current", "sparse/current", "2")
_SCHEMA = candidates.VectorSchema("dense", 1024, "sparse")
_EMBEDDING = (
    json.dumps(
        {"dense": _MODEL.dense_model, "sparse": _MODEL.sparse_model},
        sort_keys=True,
        separators=(",", ":"),
    )
    + ":1024:2"
)
_VALID = candidates.DonorRecordedState("epoch", _EMBEDDING)


@dataclass
class _Transport:
    unsupported: set[str] = field(default_factory=set)
    failures: set[str] = field(default_factory=set)
    capability_calls: list[str] = field(default_factory=list)
    vector_calls: list[str] = field(default_factory=list)

    def supports_donor_reads(self, collection: str) -> bool:
        self.capability_calls.append(collection)
        if collection in self.failures:
            raise OSError("isolated capability unavailable")
        return collection not in self.unsupported

    def retrieve_donor_points(
        self, collection: str, point_ids: list[str]
    ) -> dict[str, DonorPoint]:
        del point_ids
        self.vector_calls.append(collection)
        raise OSError("isolated vector transport unavailable")


@dataclass
class _Admission:
    root: Path
    entries: dict[str, ManifestEntry]
    pointers: dict[str, str | Exception | None]
    proofs: dict[str, candidates.DonorRecordedState | Exception | None]
    transport: _Transport
    pointer_calls: list[str]
    proof_calls: list[str]

    def resolve(
        self,
    ) -> tuple[_reuse.ReuseStats | None, _reuse.DonorReuseContext | None]:
        return _reuse.resolve_donor_reuse(
            self.root,
            candidates.CollectionKind.CODE,
            cast("VaultStore", self.transport),
            expected_content_epoch="epoch",
        )


@pytest.fixture
def admission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Admission:
    entries = {
        f"d{index:03}_": ManifestEntry(
            prefix=f"d{index:03}_",
            root=str(tmp_path / f"donor-{index:03}"),
            backend="server",
            last_indexed=f"2026-10-{100 - index:03}",
            collections=(f"d{index:03}_codebase_docs",),
        )
        for index in range(100)
    }
    pointers: dict[str, str | Exception | None] = {
        entry.root: f"{prefix}served" for prefix, entry in entries.items()
    }
    proofs: dict[str, candidates.DonorRecordedState | Exception | None] = {
        entry.root: _VALID for entry in entries.values()
    }
    pointer_calls: list[str] = []
    proof_calls: list[str] = []

    def pointer(root: Path | str) -> str | None:
        pointer_calls.append(str(root))
        value = pointers.get(str(root))
        if isinstance(value, Exception):
            raise value
        return value

    def proof(
        root: Path | str, kind: candidates.CollectionKind
    ) -> candidates.DonorRecordedState | None:
        assert kind is candidates.CollectionKind.CODE
        proof_calls.append(str(root))
        value = proofs.get(str(root))
        if isinstance(value, Exception):
            raise value
        return value

    def own_prefix(root: Path | str) -> str:
        del root
        return "own_"

    def family(root: Path) -> Path:
        del root
        return tmp_path / "family"

    def model(kind: candidates.CollectionKind) -> candidates.ModelIdentity:
        del kind
        return _MODEL

    monkeypatch.setattr(storage_manifest, "load_manifest", lambda: entries)
    monkeypatch.setattr(_store_models, "root_collection_prefix", own_prefix)
    monkeypatch.setattr(_store_models, "read_served_code_collection", pointer)
    monkeypatch.setattr(candidates, "git_common_dir", family)
    monkeypatch.setattr(candidates, "read_donor_recorded_state", proof)
    monkeypatch.setattr(candidates, "expected_vector_schema", lambda: _SCHEMA)
    monkeypatch.setattr(candidates, "current_model_identity", model)
    monkeypatch.setattr(
        _settings,
        "get_config",
        lambda: SimpleNamespace(
            index_reuse_enabled=True, effective_server_mode=lambda: True
        ),
    )
    return _Admission(
        tmp_path / "target",
        entries,
        pointers,
        proofs,
        _Transport(),
        pointer_calls,
        proof_calls,
    )


def test_incompatible_three_do_not_starve_fourth_donor(admission: _Admission) -> None:
    for entry in list(admission.entries.values())[:3]:
        admission.proofs[entry.root] = candidates.DonorRecordedState(
            "epoch", "old-model"
        )
    stats, context = admission.resolve()
    assert context is not None, (
        "eligible fourth donor was starved by incompatible first three"
    )
    assert context.donor_collections == ("d003_served", "d004_served", "d005_served"), (
        "incompatible model passed canonical donor gate"
    )
    assert stats is not None and not stats.donor_absent
    assert len(admission.pointer_calls) == len(admission.proof_calls) == 6
    assert admission.transport.capability_calls == list(context.donor_collections)


def test_six_inspections_bound_hundred_incompatible_candidates(
    admission: _Admission,
) -> None:
    for entry in admission.entries.values():
        admission.proofs[entry.root] = candidates.DonorRecordedState(
            "other-epoch", _EMBEDDING
        )
    stats, context = admission.resolve()
    assert context is None and stats is not None and stats.donor_absent, (
        "incompatible epoch passed canonical donor gate"
    )
    assert len(admission.pointer_calls) == 6, "donor pointer inspections exceeded six"
    assert len(admission.proof_calls) == 6, "donor proof inspections exceeded six"
    assert not admission.transport.capability_calls


def test_three_selected_donors_stop_io_and_remain_frozen(admission: _Admission) -> None:
    stats, context = admission.resolve()
    assert context is not None and stats is not None
    assert len(context.donor_collections) == 3, "selected vector donors exceeded three"
    assert len(admission.pointer_calls) == 3, (
        "selected three donors failed to stop admission I/O"
    )
    assert len(admission.proof_calls) == 3, (
        "canonical donor gate inspected proof more than once"
    )
    assert admission.transport.capability_calls == list(context.donor_collections), (
        "donor capability was queried more than once"
    )
    admission.entries.clear()
    admission.proofs.clear()
    admission.pointers.clear()
    for _ in range(2):
        chunk = _store_models.CodeChunk("point", "file.py", "python", "body", 1, 1)
        assert context.adopt_verified_vectors([chunk], sparse_required=True) == [False]
        assert chunk.vector == [], "failed donor transport must remain an encode miss"
    assert admission.transport.vector_calls == list(context.donor_collections) * 2
    assert len(admission.pointer_calls) == len(admission.proof_calls) == 3
    assert len(admission.transport.capability_calls) == 3
    assert stats.reuse_hits == 0 and stats.reuse_misses == 2


def test_missing_and_failed_evidence_consume_inspection_window(
    admission: _Admission,
) -> None:
    roots = [entry.root for entry in admission.entries.values()]
    admission.pointers[roots[0]] = None
    admission.pointers[roots[1]] = OSError("isolated pointer unavailable")
    admission.proofs[roots[2]] = None
    admission.proofs[roots[3]] = OSError("isolated proof unavailable")
    admission.transport.failures.add("d004_served")
    admission.transport.unsupported.add("d005_served")
    stats, context = admission.resolve()
    assert len(admission.pointer_calls) == 6, (
        "unreadable donors expanded inspection window"
    )
    assert admission.proof_calls == roots[2:6]
    assert admission.transport.capability_calls == ["d004_served", "d005_served"]
    assert context is None and stats is not None and stats.donor_absent


def test_filtering_and_family_newest_prefix_order_precede_pointer_io(
    admission: _Admission, monkeypatch: pytest.MonkeyPatch
) -> None:
    template = admission.entries["d000_"]
    admission.entries.clear()

    for prefix, root, stamp, backend, member in (
        ("own_", "target", "9999", "server", True),
        ("local_", "local", "9999", "local", True),
        ("wrong_", "wrong", "9999", "server", False),
        ("remote_", "far", "9999", "server", True),
        ("z_", "near-z", "2000", "server", True),
        ("a_", "near-a", "2000", "server", True),
        ("new_", "near-new", "2001", "server", True),
    ):
        entry = replace(
            template,
            prefix=prefix,
            root=str(admission.root.parent / root),
            backend=backend,
            last_indexed=stamp,
            collections=(
                ((prefix if backend == "server" else "") + "codebase_docs",)
                if member
                else ()
            ),
        )
        admission.entries[prefix] = entry
        admission.pointers[entry.root] = prefix + "served"

    def family(root: Path) -> Path | None:
        return None if root.name == "far" else Path("family")

    monkeypatch.setattr(candidates, "git_common_dir", family)
    found = list(
        candidates.iter_donor_candidates(admission.root, candidates.CollectionKind.CODE)
    )
    assert admission.entries["own_"].root not in admission.pointer_calls, (
        "own-root donor resolved a publication pointer"
    )
    assert admission.entries["local_"].root not in admission.pointer_calls, (
        "wrong-backend donor resolved a publication pointer"
    )
    assert admission.entries["wrong_"].root not in admission.pointer_calls, (
        "wrong-kind donor resolved a publication pointer"
    )
    assert [candidate.prefix for candidate in found] == ["new_", "a_", "z_"], (
        "donor filtering or family/newest/prefix ranking changed"
    )
    assert admission.pointer_calls == [candidate.root for candidate in found]


def test_disabled_reuse_and_failed_manifest_do_not_read_pointers(
    admission: _Admission, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        _settings, "get_config", lambda: SimpleNamespace(index_reuse_enabled=False)
    )
    assert admission.resolve() == (None, None)
    assert not admission.pointer_calls and not admission.proof_calls
    monkeypatch.setattr(
        _settings,
        "get_config",
        lambda: SimpleNamespace(
            index_reuse_enabled=True, effective_server_mode=lambda: True
        ),
    )

    def unreadable_manifest() -> dict[str, ManifestEntry]:
        raise OSError("isolated manifest unavailable")

    monkeypatch.setattr(storage_manifest, "load_manifest", unreadable_manifest)
    stats, context = admission.resolve()
    assert context is None and stats is not None and stats.donor_absent
    assert not admission.pointer_calls and not admission.proof_calls
