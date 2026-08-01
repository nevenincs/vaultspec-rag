---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
body_hash: 'sha256:ddd806a4b06719a2c4be8908352b6620821863ff43c9298a7f72948e68bff6a8'
step_id: 'S33'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Make native MCP intent writes transactional and generalize malformed-project diagnostics

## Scope

- `src/vaultspec_rag/commands/_install.py and real install transaction tests`

## Description

- Snapshot the optional dependency placement, ownership metadata, package mode,
  canonical MCP source, and every persistent lock before the first intent write.
- Roll back exact bytes and remove only transaction-created files and locks when
  placement, mode persistence, source seeding, removal, or repair fails.
- Classify every project read, decode, and parse failure as both an MCP failure
  and a torch-config error when torch configuration was requested.
- Exercise fresh and pre-existing lock state, fresh and existing source write
  blockers, invalid UTF-8, an unreadable project surface, and CLI failure exit.

## Outcome

Native MCP intent now commits as one guarded transition. The focused failure
matrix passes 10 tests, the complete install/mode/torch surface passes 191
tests, and Ruff, formatting, Ty, BasedPyright, complexity, lock consistency,
vault health, diff hygiene, and package builds pass.

## Notes

S32 remained a durable failed audit with three HIGH findings before this
remediation began. The exact segmented repository aggregate is intentionally
deferred to the fresh S34 review target.
