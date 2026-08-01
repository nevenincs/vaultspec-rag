---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-21'
body_hash: 'sha256:b7ef8f50dd15c05c4698975051f418d79fabdd187e2f8dad99c99870146f31a5'
step_id: 'S07'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Update \_resolve_preprocess_context to the two-state mode (no server_mode/unsandboxed plumbing)

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Simplify `_resolve_preprocess_context`: no `SERVICE_DAEMON` probe, no unsandboxed-mode derivation.

## Outcome

Context construction is mode-agnostic; `None` when no rules apply (zero-overhead path unchanged).

## Notes

None.
