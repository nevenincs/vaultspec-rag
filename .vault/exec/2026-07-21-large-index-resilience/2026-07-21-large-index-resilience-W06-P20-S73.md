---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:9d3612849f19e260510db429b3b24eca56442224c0763cf65efdb5d29ee3522e'
step_id: 'S73'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Refuse a collected selection holding both device tiers, judged on items rather than on the marker expression

## Scope

- `conftest.py`
- `src/vaultspec_rag/tests/_tier_gate.py`

## Description

- Built the gate first against the marker expression, and proved it wrong: it probed one tier at a time, so it could not represent a test carrying two marks.
- Confirmed the consequence empirically - the expression model reported no hazard for the selection that actually wedges, and a hazard for a selection holding no subprocess test at all, which would have refused the performance lane.
- Rebuilt it to read the collected selection: subprocess-marked items on one side, resident-tier items that are not subprocess on the other, with the hazard being both sides non-empty.
- Placed it at collection finish, where the selection is final, rather than beside the existing tier gate, which needs the opposite half of collection.
- Removed the expression-based helper and the generality nothing used, leaving one model of the constraint.

## Outcome

Exercised against the real suite. The wedging selection is refused, naming 67 subprocess tests against 723 resident ones. Both halves of the split lane are allowed, as are the performance tier, the fast tier, and a run scoped to a single module by path. A test declaring both marks counts as subprocess, which is what it does; otherwise the subprocess lane would refuse itself and no split could pass.

## Notes

An earlier attempt at this gate was reverted for refusing ordinary path-scoped runs. Judging the items rather than the expression removes that failure mode rather than working around it: a path-scoped run is judged on what it actually collected, so it needs no exemption.

The declarations themselves are untouched. Sixty-seven tests still inherit a resident tier from a module default alongside their own subprocess mark, across sixteen modules. The gate makes that harmless, not correct; untangling it is separate work and was not folded in here.
