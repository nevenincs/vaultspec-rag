---
tags:
  - '#exec'
  - '#gpu-admission-unreadable'
date: '2026-08-14'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:ff06d25d490ddbcbdb10b24cc60e9c2e8c239f60c436f197f3d5e35e5ef38214'
step_id: 'S04'
related:
  - "[[2026-08-14-gpu-admission-unreadable-plan]]"
  - "[[2026-08-14-gpu-admission-unreadable-audit]]"
---

# Assert the ledger coupling the audit found stated only in prose - that a diagnostic reading advances the streak a later load is refused on

## Scope

- `src/vaultspec_rag/tests/test_gpu_admission.py`

## Description

- Add one guard driving both reading paths against the single ledger they
  share: the probed reading through the diagnostic entry point, the load
  through the real window on a real lock.
- Take one fewer diagnostic reading than the limit, attempt no load, then
  assert the first load attempted is refused - so what is pinned is the
  crossing, not either path's own accumulation.

## Outcome

One guard, broken open, run alone, observed to fail on the assertion its
docstring names, restored, and observed to pass. The mutation spared the
diagnostic path the ledger by judging its probed reading against the floor
alone - the shape a plausible later tidy-up would take, on the reasoning that
a read-only probe should not mutate state. Under it the load arrived as the
streak's first unreadable reading and was admitted as a hiccup, failing on
`DID NOT RAISE RuntimeError`. Restored, the suite stands at forty-two.

The verification clause the plan already carried - that no reading path
reaches the judgement without passing through the ledger - was asserted for
the supplied reading and true by construction for the probed one. It is now
asserted for both.

## Notes

The coupling this closes was not a defect but an unasserted relationship: the
tolerance limit and the cadence of whatever polls the verdict live in
different modules, and nothing stated that they compose into the real-time
window the limit spans. Prose in two records described it; no test would have
noticed it going away.

Run against a live production host, so the lane was held to this one suite -
whose window anchors at a temporary path and whose ledger is per-process, so
neither contends for the machine-global load window nor perturbs the running
daemon's own gate. The broader GPU and integration lanes were deliberately not
run for that reason, and this step's evidence should be read as covering the
gate suite alone.

One unrelated observation, recorded because it cost time and may recur: the
module-size gate failed once mid-session naming a source file that does not
exist, then passed on an unchanged tree. The tree carries orphaned bytecode
from an earlier test split, which is the obvious suspect and is not the proven
cause - the failure did not reproduce, and nothing was deleted to chase it.
