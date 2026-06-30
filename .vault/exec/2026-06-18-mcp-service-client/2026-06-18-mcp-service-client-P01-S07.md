---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S07'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Repoint the CLI service-status discovery helpers to re-export from the service-client package

## Scope

- `src/vaultspec_rag/cli/_service_status.py`

## Description

- Delete the read-only discovery function bodies from the CLI service-status module (status-dir resolver, status-file resolver, status reader, default-port resolver) and re-export them from the service-client discovery module.
- Keep the status-writer surface in place: the status write, the token update, the metadata merge, and the lifecycle-shutdown log helper remain owned by this module.
- Move the standard-library path import into a type-checking block since, after the deletions, it is referenced only in the log-file helper's return annotation.

## Outcome

- The CLI's callers and tests that import the four discovery helpers from the service-status module path keep resolving them at the same import path through the re-export.
- The writer helpers continue to resolve the status directory and status file through the re-exported discovery helpers, so their behavior is unchanged.
- Linting and type checking are clean on the module.

## Notes

None.
