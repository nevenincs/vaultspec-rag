---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:d165cbea52133cb8d0049f701983d7fa1dec0cf486c1361f4fc56b8371a8041d'
step_id: 'S75'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Restore a clean type gate: declare the refused-envelope literal and drop suppressions that no longer suppress anything

## Scope

- `src/vaultspec_rag/tests/test_gpu_borrow_lease.py`
- `src/vaultspec_rag/indexer/_resolved_policy.py`
- `src/vaultspec_rag/commands/_models.py`

## Description

- Ran the type checker across the package and separated what this branch introduced from what predated it.
- Fixed the two real errors: a refused quiesce envelope bound to a name and handed to two guards in turn, where the same literal type-checks when passed inline.
- Removed five suppressions the checker itself reported as suppressing nothing, keeping the casts they were attached to.

## Outcome

Lint, format, and type all report clean across every file the branch touches. The edited guard still passes.

## Notes

The two errors are a mapping-invariance case, not a defect in the guards: an inline literal is inferred against the parameter it is passed to, while a named one is inferred on its own and must then be assignable. The test binds the envelope to a name precisely because its point is that both guards see one envelope.

The five stale directives predated this work and were carried as accepted noise. They were worth removing on their own terms: a gate that reports the same five findings on every run is a gate whose output gets skimmed, which costs more than the directives saved.
