"""The split fingerprint routes each delta to the outcome it deserves.

These are the classifier's own tests: what a body edit, a metadata edit, a
stamp bump, and a sidecar written under the previous scheme each classify as.
The end-to-end proof that the classification is *acted on* - zero encodes,
untouched vectors - lives with the guard tests over a real store; this file
pins the decision itself, where every branch is reachable without a GPU.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from vaultspec_core.config import (
    reset_config,
)

from ..config._settings import reset_config as reset_rag_config
from ..indexer._vault_fingerprint import (
    SCHEME,
    VaultDelta,
    classify,
    fingerprint_bytes,
    fingerprint_path,
    parse,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_BODY = "# a decision\n\nThe body that decides whether a vector is stale.\n"


def _document(
    *,
    modified: str = "2026-07-25",
    tags: str = "  - '#adr'\n  - '#sample'",
    body: str = _BODY,
) -> str:
    """Render a vault document with a controllable frontmatter and body."""
    return (
        "---\ntags:\n"
        f"{tags}\n"
        "date: '2026-07-25'\n"
        f"modified: '{modified}'\n"
        "related:\n  - '[[other-doc]]'\n"
        "---\n\n"
        f"{body}"
    )


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    """A workspace root with one ADR path the doc-type resolver recognises."""
    reset_config()
    reset_rag_config()
    (tmp_path / ".vaultspec").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vault" / "adr").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _sample_path(root: Path) -> Path:
    """The vault's canonical sample ADR path."""
    return root / ".vault" / "adr" / "2026-07-25-sample-adr.md"


def _fingerprint(root: Path, text: str) -> str:
    """Fingerprint *text* as the vault's canonical sample ADR."""
    return fingerprint_bytes(_sample_path(root), root, text.encode("utf-8"))


def _legacy_digest(data: bytes) -> str:
    """Digest bytes the way the pre-split scheme did, for migration tests."""
    return hashlib.blake2b(data).hexdigest()


class TestClassification:
    """Each delta class reaches the branch that costs what it should."""

    def test_a_stamp_bump_alone_is_unchanged(self, vault_root: Path) -> None:
        """The measured waste class: a stamp refresh over an identical body."""
        before = _fingerprint(vault_root, _document(modified="2026-07-25"))
        after = _fingerprint(vault_root, _document(modified="2026-07-29"))

        assert before != after, "the raw digest must still see the stamp move"
        assert classify(before, after) is VaultDelta.UNCHANGED

    def test_a_metadata_edit_is_a_metadata_delta(self, vault_root: Path) -> None:
        before = _fingerprint(vault_root, _document())
        after = _fingerprint(
            vault_root,
            _document(tags="  - '#adr'\n  - '#renamed'"),
        )

        assert classify(before, after) is VaultDelta.METADATA

    def test_a_body_edit_is_a_body_delta(self, vault_root: Path) -> None:
        before = _fingerprint(vault_root, _document())
        after = _fingerprint(
            vault_root,
            _document(body="# a decision\n\nAn entirely different body.\n"),
        )

        assert classify(before, after) is VaultDelta.BODY

    def test_a_byte_identical_document_is_unchanged(self, vault_root: Path) -> None:
        fingerprint = _fingerprint(vault_root, _document())

        assert classify(fingerprint, fingerprint) is VaultDelta.UNCHANGED

    def test_an_unseen_document_is_a_body_delta(self, vault_root: Path) -> None:
        """Nothing is stored for it, so everything about it is new."""
        assert classify(None, _fingerprint(vault_root, _document())) is VaultDelta.BODY

    def test_line_ending_churn_alone_is_unchanged(self, vault_root: Path) -> None:
        """A checkout that reflows line endings changes nothing embedded."""
        before = _fingerprint(vault_root, _document())
        after = _fingerprint(vault_root, _document().replace("\n", "\r\n"))

        assert classify(before, after) is VaultDelta.UNCHANGED

    def test_a_body_edit_wins_over_a_simultaneous_metadata_edit(
        self, vault_root: Path
    ) -> None:
        """Stale vectors are the more expensive error, so the body decides."""
        before = _fingerprint(vault_root, _document())
        after = _fingerprint(
            vault_root,
            _document(tags="  - '#adr'\n  - '#renamed'", body="new body\n"),
        )

        assert classify(before, after) is VaultDelta.BODY


class TestLegacySidecarMigration:
    """A sidecar written under the raw-digest scheme migrates, not re-embeds."""

    def test_unmoved_bytes_migrate_without_re_embedding(self, vault_root: Path) -> None:
        """The one-time cost must not be a full corpus of GPU time."""
        text = _document()
        current = _fingerprint(vault_root, text)
        legacy = parse(current)
        assert legacy is not None

        assert classify(legacy.raw, current) is VaultDelta.UNCHANGED

    def test_moved_bytes_re_embed_because_the_old_scheme_recorded_no_more(
        self, vault_root: Path
    ) -> None:
        legacy_raw = parse(_fingerprint(vault_root, _document()))
        assert legacy_raw is not None
        edited = _fingerprint(vault_root, _document(body="a different body\n"))

        assert classify(legacy_raw.raw, edited) is VaultDelta.BODY

    def test_the_raw_digest_matches_the_previous_scheme_byte_for_byte(
        self, vault_root: Path
    ) -> None:
        """The bridge is only a bridge if both sides digest the same thing.

        Mutation that drives this red: in ``fingerprint_bytes``, digest
        ``data.decode("utf-8").encode("utf-8")`` instead of ``data``. It stays
        green for LF files and fails here, on the CRLF case, because
        ``read_text`` would have folded the line endings away.
        """
        raw_bytes = _document().replace("\n", "\r\n").encode("utf-8")
        current = fingerprint_bytes(_sample_path(vault_root), vault_root, raw_bytes)
        parsed = parse(current)

        assert parsed is not None
        assert parsed.raw == _legacy_digest(raw_bytes)

    def test_a_crlf_document_migrates_without_re_embedding(
        self, vault_root: Path
    ) -> None:
        """A CRLF checkout must migrate as cheaply as an LF one.

        The repository pins the vault to LF, but a consumer with
        ``core.autocrlf=true`` checks out CRLF. If the raw digest disagreed with
        the previous scheme's there, the advertised cheap migration would become
        a full-corpus re-embed for exactly those users.
        """
        raw_bytes = _document().replace("\n", "\r\n").encode("utf-8")
        current = fingerprint_bytes(_sample_path(vault_root), vault_root, raw_bytes)

        assert classify(_legacy_digest(raw_bytes), current) is VaultDelta.UNCHANGED

    def test_a_stamp_bump_under_a_legacy_entry_still_re_embeds_once(
        self, vault_root: Path
    ) -> None:
        """Honest about the bound: the old scheme cannot tell what moved.

        This is the migration cost the ADR accepts, and pinning it keeps a
        later reader from mistaking it for a classification defect.
        """
        legacy = parse(_fingerprint(vault_root, _document(modified="2026-07-25")))
        assert legacy is not None
        bumped = _fingerprint(vault_root, _document(modified="2026-07-29"))

        assert classify(legacy.raw, bumped) is VaultDelta.BODY


class TestEncoding:
    """The sidecar value round-trips and announces its own scheme."""

    def test_a_fingerprint_round_trips(self, vault_root: Path) -> None:
        rendered = _fingerprint(vault_root, _document())
        parsed = parse(rendered)

        assert parsed is not None
        assert rendered.startswith(f"{SCHEME}|")
        assert parsed.raw and parsed.body and parsed.metadata

    def test_a_legacy_digest_is_recognised_as_not_ours(self) -> None:
        assert parse("a" * 128) is None

    def test_a_malformed_value_is_recognised_as_not_ours(self) -> None:
        assert parse(f"{SCHEME}|only|three") is None
        assert parse(f"{SCHEME}|raw||metadata") is None

    def test_an_unrecognised_path_falls_back_to_a_raw_digest(
        self, vault_root: Path
    ) -> None:
        """No doc type means no document, so there is no split to record."""
        rendered = fingerprint_bytes(
            vault_root / "README.md",
            vault_root,
            _document().encode("utf-8"),
        )

        assert parse(rendered) is None
        assert rendered == rendered.strip() and rendered


class TestUndecodableBytes:
    """One bad byte must not be able to wedge vault indexing."""

    def test_invalid_utf8_yields_a_raw_digest_instead_of_raising(
        self, vault_root: Path
    ) -> None:
        """Mutation that drives this red: in ``fingerprint_bytes``, decode
        without catching ``UnicodeDecodeError``. This test then fails with that
        exception rather than an assertion - which is the point, because in
        production it escapes the hashing phase, whose failure capture catches
        only ``OSError``, and aborts the entire indexing run.

        Every retry would abort identically while the file remained, so vault
        indexing would stay wedged until an operator located one byte. The
        previous raw-bytes digest could not fail this way: such a file hashed
        fine and was skipped, with a warning, at the parse phase.
        """
        latin1 = "caf\xe9".encode("latin-1")
        undecodable = _document(body=f"# a decision\n\n{latin1.decode('latin-1')}\n")
        data = undecodable.encode("utf-8").replace(b"caf\xc3\xa9", b"caf\xe9")
        assert b"caf\xe9" in data, "the fixture must actually be invalid UTF-8"

        rendered = fingerprint_bytes(_sample_path(vault_root), vault_root, data)

        assert rendered == _legacy_digest(data)
        assert parse(rendered) is None

    def test_an_undecodable_file_is_a_body_delta_not_a_silent_unchanged(
        self, vault_root: Path
    ) -> None:
        """It must never read as unchanged against a real split fingerprint.

        Falling back to a bare digest is safe only because a bare value forces
        raw-to-raw comparison. If it could compare equal to a split fingerprint,
        a file that became unreadable would look like nothing had happened.
        """
        readable = _fingerprint(vault_root, _document())
        data = _document().encode("utf-8").replace(b"decision", b"deci\xe9sion")
        broken = fingerprint_bytes(_sample_path(vault_root), vault_root, data)

        assert classify(readable, broken) is VaultDelta.BODY

    def test_reading_an_undecodable_file_from_disk_does_not_raise(
        self, vault_root: Path
    ) -> None:
        """The production entry point, over a real file, not just its bytes."""
        path = _sample_path(vault_root)
        path.write_bytes(_document().encode("utf-8").replace(b"body", b"b\xe9dy"))

        rendered = fingerprint_path(path, vault_root)

        assert rendered == _legacy_digest(path.read_bytes())
