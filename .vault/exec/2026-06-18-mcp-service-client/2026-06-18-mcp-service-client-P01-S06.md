---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-18'
step_id: 'S06'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Repoint the CLI HTTP search module to re-export from the service-client package, preserving the CLI surface

## Scope

- `src/vaultspec_rag/cli/_http_search.py`

## Description

- Replace the CLI HTTP-search module body with re-exports of the moved transport surface from the service-client transport module, keeping its docstring describing the trinary contract.
- Re-export every name the CLI and its tests reference from this module path: the three client functions, the wire-call primitive, the connection-refused predicate, the logs-route builder, the search-timeout helper and constant, the timeout-diagnostics builder, and the three new wrappers.
- Declare the re-exported set in `__all__` so the static type checker treats the intentional private re-exports as the module's surface and no longer flags them.

## Outcome

- The CLI's existing imports and the tests that import these names from the HTTP-search module path keep working unchanged, with no behavior change for CLI callers.
- The CLI, routing, and ADR-regression unit tests stay green; the regression test that inspects the wire-call primitive's source still resolves it through the re-export.

## Notes

The CLI tests that stub the wire-call primitive were repointed to the transport module, the function's new home, so the behavioral assertions (refused -> None, live-but-broken -> structured error, timeout -> diagnostics) remain intact at the real call site.
