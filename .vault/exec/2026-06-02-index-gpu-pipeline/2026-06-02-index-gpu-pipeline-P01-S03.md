---
tags:
  - '#exec'
  - '#index-gpu-pipeline'
date: '2026-06-02'
modified: '2026-06-30'
body_hash: 'sha256:ea539d17096b0c1e00deaf5fa4ecd8383221319ace07cb432b88a891d6923a67'
step_id: 'S03'
related:
  - "[[2026-06-02-index-gpu-pipeline-plan]]"
---

# Preserve the serial byte-gate path and the BrokenProcessPool fallback as the single-threaded inline form under the two-thread structure

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Keep the serial byte-gate path and the BrokenProcessPool fallback as a single-threaded inline form.
- Route to the consumer-thread structure only on the parallel path.

## Outcome

The serial / fallback behaviour is unchanged; the two-thread structure exists only when the pool is used.

## Notes

A `_put` liveness check lets the producer detect a dead consumer instead of blocking on a full queue.
