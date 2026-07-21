---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S13'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Update in-process CLI contract coverage for source selection and local post-crash reads

## Scope

- `src/vaultspec_rag/tests/test_cli_server.py`

## Description

- Verify source selection, grouped plaintext, JSON, filtering, and strict live payload handling.
- Verify real-file offline reads when no service is running.
- Verify the removed raw flag is rejected.

## Outcome

The CLI contract is covered in process for both live and post-crash operator paths.

## Notes

The complete CLI server module passes with 37 tests.
