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
