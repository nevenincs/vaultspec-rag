---
tags:
  - '#exec'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:87dba1a034cdf8f969adab2c1e5cb9a8179d66a279507988469dd90378e78fac'
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
