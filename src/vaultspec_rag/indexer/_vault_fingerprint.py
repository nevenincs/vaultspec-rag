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

The raw digest is carried alongside both, taken over the file's bytes exactly
as stored. It is the byte-identity fast path, and it is the bridge to sidecars
written under the old scheme: a stored bare digest is compared against it, so a
corpus whose bytes have not moved since the last run under the old scheme
migrates by re-labelling rather than by re-embedding. It must be over the true
bytes for that comparison to mean anything - the old scheme digested bytes, so
digesting a decoded-and-re-encoded copy instead would disagree for every file
whose line endings the checkout translated, and spend a full corpus of GPU time
once, which is precisely the cost this module exists to stop paying.
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

#: Scheme tag leading every fingerprint this module writes. A sidecar entry
#: without it was written by the raw-digest scheme, which is a fact worth
#: recognising rather than misreading - see :func:`parse`.
SCHEME: Final = "v2"

#: Field separator. Absent from hex digests and from the scheme tag, so a
#: fingerprint always splits into exactly its parts.
_SEPARATOR: Final = "|"

#: Digest width for the body half, in bytes. Thirty-two hex characters is far
#: past the collision headroom any single vault can consume, and keeps the
#: per-document sidecar entry short.
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
    """Render *fingerprint* as the single string the sidecar stores.

    One string rather than a nested object because the sidecar is a flat
    ``{document id: digest}`` map that reserved ``__``-prefixed keys already
    share; widening its value type would break every reader of it for a shape
    that carries no more information than this one does.
    """
    return _SEPARATOR.join(
        (SCHEME, fingerprint.raw, fingerprint.body, fingerprint.metadata)
    )


def parse(stored: str) -> VaultFingerprint | None:
    """Parse a sidecar value, or return ``None`` when it is not one of ours.

    ``None`` is the honest answer for a bare raw digest written by the previous
    scheme and for anything malformed. Both are handled the same way by
    :func:`classify`, which falls back to comparing raw digests - the only
    comparison a legacy entry can support.
    """
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
    decoded-and-re-encoded copy. That is what makes it comparable to a sidecar
    entry written under the previous scheme, which digested the file's bytes:
    re-encoding would silently disagree for any file whose line endings the
    checkout translated, and the cheap migration would degrade to a re-embed of
    every such document.

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


def classify(stored: str | None, current: str) -> VaultDelta:
    """Decide what work *current* demands given what the sidecar holds.

    A document the sidecar has never seen is :attr:`VaultDelta.BODY`: nothing
    is stored for it, so everything about it is new.

    A stored entry from the previous raw-digest scheme can only be compared
    raw-to-raw. Equal means the bytes never moved, so nothing about the
    document moved either and the entry migrates to the new scheme by being
    rewritten - no encode, no payload rebuild. Unequal means the bytes moved
    but the old scheme recorded nothing about *how*, so the safe answer is
    :attr:`VaultDelta.BODY`. That is the one-time migration cost, and it is
    bounded by the documents actually edited since the last run rather than by
    the corpus.

    A current value that is itself unparseable belongs to a path with no
    recognised doc type. It is compared as a raw digest for the same reason.
    """
    if stored is None:
        return VaultDelta.BODY
    if stored == current:
        return VaultDelta.UNCHANGED
    now = parse(current)
    before = parse(stored)
    if now is None or before is None:
        # One side predates the scheme (or has no document behind it); the raw
        # digest is the only field both sides are known to share.
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


def _raw_of(value: str) -> str:
    """Return the raw digest a sidecar value carries, whatever its scheme."""
    parsed = parse(value)
    return parsed.raw if parsed is not None else value
