---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S06'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Replace the legacy service-only reader with bounded source-aware grouped log retrieval

## Scope

- `src/vaultspec_rag/logging_config.py`

## Description

- Replace the service-only reader with source-aware managed-log retrieval.
- Discover sparse numeric generations and reverse-read bounded blocks.
- Preserve independent per-source limits, order, and empty groups.

## Outcome

Operators can retrieve bounded service, Qdrant, or grouped all-source records without whole-file loading.

## Notes

Read and rollover races degrade to the available records instead of fabricating data.
