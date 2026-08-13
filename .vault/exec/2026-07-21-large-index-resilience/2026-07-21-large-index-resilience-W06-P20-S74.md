---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:5a9e03fd7862151058b35b14f545a77f43646d8d9acfd515fd8fafffb667ea25'
step_id: 'S74'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Guard both halves - the gate against collected items, and the runner's two selections structurally

## Scope

- `src/vaultspec_rag/tests/test_marker_discipline.py`
- `src/vaultspec_rag/tests/test_adr_regression.py`

## Description

- Wrote four guards against the gate itself, reusing the existing collected-item stand-in rather than adding a second one.
- Covered the refusal, both correctly split lanes, the tier that holds no subprocess test, and the fast tier as a non-participant.
- Replaced the runner audit with a structural assertion - two selections, the first excluding the subprocess tier and the second naming only it - rather than a second model of the hazard that would have to stay correct alongside the gate.
- Proved every guard can fail: inverted the gate's condition, then merged the runner's two selections, then made the second selection name a resident tier as well.

## Outcome

Each mutation failed on the assertion its docstring names, and each was restored in the same sequence with the suite passing again. Inverting the gate's condition failed the split-lane guard specifically, which is the direction that matters: a gate requiring only the subprocess side would refuse the correct lane and admit the broken one.

## Notes

The runner audit was previously written against the expression-based helper, and it passed only because the recipe happened to spell out its exclusion. Under a corrected expression model the same audit would have failed on the performance selection - which is how the flaw in that model surfaced. The structural form checks what it always meant to check and cannot drift from the gate, because it no longer shares a model with it.
