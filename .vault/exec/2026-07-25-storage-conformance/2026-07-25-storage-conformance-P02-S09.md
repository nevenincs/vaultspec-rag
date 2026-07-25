---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S09'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Report a model-identity disagreement at equal width as nonconforming without raising, leaving the collection readable

## Scope

- `src/vaultspec_rag/store.py`

## Description

## Outcome

A model disagreement at matching geometry records the verdict, logs a warning
naming the superseded model, and returns normally. `conformance_verdicts()`
exposes the recorded verdicts so the health surface can report without
re-probing the backend on every poll.

Not refusing is the deliberate half. The collection is readable and a rebuild is
the remedy, so refusing would remove search for precisely the duration of the
fix. A guard test asserts the ensure call does not raise, proven by widening the
raise to any nonconforming verdict and watching it fail.

## Notes
