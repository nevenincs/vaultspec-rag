---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:12b96a3a52a83a34c60024b7c8cbc83f89fbfd65546319fb8d8e80477e0f09ce'
step_id: 'S01'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Thread the lifecycle-derived active build target through clean-generation cleanup without rebinding the served collection before publication

## Scope

- `src/vaultspec_rag/indexer`

## Description

- Bind the lifecycle-derived build target to each opened generation.
- Replace the indexer's duplicate target cache with the lifecycle authority.
- Pass the active target explicitly to stale cleanup, preparation, ingestion, and publication.

## Changes

- `src/vaultspec_rag/indexer/_generation_lifecycle.py`: retain the active target for the open generation.
- `src/vaultspec_rag/indexer/_codebase_indexer.py`: consume that target for all clean-generation collection mutations.

## Outcome

Clean-generation cleanup now mutates the derived build collection while the served
collection remains unchanged until lifecycle publication.

## Notes

Verification passed: scoped Ruff format and lint checks, `ty`, strict basedpyright,
and `test_run_checkpoint.py` (25 passed).
