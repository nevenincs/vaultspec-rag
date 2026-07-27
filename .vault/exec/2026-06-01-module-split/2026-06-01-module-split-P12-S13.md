---
tags:
  - '#exec'
  - '#module-split'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S13'
related:
  - "[[2026-06-01-module-split-plan]]"
---

# Decompose storage-operation responsibilities and migrate all direct importers

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

Move the storage lifecycle responsibilities from the former monolith into
concrete reclamation, migration, manifest, reconciliation, and survey owners.
Update production and test consumers to import their direct owner rather than
retaining a compatibility facade.

Verify the boundary with a repository import scan, focused local-Qdrant
storage tests, scoped formatting, lint, and type checks, then obtain an
independent safety and ownership review.

## Outcome

The former storage-operations facade is absent and no direct importer remains.
The resulting modules preserve service authority while giving each storage
operation a concrete owner. The focused storage suite passed 143 tests, and
the independent review found no high- or critical-severity safety, import, or
ownership issue.

## Notes

The shared worktree contains unrelated changes, including trailing whitespace
in a different archive plan. That unrelated condition was deliberately not
modified or used to qualify this step's scoped verification.
