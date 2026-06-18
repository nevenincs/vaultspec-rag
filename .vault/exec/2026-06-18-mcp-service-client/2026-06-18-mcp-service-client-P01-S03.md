---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-18'
step_id: 'S03'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Create the import-light service-discovery module housing the status-file reader and default-port resolver

## Scope

- `src/vaultspec_rag/serviceclient/_discovery.py`

## Description

- Move the read-only service-discovery helpers out of the CLI service-status module into the new discovery module: the status-directory resolver, the status-file resolver, the status-file reader, and the default-port resolver.
- Resolve the status directory through the lightweight config accessor, honoring the status-dir environment override exactly as before.
- Wire the default-port resolver to call the discovery module's own status reader directly, rather than the former indirection through the CLI package namespace.
- Leave the status-writer surface (status write, token update, metadata merge, lifecycle-shutdown log) in the CLI module untouched, since only the read/discovery helpers move.

## Outcome

- The discovery module imports only stdlib plus the lightweight config accessor; importing it pulls no heavy modules.
- The CLI service-status module re-exports these four names so its callers and tests keep resolving them at their original import path.
- The default-port resolver continues to return the running service's port, or None when the status file is absent or unparsable, preserving the exit-3 "service down" code path.

## Notes

The former default-port resolver read the status through the CLI package alias so a test rebind of the CLI-level status reader would be observed. No test rebinds that name, so the discovery module reads its own status helper directly; the two auto-delegation tests that stub the status read were repointed to the discovery module, which is now the real read site.
