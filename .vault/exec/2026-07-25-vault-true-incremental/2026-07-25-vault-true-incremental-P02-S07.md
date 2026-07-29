---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S07'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Route a subset-only delta to a payload-only upsert that rebuilds the document's payloads and leaves its vectors untouched

## Scope

- `src/vaultspec_rag/indexer/_vault_indexer.py`

## Description

- Add `overwrite_vault_chunk_payloads()` to `src/vaultspec_rag/store_ingest.py`,
  writing through the same payload builder the upsert uses and under the same
  disk-headroom check, point lock, and bounded retry.
- Add `_plan_payload_refresh()` and `_apply_payload_refresh()` to the vault
  indexer, under their own progress phases.
- Check the planned chunk count against the stored count per document, and defer
  any disagreement back into the re-embed branch before encoding begins.
- Wire the branch into both the full-scan and the scoped incremental paths, and
  report its size as `IndexResult.payload_updated`.

## Outcome

A metadata-only edit rebuilds the document's payloads and leaves its vectors
exactly where they were - proven byte-identical by the guard in S13, not merely
asserted here.

Payloads are overwritten rather than merged. A merge would strand a field that
has since been removed from the payload shape in the store forever, invisible to
every later write; the payload has to end up as though it had just been built,
because that is the claim indexing makes about it.

Sharing the payload builder with the upsert is what makes the two writes
incapable of disagreeing.

## Notes

The arity check is the load-bearing safety property. A payload-only write assumes
the store holds exactly the points this document produces; when the stored count
disagrees, the store is not in the shape the classification described, so the
document is re-embedded outright instead. The check runs before encoding so a
deferred document still joins that batch rather than being discovered too late.

A document that fails to parse is deferred the same way rather than silently
dropped.

The write is one call per chunk, because each chunk carries a different payload.
For a whole-corpus metadata refresh that is one local call per point - still
orders of magnitude below the encode it replaces, but not free, and worth knowing
if a future corpus is much larger.

The reported `payload_updated` figure initially carried the chunk count rather
than the document count. It read correctly for every single-chunk document,
which is most of them, and the guards in P04 all used such documents - so
nothing caught it. The repeated-statement-run scan did, indirectly: extracting
the shared reconcile phase it flagged forced both call sites onto one return
value and exposed the two numbers as different. The plan now returns the
document count explicitly, and a guard over a six-chunk document pins it,
proven red-then-green by restoring the chunk count and watching it fail with
`reported 6 documents for one document of 6 chunks`.

The reconcile phase is shared by the full-scan and scoped paths rather than
copied. The two differ only in how they reach a classification; what a
classification costs must not depend on which caller produced it, or a fix
applied to one path and missed on the other makes watcher-driven edits behave
differently from operator-driven ones.

The arity check was originally read from the stored chunk count, which is the
highest ordinal plus one rather than a census of the points that exist. A
document missing an interior ordinal therefore reported the same number as a
whole one, passed the check, and took the payload branch - where the write
addresses points by assumed ordinal, reaches nothing for the missing one, and
raises nothing. The sidecar then recorded the new fingerprint, so every later
run classified it unchanged and the stale payload had no path back. Verified
against a real store before fixing: with ordinals 0 and 2 present, the count
reading still returned 3 and the overwrite of ordinal 1 silently no-opped.

The check now reads the exact stored ordinal set and requires it to equal the
set the document splits into, deferring anything else to the re-embed branch,
and defers everything if the read itself fails. That also closes two cases the
count reading admitted: a pre-chunking point, which counts as one and passes for
a single-chunk document while no ordinal-keyed write can address it, and a
document carrying extra points beyond its chunk count.

The set reading and the count reading are derived from one scan, so the tail
purge keeps the max-plus-one answer it needs while this branch gets the census
it needs.

The payload write is now handed to the store one document at a time. It issues a
call per point, so a whole-corpus refresh is thousands of sequential round
trips; as one call it was uncancellable and reported no progress until it
finished. A document is the safe granularity - its payloads land together, so
cancelling between documents never leaves one half-refreshed.
