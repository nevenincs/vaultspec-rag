---
tags:
  - '#exec'
  - '#watcher-targeted-reindex'
date: '2026-06-18'
modified: '2026-06-18'
step_id: 'S07'
related:
  - "[[2026-06-02-watcher-targeted-reindex-plan]]"
---

# Add a real-backend watcher regression test that deletes a tracked file during the cooldown window then leaves the tree quiet and asserts the chunks are evicted, plus a guard that an idle tick during an open cooldown does not trigger a premature reindex, folding in the reproduction scenarios and exercising the real backend with no mocks or skips

## Scope

- `src/vaultspec_rag/tests/integration/`

## Description

- Add a local-backend watcher regression test that primes the per-source
  cooldown with an unrelated edit, deletes a tracked file inside the cooldown
  window, then leaves the tree quiet and polls past cooldown plus the idle-tick
  interval, asserting the deleted file's chunks are evicted with no further
  filesystem event.
- Add a guard test that deletes a file inside a long cooldown window and asserts
  the chunks are still present partway through it, proving the idle tick does not
  bypass the cooldown.
- Add a server-backend test that drives the supervised real Qdrant server: index
  two files, delete one, run the scoped incremental reindex over the deleted
  path, and assert the chunks are evicted while the surviving file is untouched.
- Fold in the throwaway reproduction scenarios and delete the scratch file so the
  suite carries only the permanent regression coverage.

## Outcome

Three regression tests added and green against the real backends with no mocks
or skips. The local watcher eviction test confirms a deletion suppressed by the
cooldown is flushed on a quiet tree (the #192 fix). The idle-tick guard confirms
the cooldown is still honoured (no early reindex). The server-mode test confirms
the scoped delete is durable against the supervised real Qdrant engine. The
throwaway reproduction file was removed. Verified in isolation: the two watcher
tests pass together in about forty seconds, and the server-mode test in about
thirty.

## Notes

The first reproduction draft polled inside the cooldown window and so could not
observe the post-fix eviction (which lands at cooldown plus one tick); the
regression test deliberately polls past cooldown plus the idle-tick interval to
avoid that false negative. Tests use the real GPU and real backends with no
mocks or skips.
