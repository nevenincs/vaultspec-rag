---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:5b73e2bdce831f7c39816c5c5789a523cf2e5436a95d235d3aaccdeb304c4aa1'
step_id: 'S04'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Implement bounded raw-byte rotation and configure the Qdrant supervisor from the shared retention policy

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

- Add a secure append-only raw rotating sink for supervised child output.
- Rotate before writes, shift sparse numeric backups, prune stale generations, and support zero-backup truncation.
- Retain recent in-memory output when persistence fails.
- Keep a single-writer guard while an inherited pipe delays drain completion.

## Outcome

Qdrant output has finite independent retention without weakening supervisor diagnostics or writer exclusivity.

## Notes

Independent review found and closed a drain-lifecycle race and a cleanup escape before acceptance.
