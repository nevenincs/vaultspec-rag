---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S08'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Classify a volatile-stamp-only change as unchanged so it reaches neither the encoder nor the store

## Scope

- `src/vaultspec_rag/indexer/_vault_indexer.py`

## Description

- Return `VaultDelta.UNCHANGED` from `classify()` when both digests agree while
  the encoded values differ - which can only be the raw digest moving under an
  unchanged body and unchanged metadata.
- Leave such a document out of both work sets in `_classify_documents()`, so it
  reaches neither the encoder nor the store.
- Keep writing its refreshed fingerprint into the sidecar.

## Outcome

A `modified:` stamp bump now costs a stat, a parse, and two digests. It reaches
no GPU and performs no store write.

This required no exclusion rule. The stamp is absent from `VaultDocument`, so it
cannot enter the subset, and it is stripped from the body by the frontmatter
parse - it is invisible to both digests by construction, and the only thing that
can see it is the raw digest that no longer decides anything on its own.

Verified end to end by the guard in S12: six stamped documents,
`updated == 0`, `payload_updated == 0`, vectors unmoved.

## Notes

Unchanged is a classification, not a refusal to look. The sidecar still absorbs
the new value, or every later run would re-derive the same answer from the same
stale entry and the stat gate could never short-circuit it. A test asserts the
sidecar entry does change on a stamp bump, which is the one place where "nothing
happened" would have been the wrong outcome.
