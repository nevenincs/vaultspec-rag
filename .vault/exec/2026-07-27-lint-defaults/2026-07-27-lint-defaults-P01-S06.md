---
tags:
  - '#exec'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S06'
related:
  - "[[2026-07-27-lint-defaults-plan]]"
---

# Remediate upstream-default complexity findings

## Scope

- `src/vaultspec_rag/_public_search.py`

## Description

- Introduce immutable document and combined-search request values.
- Migrate public exports and direct CLI, server, and integration callers.
- Verify the real indexed document path and focused type and lint checks.

## Outcome

The public search facade now owns each operation's cohesive request state without
wide internal signatures or a legacy compatibility path.

## Notes

The broader source files still contain separately planned complexity findings; this
step resolves only the public facade functions.
