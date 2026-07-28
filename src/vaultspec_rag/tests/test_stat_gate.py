"""Stat-evidence gate: reuse, refusal, and fail-toward-rehash semantics.

Reuse is proven without mocks by exploiting the one blindness the gate
accepts by design: rewriting a file's content while restoring its exact
``(size, mtime_ns)`` makes a genuine skip observable as the old hash coming
back, and a genuine rehash observable as the new hash.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import TYPE_CHECKING

import pytest

from ..indexer._stat_gate import (
    _RACY_WINDOW_NS,
    _SCHEMA_KEY,
    _SCHEMA_VERSION,
    StatEvidenceGate,
    sidecar_for,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _digest(payload: bytes) -> str:
    return hashlib.blake2b(payload).hexdigest()


def _backdate(path: Path, *, seconds: float = 60.0) -> None:
    """Age *path* past the racy window so its evidence is trustworthy."""
    stat = path.stat()
    aged = stat.st_mtime - seconds
    os.utime(path, (aged, aged))


def _swap_content_same_stat(path: Path, payload: bytes) -> None:
    """Replace content while restoring the exact prior ``(size, mtime_ns)``."""
    before = path.stat()
    if len(payload) != before.st_size:
        raise AssertionError("replacement payload must preserve the size")
    path.write_bytes(payload)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


def test_trusted_evidence_answers_from_stat_alone(tmp_path: Path) -> None:
    source = tmp_path / "mod.py"
    source.write_bytes(b"x = 1\n")
    _backdate(source)
    sidecar = tmp_path / "gate.json"

    first = StatEvidenceGate.load(sidecar)
    original = first.hash_file("mod.py", source)
    assert original == _digest(b"x = 1\n")
    assert (first.reused, first.rehashed) == (0, 1)
    first.persist()

    # Same size, same mtime_ns, different bytes: a reuse returns the recorded
    # hash, which is the observable proof the file was not read again.
    _swap_content_same_stat(source, b"x = 2\n")
    second = StatEvidenceGate.load(sidecar)
    assert second.hash_file("mod.py", source) == original
    assert (second.reused, second.rehashed) == (1, 0)


def test_stat_visible_change_rehashes(tmp_path: Path) -> None:
    source = tmp_path / "mod.py"
    source.write_bytes(b"x = 1\n")
    _backdate(source)
    sidecar = tmp_path / "gate.json"

    first = StatEvidenceGate.load(sidecar)
    first.hash_file("mod.py", source)
    first.persist()

    source.write_bytes(b"x = 22\n")
    _backdate(source, seconds=30.0)
    second = StatEvidenceGate.load(sidecar)
    assert second.hash_file("mod.py", source) == _digest(b"x = 22\n")
    assert (second.reused, second.rehashed) == (0, 1)


def test_racy_evidence_is_never_trusted(tmp_path: Path) -> None:
    """A file hashed inside the racy window of its own mtime is rehashed."""
    source = tmp_path / "mod.py"
    source.write_bytes(b"x = 1\n")
    # No backdating: the recorded mtime sits within _RACY_WINDOW_NS of the
    # hashing instant, so the entry must never satisfy the gate.
    sidecar = tmp_path / "gate.json"

    first = StatEvidenceGate.load(sidecar)
    first.hash_file("mod.py", source)
    first.persist()

    _swap_content_same_stat(source, b"x = 2\n")
    second = StatEvidenceGate.load(sidecar)
    # A rehash returns the new digest; a (wrongly) trusted entry would have
    # returned the old one.
    assert second.hash_file("mod.py", source) == _digest(b"x = 2\n")
    assert (second.reused, second.rehashed) == (0, 1)


def test_corrupt_sidecar_degrades_to_rehash(tmp_path: Path) -> None:
    source = tmp_path / "mod.py"
    source.write_bytes(b"x = 1\n")
    _backdate(source)
    sidecar = tmp_path / "gate.json"
    sidecar.write_text("{not json", encoding="utf-8")

    gate = StatEvidenceGate.load(sidecar)
    assert gate.hash_file("mod.py", source) == _digest(b"x = 1\n")
    assert (gate.reused, gate.rehashed) == (0, 1)
    gate.persist()
    assert json.loads(sidecar.read_text(encoding="utf-8"))[_SCHEMA_KEY] == (
        _SCHEMA_VERSION
    )


def _seed_trusted_sidecar(tmp_path: Path) -> tuple[Path, Path]:
    """Record trustworthy evidence for one file and return (source, sidecar)."""
    source = tmp_path / "mod.py"
    source.write_bytes(b"x = 1\n")
    _backdate(source)
    sidecar = tmp_path / "gate.json"
    seed = StatEvidenceGate.load(sidecar)
    seed.hash_file("mod.py", source)
    seed.persist()
    return source, sidecar


@pytest.mark.parametrize(
    "defective_row",
    [
        # Row is not a four-element list.
        [6, 1, "aa"],
        # Booleans satisfy isinstance(int) but are a shape defect.
        [True, 1, "aa", 5_000_000_000],
        # Empty hash.
        [6, 1, "", 5_000_000_000],
        # Negative size.
        [-1, 1, "aa", 5_000_000_000],
        # Non-list row.
        "not-a-row",
    ],
)
def test_defective_sidecar_rows_discard_the_whole_cache(
    tmp_path: Path,
    defective_row: object,
) -> None:
    """One defective row poisons the file; nothing in it may be salvaged."""
    source, sidecar = _seed_trusted_sidecar(tmp_path)
    raw = json.loads(sidecar.read_text(encoding="utf-8"))
    raw["defect.py"] = defective_row
    sidecar.write_text(json.dumps(raw), encoding="utf-8")
    _swap_content_same_stat(source, b"x = 2\n")

    gate = StatEvidenceGate.load(sidecar)
    # A validator that skipped the defective row and salvaged the rest would
    # reuse mod.py's recorded hash here; the whole-file discard makes the
    # swapped bytes visible instead.
    assert gate.hash_file("mod.py", source) == _digest(b"x = 2\n")
    assert (gate.reused, gate.rehashed) == (0, 1)


def test_unknown_schema_version_discards_the_whole_cache(tmp_path: Path) -> None:
    source, sidecar = _seed_trusted_sidecar(tmp_path)
    raw = json.loads(sidecar.read_text(encoding="utf-8"))
    raw[_SCHEMA_KEY] = "0"
    sidecar.write_text(json.dumps(raw), encoding="utf-8")
    _swap_content_same_stat(source, b"x = 2\n")

    gate = StatEvidenceGate.load(sidecar)
    # A loader that ignored the version marker would reuse mod.py's recorded
    # hash; the discard makes the swapped bytes visible instead.
    assert gate.hash_file("mod.py", source) == _digest(b"x = 2\n")


def test_prune_drops_only_absent_keys(tmp_path: Path) -> None:
    kept = tmp_path / "kept.py"
    kept.write_bytes(b"x = 1\n")
    gone = tmp_path / "gone.py"
    gone.write_bytes(b"x = 2\n")
    for path in (kept, gone):
        _backdate(path)
    sidecar = tmp_path / "gate.json"

    first = StatEvidenceGate.load(sidecar)
    first.hash_file("kept.py", kept)
    first.hash_file("gone.py", gone)
    first.prune({"kept.py"})
    first.persist()

    raw = json.loads(sidecar.read_text(encoding="utf-8"))
    assert "kept.py" in raw
    assert "gone.py" not in raw


def test_unwritable_sidecar_never_raises(tmp_path: Path) -> None:
    source = tmp_path / "mod.py"
    source.write_bytes(b"x = 1\n")
    _backdate(source)
    sidecar = tmp_path / "gate.json"
    sidecar.mkdir()

    gate = StatEvidenceGate.load(sidecar)
    assert gate.hash_file("mod.py", source) == _digest(b"x = 1\n")
    # Advisory persistence: the replace onto a directory fails inside and is
    # swallowed with a warning; the run must not fail.
    gate.persist()
    assert sidecar.is_dir()


def test_missing_file_raises_oserror_like_the_ungated_path(tmp_path: Path) -> None:
    gate = StatEvidenceGate.load(tmp_path / "gate.json")
    with pytest.raises(OSError):
        gate.hash_file("gone.py", tmp_path / "gone.py")
    assert (gate.reused, gate.rehashed) == (0, 0)


def test_clean_gate_does_not_touch_disk(tmp_path: Path) -> None:
    sidecar = tmp_path / "gate.json"
    gate = StatEvidenceGate.load(sidecar)
    gate.persist()
    assert not sidecar.exists()


def test_racy_window_covers_coarse_filesystem_timestamps() -> None:
    assert _RACY_WINDOW_NS >= 2_000_000_000


def test_sidecar_name_derives_from_meta_path(tmp_path: Path) -> None:
    meta = tmp_path / "code_index_meta.json"
    assert sidecar_for(meta) == tmp_path / "code_index_meta.json.statgate.json"


class TestCodebaseIndexerGateWiring:
    """The indexer's hashing loop answers warm unchanged files from stat."""

    def test_hash_changed_paths_reuses_and_prunes(self, tmp_path: Path) -> None:
        from typing import Any, cast

        from ..indexer import CodebaseIndexer
        from ..progress import NullProgressReporter

        source = tmp_path / "mod.py"
        source.write_bytes(b"x = 1\n")
        _backdate(source)
        removed = tmp_path / "removed.py"
        removed.write_bytes(b"x = 2\n")
        _backdate(removed)

        indexer = CodebaseIndexer(tmp_path, cast("Any", None), cast("Any", None))
        reporter = NullProgressReporter()
        first = indexer._hash_changed_paths(
            {"mod.py": source, "removed.py": removed},
            reporter,
            full_membership=True,
        )
        assert first == {
            "mod.py": _digest(b"x = 1\n"),
            "removed.py": _digest(b"x = 2\n"),
        }
        sidecar = indexer._stat_gate_path
        assert sidecar.exists()

        # Warm pass over an unchanged stat identity returns the recorded hash
        # even though the bytes differ - the observable proof of a skip.
        _swap_content_same_stat(source, b"x = 9\n")
        removed.unlink()
        second = indexer._hash_changed_paths(
            {"mod.py": source},
            reporter,
            full_membership=True,
        )
        assert second == {"mod.py": _digest(b"x = 1\n")}
        raw = json.loads(sidecar.read_text(encoding="utf-8"))
        assert "removed.py" not in raw


class TestDocumentIndexerGateWiring:
    """Unscoped document selection answers warm unchanged files from stat."""

    def test_unscoped_selection_reuses_recorded_hashes(
        self,
        tmp_path: Path,
    ) -> None:
        from typing import Any, cast

        from ..indexer._document_indexer import DocumentIndexer
        from ..indexer._document_meta import DocumentFileMetadata

        doc = tmp_path / "guide.md"
        doc.write_bytes(b"# guide\n")
        _backdate(doc)
        indexer = DocumentIndexer(tmp_path, cast("Any", None), cast("Any", None))
        previous = {
            "guide.md": DocumentFileMetadata(
                source_path="guide.md",
                content_fingerprint=_digest(b"# guide\n"),
                point_ids=("p1",),
            )
        }

        first = indexer._select_incremental_paths(
            (doc,),
            previous,
            scoped=False,
        )
        assert first == set()
        assert indexer._stat_gate_path.exists()

        # Content differs but the stat identity matches the recorded
        # evidence: a stat-answered pass still reports the file unchanged,
        # which is the observable proof the gate answered without reading.
        _swap_content_same_stat(doc, b"# edits\n")
        second = indexer._select_incremental_paths(
            (doc,),
            previous,
            scoped=False,
        )
        assert second == set()

        # A stat-visible change is selected for reindexing.
        doc.write_bytes(b"# newer guide\n")
        _backdate(doc, seconds=30.0)
        third = indexer._select_incremental_paths(
            (doc,),
            previous,
            scoped=False,
        )
        assert third == {"guide.md"}


class TestVaultIndexerGateWiring:
    """Vault document hashing answers warm unchanged files from stat."""

    def test_hash_documents_reuses_and_prunes(self, tmp_path: Path) -> None:
        from typing import Any, cast

        from ..indexer._vault_indexer import VaultIndexer
        from ..progress import NullProgressReporter

        doc = tmp_path / "note.md"
        doc.write_bytes(b"# note\n")
        _backdate(doc)
        gone = tmp_path / "gone.md"
        gone.write_bytes(b"# gone\n")
        _backdate(gone)
        indexer = VaultIndexer(tmp_path, cast("Any", None), cast("Any", None))
        reporter = NullProgressReporter()

        first = indexer._hash_documents(
            {"note": doc, "gone": gone},
            reporter,
            full_membership=True,
        )
        assert first == {
            "note": _digest(b"# note\n"),
            "gone": _digest(b"# gone\n"),
        }

        _swap_content_same_stat(doc, b"# edit\n")
        gone.unlink()
        second = indexer._hash_documents(
            {"note": doc},
            reporter,
            full_membership=True,
        )
        assert second == {"note": _digest(b"# note\n")}
        raw = json.loads(indexer._stat_gate_path.read_text(encoding="utf-8"))
        assert "gone" not in raw
