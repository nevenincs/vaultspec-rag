---
tags:
  - '#exec'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S08'
related:
  - "[[2026-07-27-lint-defaults-plan]]"
---

# Remediate upstream-default complexity findings

## Scope

- `src/vaultspec_rag/_store_writes.py`

## Description

- Introduce an immutable terminal retry-exhaustion value.
- Route terminal retry logging through the cohesive value.
- Preserve the original attempt-exhaustion log message with focused coverage.

## Outcome

`_store_writes.py` meets the upstream argument-count default without changing
retry classification, retry timing, original-exception propagation, or terminal
operator diagnostics.

## Notes

The semantic search service was unavailable, so source grounding used the
project plan and targeted source/caller inspection. No data was modified.
