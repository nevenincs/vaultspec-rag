---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:7fb7cd4526e2a4ad98d7f41f299a47440bd2a0699a9502be5eba432b0bc7a2be'
step_id: 'S03'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# `P01.S03` whole archive eviction

## Scope

`src/vaultspec_rag/storage_reclamation.py`
`src/vaultspec_rag/tests/test_storage_ops.py`

## Description

- Replace file-by-file retention and byte-cap removal with whole completed archive-directory eviction.
- Parse each archive's persisted `snapshot-manifest.json` completion stamp and account for all contained artifact bytes.
- Delete archive directories through the shared link-safe tree remover.
- Add filesystem regressions that retain a fresh manifest in an expired archive, verify byte-cap eviction never leaves a manifest behind, and refuse to guess a missing stamp from an old copied-file mtime.

## Outcome

The retention sweep now treats an archive as an indivisible restore unit. Its manifest and snapshot artifacts are kept or evicted together.

Focused validation passed: `TestSweepArchive` (4 passed), Ruff, Ty, and scoped whitespace validation. Mutation proof temporarily restored directory-mtime selection; the missing-stamp guard failed because the legacy archive was deleted, and passed again after restoring the manifest-clock selection.

## Notes

The plan document already contains shared unstaged work, so its S03 state is reconciled through the CLI but deliberately excluded from this step commit. Malformed or legacy archives with no parseable completion stamp are retained rather than destructively guessed at.
