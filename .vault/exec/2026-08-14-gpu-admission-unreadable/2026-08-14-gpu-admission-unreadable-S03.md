---
tags:
  - '#exec'
  - '#gpu-admission-unreadable'
date: '2026-08-14'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:60e27741fb7b2bd4bb11f3a7418650299835e6fd2734d78c20ff0db815cbd4d3'
step_id: 'S03'
related:
  - "[[2026-08-14-gpu-admission-unreadable-plan]]"
---

# Repoint the fail-open guard and prove both directions of the new refusal

## Scope

- `src/vaultspec_rag/tests/test_gpu_admission.py`

## Description

- Repoint the guard that asserted the unconditional fail-open at the
  single-reading case it was actually right about, rather than keeping it
  alongside the new behaviour.
- Add guards for the refusal, the threshold boundary, the reason split
  against an absent device, and the remediation prose.
- Add guards for the ledger: accumulation, the reset on a reading that
  answers, and the non-reset on a reading that never reached the question.
- Add guards for the composition: that a supplied reading is judged by the
  ledger too, that the refusal reaches the loader, and that it does not
  latch.
- Settle the ledger at both test boundaries through the production reset
  path, alongside the existing latch clearing.

## Outcome

Eleven guards, each broken open one at a time, run alone, observed to fail
on the assertion its docstring names, restored, and observed to pass. Both
directions are covered: a guard set that only proved the refusal would
have passed just as well against a gate that refused every unreadable
reading, which is a different defect rather than a fix.

## Notes

Four docstrings named a mutation or an assertion other than the one that
actually fired - two claimed an assertion that a nearer one pre-empted,
two described a mutation adjacent to the one run. All four were corrected
to what was observed. An unverified mutation note is worse than none: the
next reader trusts it and loosens the matcher it describes.

The suite's fixture settles the streak by feeding the ledger a reading
that answers, rather than through a reset entry point added for tests. A
symbol kept alive only for tests would prove nothing about production, and
the reset path is itself under test.
