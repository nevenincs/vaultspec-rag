---
tags:
  - '#plan'
  - '#gpu-admission-unreadable'
date: '2026-08-14'
modified: '2026-08-14'
body_hash: 'sha256:2164ed80bcb7efe1d85a1cd67fbb9e10b9c1d4c5222d662855da7e56525125d5'
tier: L1
related:
  - '[[2026-08-14-gpu-admission-unreadable-adr]]'
  - '[[2026-07-29-gpu-admission-gate-adr]]'
  - '[[2026-08-14-gpu-admission-unreadable-reference]]'
---

# `gpu-admission-unreadable` plan

Close the load-admission fail-open that let a device answer presence and
nothing else while jobs kept being admitted onto it.

## Description

The governing decision fixed the admission predicate as free-against-floor
and never stated what an absent free figure means, leaving the unreadable
branch to an implementation comment. `2026-08-14-gpu-admission-unreadable-adr`
closes that gap: the branch keeps its fail-open for a single reading and
refuses once the readings become a run, counted rather than timed, and named
by its own reason so an operator is sent to the driver rather than to the
admission floor. `2026-07-29-gpu-admission-gate-adr` remains the record for
everything the gate does once a figure is in hand; nothing here re-litigates
the floor comparison, the latch, or the load window.

## Steps

- [x] `S01` - Give the gate a consecutive-unreadable ledger and refuse past its limit under a distinct reason; `src/vaultspec_rag/_gpu_admission.py`.
- [x] `S02` - Route the probed and the supplied reading through one judgement so neither bypasses the ledger; `src/vaultspec_rag/_gpu_admission.py, conftest.py`.
- [x] `S03` - Repoint the fail-open guard and prove both directions of the new refusal; `src/vaultspec_rag/tests/test_gpu_admission.py`.
- [x] `S04` - Assert the ledger coupling the audit found stated only in prose - that a diagnostic reading advances the streak a later load is refused on; `src/vaultspec_rag/tests/test_gpu_admission.py`.

## Parallelization

`S01` and `S02` both edit the gate and are sequential: the second routes both
observation paths into the judgement the first adds. `S03` follows both,
because a guard written against a half-wired ledger would pass on the
predicate rather than on the production composition.

## Verification

- The suite for the gate passes, and the fast lane passes whole.
- Each new guard has been broken open, run alone, and observed to fail on
  the assertion its docstring names, then restored and observed to pass -
  in both directions, since an admission guard that only ever admits proves
  nothing.
- Lint, format, type-check, and the module-size gate report clean over every
  file touched.
- No reading path reaches the judgement without passing through the ledger,
  asserted rather than reasoned about.
