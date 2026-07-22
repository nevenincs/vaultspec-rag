---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S02'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Install the service log handler from the generic managed-log settings

## Scope

- `src/vaultspec_rag/server/_main.py`

## Description

- Configure the daemon rotating handler from the generic managed-log settings.
- Preserve the existing active service log path and secure handler behavior.

## Outcome

The service writer is bounded by the same independently applied policy as the Qdrant writer.

## Notes

None.
