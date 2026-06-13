---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'S47'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Resolve entry_point rules in the loader instead of rejecting them (D9 follow-up)

## Scope

- `src/vaultspec_rag/indexer/_preprocess_config.py`

## Description

Replaced the loader's `_resolve_command` (which rejected entry_point) with
`_resolve_invocation`, returning `(command, entry_point)` with exactly one set. An
`entry_point` must be a `"module:callable"` reference; malformed refs are dropped per the
D3 policy. Updated the now-stale "command-only / dropped in v1" docstrings.

## Outcome

`entry_point` rules now load and carry to the runner; malformed refs are dropped, valid
ones accepted (`test_entry_point_rule_loads`, `test_malformed_entry_point_is_dropped`).

## Notes

The worker cache token is command-or-entry_point so version-bump invalidation works for both.
