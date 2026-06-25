---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S03'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add a vault-side twin test deleting a vault document, running the scoped incremental index, and asserting document eviction and search absence in server mode

## Scope

- `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`

## Description

Investigated whether the vault-side delete-eviction twin was a genuine gap or already
shipped. Found it shipped: `test_scoped_delete_evicts_vault_doc_in_server_mode` builds a
synthetic vault, full-indexes it, deletes one vault document, runs the scoped incremental
index over the deleted path, and asserts the removal reduced the stored count in server
mode. The watcher-driven twin in the same module additionally asserts the deleted vault
document drops out of a real hybrid search while a kept sibling still surfaces.

## Outcome

The step is genuinely shipped, not a gap. The vault-side eviction is covered by both a
direct scoped-reindex assertion and an end-to-end watcher assertion, each in server mode
against the real managed server. No new test was needed.

## Notes

No code changes; verify-and-tick of work delivered through pull request 196. The direct
assertion lives in `TestServerModeDeletionEviction` and the watcher twin in
`TestServerModeWatcherEviction`.
