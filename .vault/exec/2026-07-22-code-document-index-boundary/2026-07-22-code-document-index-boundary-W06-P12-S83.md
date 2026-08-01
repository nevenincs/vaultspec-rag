---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:46a3e61125c37d8255afb215c8bd61b28c4f72c11a31eaa760ec4197ed0ff448'
step_id: 'S83'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify multi-segment code and document restarts replay only the final unconfirmed unit in each kind

## Scope

- `src/vaultspec_rag/tests/integration/test_content_kind_restart.py`

## Description

- Open independent code and document generations in the shared production ledger.
- Interrupt both after all but their final storage-confirmed unit.
- Reopen compatible checkpoints and assert each kind selects only its own final unit.

## Outcome

Code and document restart evidence remains collection- and kind-local. Confirmed
units are not replayed, while each final unconfirmed unit is selected exactly
once and can be durably completed.

## Notes

Scoped Ruff and Ty checks passed. The production-checkpoint integration test
passed on the CPU boundary.
