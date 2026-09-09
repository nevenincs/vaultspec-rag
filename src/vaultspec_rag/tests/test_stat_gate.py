"""Stat-evidence gate: reuse, refusal, and fail-toward-rehash semantics.

Reuse is proven without mocks by exploiting the one blindness the gate
accepts by design: rewriting a file's content while restoring its exact
``(size, mtime_ns)`` makes a genuine skip observable as the old hash coming
back, and a genuine rehash observable as the new hash.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from typing import TYPE_CHECKING

import pytest

from ..indexer._stat_gate import (
    _RACY_WINDOW_NS,
    StatEvidenceGate,
    hash_paths,
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
    sidecar = tmp_path / "gate.sqlite3"

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

    with sqlite3.connect(sidecar) as connection:
        rows = connection.execute("SELECT path FROM stat_evidence").fetchall()
    assert rows == [("kept.py",)]


def test_missing_file_raises_oserror_like_the_ungated_path(tmp_path: Path) -> None:
    gate = StatEvidenceGate.load(tmp_path / "gate.json")
    with pytest.raises(OSError):
        gate.hash_file("gone.py", tmp_path / "gone.py")
    assert (gate.reused, gate.rehashed) == (0, 0)


def test_racy_window_covers_coarse_filesystem_timestamps() -> None:
    assert _RACY_WINDOW_NS >= 2_000_000_000


class _CountingReporter:
    """Real reporter that records every advance batch it receives."""

    def __init__(self) -> None:
        self.batches: list[int] = []

    def phase_start(self, name: str, total: int | None) -> None:
        del name, total

    def advance(self, n: int = 1) -> None:
        self.batches.append(n)

    def phase_end(self) -> None:
        return None

    def log(self, message: str) -> None:
        del message

    def forward_started(self, *, ordinal: int, items: int) -> None:
        del ordinal, items

    def forward_finished(self, *, ordinal: int, items: int) -> None:
        del ordinal, items


class TestBatchHashing:
    """The batched loop matches the serial gate file for file."""

    def test_batch_matches_serial_in_input_order(self, tmp_path: Path) -> None:
        payloads = {f"f{i}.py": f"x = {i}\n".encode() for i in range(20)}
        items: list[tuple[str, Path]] = []
        for rel, payload in payloads.items():
            path = tmp_path / rel
            path.write_bytes(payload)
            _backdate(path)
            items.append((rel, path))

        gate = StatEvidenceGate.load(tmp_path / "gate.json")
        outcome = hash_paths(gate, items)
        assert not outcome.failures
        assert outcome.hashes == {
            rel: _digest(payload) for rel, payload in payloads.items()
        }
        # Input order survives the reuse/rehash split inside the batch.
        assert list(outcome.hashes) == [rel for rel, _ in items]

        # A warm pass answers every file from stat and keeps the order.
        warm = hash_paths(gate, items)
        assert warm.hashes == outcome.hashes
        assert (gate.reused, gate.rehashed) == (20, 20)

    def test_failures_skip_without_aborting_and_ticks_stay_exact(
        self,
        tmp_path: Path,
    ) -> None:
        good = tmp_path / "good.py"
        good.write_bytes(b"x = 1\n")
        _backdate(good)
        gone = tmp_path / "gone.py"

        gate = StatEvidenceGate.load(tmp_path / "gate.json")
        reporter = _CountingReporter()
        outcome = hash_paths(
            gate,
            [("gone.py", gone), ("good.py", good)],
            reporter=reporter,
        )
        assert outcome.hashes == {"good.py": _digest(b"x = 1\n")}
        assert [key for key, _ in outcome.failures] == ["gone.py"]
        assert isinstance(outcome.failures[0][1], OSError)
        # Final totals are exact however the ticks were batched.
        assert sum(reporter.batches) == 2

    def test_pool_engages_on_large_files_with_identical_results(
        self,
        tmp_path: Path,
    ) -> None:
        # Mean size clears the pool threshold, so this exercises the pooled
        # read path against the serial gate as ground truth.
        payloads = {f"big{i}.bin": bytes([i]) * (64 * 1024) for i in range(12)}
        items: list[tuple[str, Path]] = []
        for rel, payload in payloads.items():
            path = tmp_path / rel
            path.write_bytes(payload)
            _backdate(path)
            items.append((rel, path))

        serial_gate = StatEvidenceGate.load(tmp_path / "serial.json")
        serial = {rel: serial_gate.hash_file(rel, path) for rel, path in items}
        pooled_gate = StatEvidenceGate.load(tmp_path / "pooled.json")
        pooled = hash_paths(pooled_gate, items)
        assert pooled.hashes == serial
        assert pooled_gate.rehashed == 12

        # The pooled pass recorded evidence: rewriting content behind an
        # unchanged stat identity is answered with the recorded hash.
        first = items[0]
        _swap_content_same_stat(first[1], bytes([255]) * (64 * 1024))
        warm = hash_paths(pooled_gate, [first])
        assert warm.hashes[first[0]] == serial[first[0]]


class TestRecordKnownHash:
    """Externally computed hashes are banked only when honestly bindable."""

    def test_backdated_identity_is_recorded_and_reused(self, tmp_path: Path) -> None:
        source = tmp_path / "mod.py"
        source.write_bytes(b"x = 1\n")
        _backdate(source)
        gate = StatEvidenceGate.load(tmp_path / "gate.json")

        recorded = gate.record_known_hash(
            "mod.py",
            source,
            _digest(b"x = 1\n"),
            computed_not_before_ns=time.time_ns(),
        )
        assert recorded
        # The banked evidence answers the next pass from stat alone: content
        # swapped behind the same identity comes back as the recorded hash.
        _swap_content_same_stat(source, b"x = 2\n")
        assert gate.hash_file("mod.py", source) == _digest(b"x = 1\n")
        assert (gate.reused, gate.rehashed) == (1, 0)

    def test_fresh_mtime_is_never_bound(self, tmp_path: Path) -> None:
        source = tmp_path / "mod.py"
        source.write_bytes(b"x = 1\n")
        # No backdating: the mtime sits inside the racy window of the claimed
        # computation instant, so the binding must be refused - a recorder
        # that skipped the window check would return True here and the swap
        # below would surface the stale hash as a reuse.
        gate = StatEvidenceGate.load(tmp_path / "gate.json")
        recorded = gate.record_known_hash(
            "mod.py",
            source,
            _digest(b"x = 1\n"),
            computed_not_before_ns=time.time_ns(),
        )
        assert not recorded
        _swap_content_same_stat(source, b"x = 2\n")
        assert gate.hash_file("mod.py", source) == _digest(b"x = 2\n")
        assert (gate.reused, gate.rehashed) == (0, 1)

    def test_missing_file_is_skipped(self, tmp_path: Path) -> None:
        gate = StatEvidenceGate.load(tmp_path / "gate.json")
        assert not gate.record_known_hash(
            "gone.py",
            tmp_path / "gone.py",
            "aa",
            computed_not_before_ns=time.time_ns(),
        )


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
        with sqlite3.connect(sidecar) as connection:
            rows = connection.execute("SELECT path FROM stat_evidence").fetchall()
        assert rows == [("mod.py",)]


class TestDocumentIndexerGateWiring:
    """Unscoped document selection answers warm unchanged files from stat."""


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
        with sqlite3.connect(indexer._stat_gate_path) as connection:
            rows = connection.execute("SELECT path FROM stat_evidence").fetchall()
        assert rows == [("note",)]
