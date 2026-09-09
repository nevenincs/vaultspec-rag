"""What invalidates a vault vector, and what merely invalidates a payload.

Vault change detection used to digest the raw file. That conflates two facts
the rest of the pipeline already keeps apart: the frontmatter parses into point
payloads, and only the body is ever embedded. Because the CLI refreshes a
``modified:`` stamp on every mutating vault verb, a raw-file digest flips on a
byte-identical body and the document is re-encoded on the GPU for no semantic
change at all.

The fingerprint here splits along the seam the chunk layer already uses. Each
document yields a body digest over exactly the text that gets embedded, and a
metadata digest over exactly the frontmatter-derived subset that enters
payloads - which lives beside the payload builders, not here, so the two can
never drift apart. A delta in the body means re-chunk and re-embed. A delta in
the metadata alone means rebuild payloads and leave the vectors where they
are. Neither means the run does nothing.

The raw digest is carried alongside both and taken over the file's bytes exactly
as stored. It is the byte-identity fast path; the body and metadata halves retain
enough information to classify a changed current-format identity without reading
unchanged files or rebuilding a corpus-wide manifest.
"""

from __future__ import annotations

import enum
import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .._store_models import vault_metadata_digest
from ._vault_prep import vault_document_from_text

if TYPE_CHECKING:
    import pathlib

logger = logging.getLogger(__name__)

__all__ = [
    "VaultDelta",
    "VaultFingerprint",
    "classify",
    "encode",
    "fingerprint_bytes",
    "fingerprint_path",
    "parse",
]

#: Scheme tag leading every canonical vault content identity.
SCHEME: Final = "v2"

#: Field separator. Absent from hex digests and from the scheme tag, so a
#: fingerprint always splits into exactly its parts.
_SEPARATOR: Final = "|"

#: Digest width for the body half, in bytes. Thirty-two hex characters is far
#: past the collision headroom any single vault can consume, and keeps the
#: per-document evidence row compact.
_BODY_DIGEST_BYTES: Final = 16


class VaultDelta(enum.Enum):
    """What changed about a document since it was last indexed."""

    #: Neither digest moved. The cheapest correct outcome: no encode, no
    #: store write, no payload rebuild.
    UNCHANGED = "unchanged"
    #: Only the indexed-frontmatter subset moved. The stored vectors are still
    #: correct for this body, so payloads are rebuilt and vectors untouched.
    METADATA = "metadata"
    #: The body moved, so the vectors no longer describe the document and it
    #: must be re-chunked and re-embedded.
    BODY = "body"


@dataclass(frozen=True, slots=True)
class VaultFingerprint:
    """One document's raw, body, and indexed-metadata digests."""

    raw: str
    body: str
    metadata: str


def encode(fingerprint: VaultFingerprint) -> str:
    """Render *fingerprint* as one canonical content identity."""
    return _SEPARATOR.join(
        (SCHEME, fingerprint.raw, fingerprint.body, fingerprint.metadata)
    )


def parse(stored: str) -> VaultFingerprint | None:
    """Parse a current vault content identity, or reject a malformed value."""
    parts = stored.split(_SEPARATOR)
    if len(parts) != 4 or parts[0] != SCHEME:
        return None
    _scheme, raw, body, metadata = parts
    if not (raw and body and metadata):
        return None
    return VaultFingerprint(raw=raw, body=body, metadata=metadata)


def fingerprint_bytes(
    path: pathlib.Path,
    root_dir: pathlib.Path,
    data: bytes,
) -> str:
    """Fingerprint one vault document from the bytes read off disk.

    The raw digest is taken over those bytes exactly as stored, never over a
    decoded-and-re-encoded copy.

    The body digest covers ``VaultDocument.content`` - the exact string the
    chunker splits and the encoder embeds, already stripped by the shared
    parse - so a body delta and a stale-vector condition are the same event by
    construction. Line endings are normalised there instead, where they belong:
    a checkout that rewrites them changes no character the embedder sees.

    Two cases yield the bare raw digest rather than a split fingerprint, and
    both are documents this indexer does not store:

    - a path with no recognised doc type, which has no document to describe;
    - bytes that are not valid UTF-8, which no parse can read.

    Neither may raise. Indexing skips such files with a warning at the parse
    phase, and it did so before this fingerprint existed; raising here instead
    would abort the whole run on one bad byte, and keep aborting it on every
    retry until an operator found the file.
    """
    raw = hashlib.blake2b(data).hexdigest()
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        logger.debug(
            "%s is not valid UTF-8; fingerprinting its bytes alone. Indexing "
            "skips it at the parse phase, as it always has",
            path,
        )
        return raw
    doc = vault_document_from_text(path, root_dir, content)
    if doc is None:
        return raw
    normalized = doc.content.replace("\r\n", "\n").replace("\r", "\n")
    body = hashlib.blake2b(
        normalized.encode("utf-8"),
        digest_size=_BODY_DIGEST_BYTES,
    ).hexdigest()
    return encode(
        VaultFingerprint(raw=raw, body=body, metadata=vault_metadata_digest(doc))
    )


def fingerprint_path(path: pathlib.Path, root_dir: pathlib.Path) -> str:
    """Read *path* and fingerprint it.

    Raises:
        OSError: The file could not be read, exactly as the raw-digest read it
            replaces would have raised, and the only failure this can produce.
            The caller reports it per file rather than aborting its batch.
    """
    return fingerprint_bytes(path, root_dir, path.read_bytes())


def _raw_of(value: str) -> str:
    """Return the raw digest a recorded identity carries, whatever its shape."""
    parsed = parse(value)
    return parsed.raw if parsed is not None else value


def classify(stored: str | None, current: str) -> VaultDelta:
    """Decide what work *current* demands given canonical prior evidence.

    A document the proof has never seen is :attr:`VaultDelta.BODY`: nothing
    is stored for it, so everything about it is new.

    A value that carries no split is compared as a bare digest. That is the
    recorded identity for a path with no recognised doc type, which has no
    front matter to separate from a body, so the digest is all either side
    has. Equal digests mean the bytes never moved and nothing needs doing;
    unequal means they did, and with no split recorded the safe answer is a
    body rebuild.
    """
    if stored is None:
        return VaultDelta.BODY
    if stored == current:
        return VaultDelta.UNCHANGED
    now = parse(current)
    before = parse(stored)
    if now is None or before is None:
        return (
            VaultDelta.UNCHANGED
            if _raw_of(stored) == _raw_of(current)
            else VaultDelta.BODY
        )
    if before.body != now.body:
        return VaultDelta.BODY
    if before.metadata != now.metadata:
        return VaultDelta.METADATA
    # Both digests agree while the encoded strings differ, which can only be
    # the raw digest moving under an unchanged body and unchanged metadata -
    # a pure ``modified:`` stamp refresh, or canonicalisation churn the
    # digests are built to absorb. Exactly the class this module exists for.
    return VaultDelta.UNCHANGED
