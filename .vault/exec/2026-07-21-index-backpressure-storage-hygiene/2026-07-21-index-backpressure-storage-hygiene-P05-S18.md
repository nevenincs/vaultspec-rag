---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:e4b5829f99f0b31617299b4cfbd562d56b0eb09f55692ed6d38c4ed78b9c14e0'
step_id: 'S18'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add an operator-gated debris removal flag to server storage prune with structured idempotent outcomes

## Scope

- `src/vaultspec_rag/cli/`

## Description

`prune_debris` in the storage-ops domain removes unlisted collection dirs
by filesystem delete (Qdrant cannot load, snapshot, or drop them), gated
behind the new `server storage prune --debris` flag plus the existing
confirmation flow; dry-run previews, nothing-to-remove is a success, and
the JSON envelope gains a `debris` block.

## Outcome

Committed within the P05 storage commit; covered by the prune_debris
tests including the only-unlisted-dirs safety case.

## Notes

Debris has no manifest attribution, so automation never touches it - the
operator flag is the confirmation, matching manual-prune semantics.
