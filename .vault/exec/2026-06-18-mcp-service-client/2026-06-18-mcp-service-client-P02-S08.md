---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S08'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Rewrite the MCP search and index tools to delegate to the service-client, delete the duplicate daemon-call seam, route index-status to the service-state route, and map the unreachable return to one clear service-not-running error

## Scope

- `src/vaultspec_rag/mcp/_tools.py`

## Description

- Deleted the byte-for-byte duplicate daemon-call seam (`_call_daemon` and
  `_call_daemon_async`) and the local `_daemon_timeout_seconds` helper from the search and
  index tool module.
- Replaced the duplicate seam with three small private helpers that hold the no-fallback
  contract in exactly one place: `_require_port` resolves the running service port and
  raises the single service-not-running `RuntimeError` when no port is discovered;
  `_unwrap` maps the unreachable `None` sentinel a delegated client call returns to that
  same error; `_delegate` offloads a blocking synchronous client call onto a worker thread
  with `anyio.to_thread.run_sync` and applies `_unwrap`.
- Rewrote `search_vault` and `search_codebase` to delegate to the shared service-client
  search function, forwarding all vault and code filters plus the like/unlike rerank seed
  identifiers through one offloaded call.
- Rewrote `get_index_status` to read the live service-state route through the admin
  service-state delegation rather than the non-existent `/status` route.
- Rewrote `get_code_file`, `reindex_vault`, and `reindex_codebase` to delegate to the
  shared service-client code-file and reindex functions through the same offload and
  service-down path; preserved `get_code_file`'s content/error unwrapping.
- Extended the shared service-client search payload builder and search function to forward
  the like/unlike seed identifiers, because the daemon search route accepts them and the
  MCP search tools exposed them, but the extracted client did not yet carry them; both CLI
  and MCP now consume one search surface that supports them.

## Outcome

Importing the MCP package no longer pulls the heavy facade, the CLI module, or the store,
embeddings, and indexer modules; the import-isolation check reports clean. Every search and
index tool is now a thin delegation with no local machinery, and a search against an empty
status directory raises one clear service-not-running error. The targeted server,
import-isolation, and conflation-guard suites pass, and the broader transport-touching unit
suites stay green.

## Notes

The like/unlike seed identifiers were a real surface the extracted client had not yet
carried; rather than silently drop them from the MCP tools (a functional regression) or add
bespoke MCP-only payload assembly (forbidden), the shared client search function was
extended to forward them, keeping one search surface for both interfaces. The centralized
error message uses the standard "service is not running" phrasing the CLI already emits, so
it matches both the existing and the new not-running assertions.
