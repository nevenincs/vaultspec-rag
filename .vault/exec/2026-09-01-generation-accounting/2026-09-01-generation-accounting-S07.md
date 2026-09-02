---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:c36ae5d6e60b0e9a4da363a7cc766a441963b80222ae8fab82733bbc464c4d08'
step_id: 'S07'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Retire retained empty-source outcomes through the canonical storage-confirmed path

## Scope

- `src/vaultspec_rag/indexer/_consumer_pipeline.py`

## Description

- Route retained empty-source outcomes through the existing drift owner before recording the policy rejection.
- Preserve the pre-existing policy-rejection path when the current generation has no retained upsert evidence.
- Reuse the storage-confirmed retirement owner without adding a second cleanup implementation.

## Changes

- Call `retire_retained_outcome` from the empty-source handler with the same retained-policy disposition used by the skipped-source handler.

## Outcome

An empty source that replaces a current-generation upsert now deletes its retained points
and writes the corresponding durable deletion before its empty-source policy outcome is
recorded. Unevidenced empty sources retain their existing rejection behavior.

## Notes

Focused formatting, lint, strict type checking, and checkpoint tests pass. The focused
regression proof for retained empty sources is owned by the following test step.
