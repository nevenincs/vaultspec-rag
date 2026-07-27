---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-27'
modified: '2026-07-27'
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
- Use each archive directory's completion stamp and account for all contained artifact bytes.
- Delete archive directories through the shared link-safe tree remover.
- Add filesystem regressions that retain a fresh manifest in an expired archive and verify byte-cap eviction never leaves a manifest behind.

## Outcome

The retention sweep now treats an archive as an indivisible restore unit. Its manifest and snapshot artifacts are kept or evicted together.

Focused validation passed: `TestSweepArchive` (3 passed), Ruff, Ty, and scoped whitespace validation. Independent review approved the scoped diff without blocking findings.

## Notes

The plan document already contains shared unstaged work, so its S03 state is changed through the CLI but deliberately excluded from this step commit.
