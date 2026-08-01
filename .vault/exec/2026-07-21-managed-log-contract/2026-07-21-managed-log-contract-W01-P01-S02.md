---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:2c74ecc58c4c2a10fb40ba7ca0652eb2cd807b89ebdd3a5de66e256e13f75f51'
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
