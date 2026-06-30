---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S14'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Create the storage CLI group and a survey command with bounded filters and json output

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

- Add the server storage Typer group and the read-only survey command (--orphaned/--unknown/--json), wired in \_app.py and cli/__init__.py.

## Outcome

Validated live against the real 84-namespace / 171 GB server; rendering split into helpers for the complexity gate. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.
