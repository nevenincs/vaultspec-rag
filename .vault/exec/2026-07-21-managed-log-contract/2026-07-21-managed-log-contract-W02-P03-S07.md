---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S07'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Filter source-tagged groups without merging or fabricating chronology

## Scope

- `src/vaultspec_rag/server/_routes_logs.py`

## Description

- Build source-tagged groups in deterministic service-then-Qdrant order.
- Apply bounded per-source filtering before the requested tail.
- Render one shared plaintext and JSON contract.

## Outcome

Filtering and presentation keep source identity explicit and never imply cross-source chronology.

## Notes

Filtered searches inspect at most 5,000 records per selected source.
