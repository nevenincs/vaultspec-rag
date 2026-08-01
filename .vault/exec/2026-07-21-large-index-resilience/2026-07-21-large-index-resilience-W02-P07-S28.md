---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:30f0fe5d3666e85292e4a80ced6d618a4751478ea9de8513194aac4d1fd19ce6'
step_id: 'S28'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Persist clean-rebuild destructive intent and resume incomplete replacement generations without a second drop

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Persist clean destructive intent in the generation before collection replacement.
- Classify interrupted destructive attempts as `rebuild_incomplete` without masking the original failure.
- Resume matching incomplete generations and skip the collection drop when storage-confirmed units already exist.
- Preserve the cache-lifecycle boundary independently from code collection replacement.

## Outcome

An interrupted clean code rebuild retains one durable generation and resumes its confirmed segments against the existing replacement collection. Recovery no longer repeats the destructive drop or restarts completed segment work.

## Notes

The real-store recovery test seeded production-segment identities, marked the clean generation incomplete, resumed through `full_index(clean=True)`, and verified the exact confirmed point set survived. Ruff and ty passed for the changed implementation and test.
