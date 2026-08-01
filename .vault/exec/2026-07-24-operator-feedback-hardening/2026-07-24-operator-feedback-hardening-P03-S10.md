---
tags:
  - '#exec'
  - '#operator-feedback-hardening'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:df9db8ef4f392aa9389619044ab7d99bebfc661a876451d1389a27f7b6d80e33'
step_id: 'S10'
related:
  - "[[2026-07-24-operator-feedback-hardening-plan]]"
---

# Route every operator-facing size through one byte vocabulary

## Scope

- `src/vaultspec_rag/_units.py`

## Description

- Establish one byte-rendering vocabulary and route every operator-facing size through it.
- Convert the remaining raw divisions on measured values to shared helpers, and fold the duplicated projection rule into one function.
- Correct the sizes that were rendered as container reprs, raw integers, or mislabelled units.

## Outcome

Sizes read in operator units across the status view, the refusals, and the job reports. A storage helper that divided by 1024 while labelling the result in decimal units had been understating every figure it printed.

## Notes

Mebibyte values carrying a decimal-unit suffix were corrected, which changes visible output and required updating assertions that pinned the old strings. The rule that a projection uses allocated rather than reserved memory had been living as two prose comments in separate modules with nothing binding them; it is now one function both call, guard-proofed by switching the projection to the reserved field and watching the assertion fail.
