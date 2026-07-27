"""Reserved keys the vault hash-metadata sidecar carries, and the layout they mark.

The code side has had a home for its sidecar constants for a while, and the
document side has one too. The vault side did not: its keys lived as private
names inside the vault indexer, so the only way for a reader to use them was to
write the strings out again.

One reader did, and said so - "mirrors of the vault sidecar's reserved keys
(private to the vault indexer, which owns the write side)" - as did the test
covering it. The same function that carried the mirror imported the equivalent
code keys from the module that owns them, two lines apart, which is what makes
this a gap in the layout rather than a considered exception.

A mirror of a payload key is worse than a mirror of logic. A renamed key does
not fail: the reader's lookup returns ``None``, every vault donor falls to
ineligible, and reuse quietly stops happening. Nothing raises and no test for
correctness notices, because none of the answers are wrong - there are just
fewer of them.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "VAULT_CONTENT_EPOCH_KEY",
    "VAULT_POINT_SCHEMA",
    "VAULT_POINT_SCHEMA_KEY",
]

#: Version of the vault point layout. ``2`` stores one point per
#: heading-aware chunk (``doc_id#c{ordinal}``); ``1`` (or an absent marker over
#: a non-empty collection) stored one point per document. A mismatch triggers a
#: one-time clean rebuild so old-layout points never coexist with chunked ones.
VAULT_POINT_SCHEMA: Final = "2"

#: Reserved key carrying the layout version inside the hash-metadata sidecar.
#: Never collides with document ids, which are relative paths.
VAULT_POINT_SCHEMA_KEY: Final = "__vault_point_schema__"

#: Reserved key carrying the content epoch over ``vault_chunk_chars``. A
#: mismatch means the chunk boundary changed, so every document re-chunks with
#: unchanged bytes and the stored vectors are stale - the same drift class as
#: ``html_strip`` on the code side. Begins with ``__`` so the metadata loader
#: strips it from document-id set arithmetic.
VAULT_CONTENT_EPOCH_KEY: Final = "__vault_content_epoch__"
