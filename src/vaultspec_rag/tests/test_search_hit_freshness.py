"""Delivered-hit freshness uses real files and fenced canonical evidence."""

from __future__ import annotations

import hashlib
import os
import sys
from contextlib import contextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Literal

import pytest

from .. import _search_freshness, store_schema
from .._publication_state import PublicationSnapshot
from .._search_freshness import (
    MAX_FILE_BYTES,
    capture_hit_publications,
    verify_search_hits,
)
from .._source_types import IndexSource, PublicSourceType
from ..config._settings import get_config
from ..indexer._publication_proof import ProofEvidence
from ..indexer._run_ledger_models import FETCH_BATCH, RunAuthority
from ..indexer._run_ledger_runtime import RunLedger
from ..indexer._vault_fingerprint import fingerprint_bytes
from ..indexer._vault_identity import vault_document_id, vault_relative_path
from ..search._models import DocumentSearchResult, SearchResult
from ..server._models import SearchResultItem
from ._run_ledger_test_support import (
    ledger_test_publish_and_compact,
    ledger_test_signature,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path
    from types import FrameType

pytestmark = pytest.mark.unit


def _published(
    root: Path, relative: str, data: bytes, source: IndexSource = "code"
) -> PublicationSnapshot:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    digest = (
        fingerprint_bytes(path, root, data)
        if source == "vault"
        else hashlib.blake2b(data).hexdigest()
    )
    proof_path = relative
    if source == "vault":
        docs_relative = vault_relative_path(path, root / get_config().docs_dir)
        assert docs_relative is not None
        proof_path = vault_document_id(docs_relative)
    ledger = RunLedger(root / "runs.sqlite3")
    signature = replace(
        ledger_test_signature(root),
        source_type=PublicSourceType(source),
        collection_identity={
            "code": store_schema.CODE_COLLECTION,
            "vault": store_schema.VAULT_COLLECTION,
            "document": store_schema.DOCUMENT_COLLECTION,
        }[source],
    )
    generation = ledger.start_generation(signature)
    ledger.establish_verified_publication(
        generation.generation_id,
        RunAuthority.REBUILD,
        (ProofEvidence(proof_path, digest, ("point-0",)),),
    )
    ledger_test_publish_and_compact(ledger, generation.generation_id)
    proof, token = ledger.acquire_current_publication_snapshot(
        source_type=signature.source_type,
        root_identity=signature.root_identity,
        backend_identity=signature.backend_identity,
    )
    return PublicationSnapshot(proof, ledger, token)


def _hit(path: str = "src/a.py") -> SearchResult:
    return SearchResult(
        "point-0",
        path,
        "a",
        0.9,
        "return 'old'",
        "codebase",
        line_start=1,
        line_end=1,
        rerank_text="return 'old'",
    )


def test_changed_file_marks_every_delivered_chunk_and_preserves_ranking(
    tmp_path: Path,
) -> None:
    snapshot = _published(tmp_path, "src/a.py", b"return 'old'\n")
    hits = [_hit(), replace(_hit(), id="point-1", score=0.3)]
    # The same size and mtime must not be mistaken for matching content.
    path = tmp_path / "src/a.py"
    observed = path.stat()
    path.write_bytes(b"return 'new'\n")
    os.utime(path, ns=(observed.st_atime_ns, observed.st_mtime_ns))
    drift = verify_search_hits(tmp_path, hits, {"code": snapshot})
    assert [(item.source, item.path, item.reason) for item in drift] == [
        ("code", "src/a.py", "content_changed")
    ]
    assert [hit.freshness for hit in hits] == ["stale", "stale"]
    assert [hit.score for hit in hits] == [0.9, 0.3]
    assert [hit.snippet for hit in hits] == ["return 'old'", "return 'old'"]
    assert SearchResultItem.serialize(hits[0])["stale_reason"] == "content_changed"


def test_unchanged_file_is_current_and_deleted_file_is_stale(tmp_path: Path) -> None:
    snapshot = _published(tmp_path, "src/a.py", b"return 'old'\n")
    hit = _hit()
    assert verify_search_hits(tmp_path, [hit], {"code": snapshot}) == ()
    assert hit.freshness == "current"
    (tmp_path / "src/a.py").unlink()
    drift = verify_search_hits(tmp_path, [hit], {"code": snapshot})
    assert len(drift) == 1
    assert hit.freshness == "stale"
    assert hit.stale_reason == "file_missing"


def test_file_edit_outside_the_shown_lines_still_marks_hit_stale(
    tmp_path: Path,
) -> None:
    snapshot = _published(tmp_path, "src/a.py", b"return 'old'\n# original\n")
    (tmp_path / "src/a.py").write_bytes(b"return 'old'\n# revised\n")
    hit = _hit()
    verify_search_hits(tmp_path, [hit], {"code": snapshot})
    assert hit.freshness == "stale"


def test_unknown_and_oversized_files_are_unverifiable(tmp_path: Path) -> None:
    hit = _hit()
    assert capture_hit_publications(tmp_path, ("code",)) == {}
    assert verify_search_hits(tmp_path, [hit], {}) == ()
    assert hit.freshness == "unverifiable"
    snapshot = _published(tmp_path, "src/a.py", b"x" * (MAX_FILE_BYTES + 1))
    verify_search_hits(tmp_path, [hit], {"code": snapshot})
    assert hit.freshness == "unverifiable"
    assert hit.stale_reason is None


def test_publication_race_invalidates_the_disk_check(tmp_path: Path) -> None:
    # Removing the post-read proof fence failed the drift assertion below;
    # restoring it passed. The failure log records the demonstrated mutation.
    snapshot = _published(tmp_path, "src/a.py", b"return 'old'\n")
    (tmp_path / "src/a.py").write_bytes(b"return 'new'\n")
    successor = snapshot.ledger.start_generation(
        replace(
            ledger_test_signature(tmp_path),
            collection_identity=store_schema.CODE_COLLECTION,
        )
    )
    snapshot.ledger.reserve_publication_receipt(
        snapshot.proof.compatibility_key,
        successor.generation_id,
        expected_parent_revision=snapshot.proof.revision,
    )
    hit = _hit()
    assert verify_search_hits(tmp_path, [hit], {"code": snapshot}) == ()
    assert hit.freshness == "unverifiable"


def test_vault_modified_stamp_is_ignored_but_body_drift_is_stale(
    tmp_path: Path,
) -> None:
    relative = ".vault/adr/example.md"
    data = (
        b"---\ntags: ['#adr', '#example']\nmodified: '2026-01-01'\n"
        b"---\n# Example\n\nOriginal.\n"
    )
    snapshot = _published(tmp_path, relative, data, "vault")
    hit = replace(_hit(relative), source="vault")
    (tmp_path / relative).write_bytes(data.replace(b"2026-01-01", b"2026-01-02"))
    verify_search_hits(tmp_path, [hit], {"vault": snapshot})
    assert hit.freshness == "current"
    (tmp_path / relative).write_bytes(data.replace(b"Original.", b"Revised."))
    verify_search_hits(tmp_path, [hit], {"vault": snapshot})
    assert hit.freshness == "stale"


def test_document_freshness_checks_original_binary_bytes(tmp_path: Path) -> None:
    snapshot = _published(tmp_path, "report.pdf", b"%PDF original", "document")
    hit = DocumentSearchResult("point-0", "report.pdf", "Report", 0.8, "extracted text")
    (tmp_path / "report.pdf").write_bytes(b"%PDF changed")
    verify_search_hits(tmp_path, [hit], {"document": snapshot})
    assert hit.freshness == "stale"
    assert hit.stale_reason == "content_changed"


def test_content_lookup_is_path_bounded_and_does_not_hydrate_point_lists(
    tmp_path: Path,
) -> None:
    snapshot = _published(tmp_path, "src/a.py", b"return 'old'\n")
    key = snapshot.proof.compatibility_key
    assert snapshot.ledger.publication_content_for_paths(
        key, ("src/a.py", "absent")
    ) == {"src/a.py": hashlib.blake2b(b"return 'old'\n").hexdigest()}
    with pytest.raises(ValueError, match="at most"):
        snapshot.ledger.publication_content_for_paths(
            key, ("src/a.py",) * (FETCH_BATCH + 1)
        )


@contextmanager
def _file_reads() -> Generator[list[FrameType]]:
    """Observe real reads; the result exposes no I/O-count diagnostic."""
    previous = sys.getprofile()
    reads: list[FrameType] = []

    def observe(
        frame: FrameType,
        event: Literal["call", "return", "c_call", "c_return", "c_exception"],
        arg: object,
    ) -> None:
        if previous is not None:
            previous(frame, event, arg)
        if event == "call" and frame.f_code is _search_freshness._read_file.__code__:
            reads.append(frame)

    sys.setprofile(observe)
    try:
        yield reads
    finally:
        sys.setprofile(previous)


def test_delivered_chunks_share_one_file_read(
    tmp_path: Path,
) -> None:
    snapshot = _published(tmp_path, "src/a.py", b"return 'old'\n")
    hits = [_hit(), replace(_hit(), id="point-1")]
    with _file_reads() as reads:
        verify_search_hits(tmp_path, hits, {"code": snapshot})
    assert [hit.freshness for hit in hits] == ["current", "current"]
    assert len(reads) == 1


def test_combined_domains_share_the_same_physical_file_read(
    tmp_path: Path,
) -> None:
    # Disabling the page cache failed the exact one-read assertion; restoring
    # the cache passed in the same run.
    data = b"return 'old'\n"
    code = _published(tmp_path, "shared.md", data)
    document = _published(tmp_path, "shared.md", data, "document")
    (tmp_path / "shared.md").write_bytes(b"return 'new'\n")
    hits: list[SearchResult | DocumentSearchResult] = [
        _hit("shared.md"),
        DocumentSearchResult("point-0", "shared.md", "Shared", 0.8, "old"),
    ]
    with _file_reads() as reads:
        verify_search_hits(tmp_path, hits, {"code": code, "document": document})
    assert [hit.freshness for hit in hits] == ["stale", "stale"]
    assert len(reads) == 1


def test_vault_and_code_share_physical_reads_with_distinct_proof_keys(
    tmp_path: Path,
) -> None:
    relative = ".vault/adr/shared.document.md"
    data = b"# Shared document\n\nOriginal.\n"
    code = _published(tmp_path, relative, data)
    vault = _published(tmp_path, relative, data, "vault")
    hits = [_hit(relative), replace(_hit(relative), source="vault", id="vault-point")]
    with _file_reads() as reads:
        verify_search_hits(tmp_path, hits, {"code": code, "vault": vault})
    assert [hit.freshness for hit in hits] == ["current", "current"]
    assert len(reads) == 1


def test_vault_outside_docs_root_cannot_borrow_a_basename_proof(
    tmp_path: Path,
) -> None:
    # Permitting basename fallback confirmed outside-root drift and failed the
    # empty-drift assertion; restoring strict containment passed in the same run.
    data = b"# Stored index\n\nOriginal.\n"
    snapshot = _published(tmp_path, ".vault/stored.index.md", data, "vault")
    outside = tmp_path / "elsewhere" / "stored.index.md"
    outside.parent.mkdir()
    outside.write_bytes(data)
    hit = replace(_hit("elsewhere/stored.index.md"), source="vault")
    assert verify_search_hits(tmp_path, [hit], {"vault": snapshot}) == ()
    assert hit.freshness == "unverifiable"


def test_missing_root_and_unsafe_paths_are_not_confirmed_drift(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    snapshot = _published(root, "src/a.py", b"return 'old'\n")
    unsafe = _hit("../outside.py")
    assert verify_search_hits(root, [unsafe], {"code": snapshot}) == ()
    assert unsafe.freshness == "unverifiable"
    # Keep the ledger alive while the source root itself is offline.
    root.rename(tmp_path / "offline")
    hit = _hit()
    verify_search_hits(root, [hit], {"code": snapshot})
    assert hit.freshness == "unverifiable"
