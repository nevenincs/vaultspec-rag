---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S16'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

# Repair the test construction pattern that bypasses the indexer constructor, so a collaborator can be held as constructor state instead of rebuilt per access

## Scope

- `src/vaultspec_rag/tests/test_indexer_unit.py`

## Description

- Replace every constructor bypass in the indexer unit tests with real
  construction through a single scan-only helper.
- Repair the same pattern at the three sites outside the named scope that
  copied it, since one survivor is enough to keep the constraint in place.
- Capture the discovery collaborator at construction now that nothing depends
  on assembling an indexer attribute by attribute.

## Outcome

Fourteen sites in the unit tests, plus one each in the chunk-worker parity
tests, the preprocess batch tests, and the chunking benchmark, built an
indexer with `__new__` and then assigned a hand-picked subset of attributes.
That pattern is what forced the discovery collaborator to be rebuilt on every
access: a value captured in the constructor is simply absent on an object
whose constructor never ran, so the accessor had to reconstruct it from
`getattr` defaults each time.

All eighteen now construct for real, leaving only the embedding model and the
store unbound, which is honest because scanning and chunking touch neither.
The scan-only helper says so in its docstring, so the next reader knows which
two dependencies are deliberately absent rather than accidentally missing.

With that gone, the discovery accessor became constructor state and the
property disappeared. Discovery is now assembled once per indexer from the
same three inputs it always used, instead of once per call.

The step's scope named only the indexer unit tests. Repairing that file alone
would have left the pattern intact in three others and the constraint fully in
force, so the step would have delivered nothing. The extra three are the same
mechanical change.

Gates on the changed scope: lint clean, format clean, type check reports no
diagnostics, and the three affected suites pass at 151 tests.

## Notes

The chunk-worker parity and preprocess-batch helpers had docstrings
advertising the bypass as "the established unit-test pattern". Those were
rewritten rather than deleted, because an unexplained pair of unbound
dependencies invites the next reader to bind them.
