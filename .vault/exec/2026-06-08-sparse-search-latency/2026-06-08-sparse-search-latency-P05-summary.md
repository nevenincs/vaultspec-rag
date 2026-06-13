---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-09'
modified: '2026-06-09'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` Phase P05 Summary

## Overview

Phase P05 finishes the MCP-business-logic elimination begun under the
`mcp-server-deconflation` plan: the `mcp/` package must be a pure protocol adapter that
translates MCP stdio/HTTP requests into REST calls to the daemon, with no direct imports
from `server`, `store`, `service`, or `registry`.

## Steps

- **S15** (commit `5b38c13`): replaced `_resources.py` direct Qdrant access
  (`_registry.lease(root)` + `slot.store.get_by_id()`) with a `/vault-document` REST call.
- **S16**: verified — no server-internal imports remain in `mcp/`; S15 already removed the
  last ones. Only a permitted `cli._service_status` peer import remains.
- **S17** (commit `cf249af`): added the `/vault-document` REST route to the daemon.
- **S18**: added `test_mcp_import_isolation.py`, a static AST guard enforcing the
  import-isolation invariant.

## Outcome

The `mcp/` package is import-isolated from daemon internals and the invariant is
machine-enforced. `ruff`/`ty` clean; guard test green.

## Notes

A small admin-tool cleanup rode along: `list_projects` dropped a misleading `project_root`
parameter (the `/projects` route ignores it; the documented tool contract is no-arg),
verified by the live-service integration tests.
