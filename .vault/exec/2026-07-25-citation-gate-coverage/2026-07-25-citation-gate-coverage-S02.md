---
tags:
  - '#exec'
  - '#citation-gate-coverage'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S02'
related:
  - "[[2026-07-25-citation-gate-coverage-plan]]"
---

# Sweep the tree for citations the widened gate reaches and repair the prose around each removal

## Scope

- `tools/profile_vault_index.py`

## Description

- Run the widened gate over the package in report-only mode and confirm no new
  citation surfaced there.
- Sweep the tooling surface, which the gate had never citation-scanned, and find
  one live audit-finding pointer in the vault-index profiler.
- Delete the pointer and read the surrounding prose in the diff.

## Outcome

One citation removed. The pointer was a trailing sentence appended to a comment
whose preceding sentences already stated the constraint in full - why the result
is pre-bound, and which failure it prevents - so the constraint survives the
deletion and the comment still parses. No sentence was left stranded, because
the pointer was not the grammatical object of any clause that remained.

The package itself swept clean under the widened pattern. The one instance the
issue reported had already been removed from the worker docstring by earlier
work; the gate hole it exposed had not.

## Notes

Fifty-nine generic absolute-path smells remain reported and non-failing. They
are synthetic values, not identity leaks, and converting them to temp paths is a
separate backlog this sweep deliberately did not touch.
