---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:e9f7891b6348cb5a3cff5de609ee11bc8f5a800b72f4dc78fd73febd4d02b441'
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
