---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S03'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# Mirror the content epoch over vault_chunk_chars beside _needs_layout_rebuild with clean-rebuild escalation and epoch stamping on successful writes

## Scope

- `src/vaultspec_rag/indexer/_vault_indexer.py`

## Description

- Add a reserved vault content-epoch key beside the existing point-layout
  marker, double-underscore prefixed so `_load_meta` strips it from document-id
  set arithmetic.
- Add a helper that computes the content epoch over the current
  `vault_chunk_chars`, and a `_needs_content_rebuild` check that compares it
  against the stored value.
- Escalate a content-epoch mismatch to a clean rebuild inside the locked
  incremental, checked right after the existing layout-rebuild sentinel and
  before scoped dispatch.
- Stamp the content epoch on every successful metadata write, computed fresh at
  write time.

## Outcome

Changing the vault chunk boundary now re-chunks every document with unchanged
bytes on the next incremental entry, closing the same content-drift gap the code
side closes for `html_strip`. The vault chunking and targeted-reindex GPU
integration suites pass, including the layout-rebuild regression that rewrites
the sidecar without the layout marker - the extra content-epoch key does not
disturb it.

## Notes

The content epoch is computed fresh at each write rather than cached on the
instance, because a long-lived per-root indexer in the resident service could
otherwise stamp a stale value after a config reload and fail to converge. A
sidecar predating this key is not force-rebuilt: the epoch is simply stamped on
the next successful write, so an existing install is not clean-rebuilt merely
for upgrading, and a genuine later chunk-boundary change is then caught
precisely.
