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


class TestEncoding:
    """The sidecar value round-trips and announces its own scheme."""

    def test_a_fingerprint_round_trips(self, vault_root: Path) -> None:
        rendered = _fingerprint(vault_root, _document())
        parsed = parse(rendered)

        assert parsed is not None
        assert rendered.startswith(f"{SCHEME}|")
        assert parsed.raw and parsed.body and parsed.metadata

    def test_line_endings_reach_the_digest_unfolded(self, vault_root: Path) -> None:
        """The identity is taken over the file as stored, never a decoded copy.

        A consumer with ``core.autocrlf=true`` checks the vault out with CRLF
        while the repository stores LF. Those are different bytes on disk, and
        the recorded identity has to say so - a read that folds line endings
        makes two different files answer with one identity, which is a stale
        vector that never re-embeds.

        Driven through the production entry point, over real files, because
        the folding this guards against lives in how the file is READ, not in
        how the bytes are digested: decoding and re-encoding round-trips
        ``\r\n`` unchanged, so a test handing in its own bytes cannot see it.

        Mutation: ``fingerprint_path`` reading ``path.read_text()`` and
        encoding that, instead of ``path.read_bytes()``. Observed to make both
        identities equal and fail this on the inequality.
        """
        adr_dir = vault_root / ".vault" / "adr"
        lf_path = adr_dir / "2026-07-25-lf-adr.md"
        crlf_path = adr_dir / "2026-07-25-crlf-adr.md"
        lf_path.write_bytes(_document().encode("utf-8"))
        crlf_path.write_bytes(_document().replace("\n", "\r\n").encode("utf-8"))

        lf = parse(fingerprint_path(lf_path, vault_root))
        crlf = parse(fingerprint_path(crlf_path, vault_root))

        assert lf is not None and crlf is not None
        assert lf.raw != crlf.raw

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

        An undecodable file is the one case that still records a bare digest,
        and it is safe because the two values cannot be equal: only an
        identical recorded string is unchanged, and anything this scheme
        cannot read is a body rebuild. If a bare value could compare equal to
        a split fingerprint, a file that became unreadable would look like
        nothing had happened to it.
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
