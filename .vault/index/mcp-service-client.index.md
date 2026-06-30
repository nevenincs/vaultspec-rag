---
generated: true
tags:
  - '#index'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-30'
related:
  - '[[2026-06-18-mcp-service-client-P01-S01]]'
  - '[[2026-06-18-mcp-service-client-P01-S02]]'
  - '[[2026-06-18-mcp-service-client-P01-S03]]'
  - '[[2026-06-18-mcp-service-client-P01-S04]]'
  - '[[2026-06-18-mcp-service-client-P01-S05]]'
  - '[[2026-06-18-mcp-service-client-P01-S06]]'
  - '[[2026-06-18-mcp-service-client-P01-S07]]'
  - '[[2026-06-18-mcp-service-client-P02-S08]]'
  - '[[2026-06-18-mcp-service-client-P02-S09]]'
  - '[[2026-06-18-mcp-service-client-P02-S10]]'
  - '[[2026-06-18-mcp-service-client-P03-S11]]'
  - '[[2026-06-18-mcp-service-client-P03-S12]]'
  - '[[2026-06-18-mcp-service-client-P04-S13]]'
  - '[[2026-06-18-mcp-service-client-P04-S14]]'
  - '[[2026-06-18-mcp-service-client-P04-S15]]'
  - '[[2026-06-18-mcp-service-client-P04-S16]]'
  - '[[2026-06-18-mcp-service-client-P05-S17]]'
  - '[[2026-06-18-mcp-service-client-P05-S18]]'
  - '[[2026-06-18-mcp-service-client-P05-S19]]'
  - '[[2026-06-18-mcp-service-client-P06-S20]]'
  - '[[2026-06-18-mcp-service-client-P06-S21]]'
  - '[[2026-06-18-mcp-service-client-adr]]'
  - '[[2026-06-18-mcp-service-client-audit]]'
  - '[[2026-06-18-mcp-service-client-plan]]'
  - '[[2026-06-18-mcp-service-client-research]]'
---

# `mcp-service-client` feature index

Auto-generated index of all documents tagged with `#mcp-service-client`.

## Documents

### adr

- `2026-06-18-mcp-service-client-adr` - `mcp-service-client` adr: `MCP backend reframed as a thin service client` | (**status:** `accepted`)

### audit

- `2026-06-18-mcp-service-client-audit` - `mcp-service-client` audit: `MCP service-client rework code review`

### exec

- `2026-06-18-mcp-service-client-P01-S01` - Convert the top-level package init to lazy attribute loading so importing any submodule no longer eager-loads the heavy facade
- `2026-06-18-mcp-service-client-P01-S02` - Create the import-light service-client transport housing the HTTP call primitive and the search, reindex, and admin client functions
- `2026-06-18-mcp-service-client-P01-S03` - Create the import-light service-discovery module housing the status-file reader and default-port resolver
- `2026-06-18-mcp-service-client-P01-S04` - Add thin client wrappers for benchmark, quality, and code-file so the MCP inherits them without bespoke logic
- `2026-06-18-mcp-service-client-P01-S05` - Export the service-client public surface from the package init
- `2026-06-18-mcp-service-client-P01-S06` - Repoint the CLI HTTP search module to re-export from the service-client package, preserving the CLI surface
- `2026-06-18-mcp-service-client-P01-S07` - Repoint the CLI service-status discovery helpers to re-export from the service-client package
- `2026-06-18-mcp-service-client-P02-S08` - Rewrite the MCP search and index tools to delegate to the service-client, delete the duplicate daemon-call seam, route index-status to the service-state route, and map the unreachable return to one clear service-not-running error
- `2026-06-18-mcp-service-client-P02-S09` - Rewrite the MCP admin and observability tools to delegate to the service-client admin function
- `2026-06-18-mcp-service-client-P02-S10` - Rewrite the MCP vault-document resource to delegate to the service-client
- `2026-06-18-mcp-service-client-P03-S11` - Remove the in-process MCP mount and the redirect ASGI wrapper from the server entry point
- `2026-06-18-mcp-service-client-P03-S12` - Remove the in-process GPU model load from the stdio branch and make stdio the sole MCP transport in the entry point
- `2026-06-18-mcp-service-client-P04-S13` - Correct the stale server-owns-mcp docstring in the server package init
- `2026-06-18-mcp-service-client-P04-S14` - Correct the stale server-owns-mcp docstring in the server state module
- `2026-06-18-mcp-service-client-P04-S15` - Remove the phantom mcp-start and mcp-admin exemption from the conflation guard test
- `2026-06-18-mcp-service-client-P04-S16` - Align the ecosystem test's documented MCP command surface with the commands that actually ship
- `2026-06-18-mcp-service-client-P05-S17` - Add the fresh-interpreter subprocess runtime check and broaden the static forbidden-import set to include cli and api
- `2026-06-18-mcp-service-client-P05-S18` - Add the no-local-fallback test asserting each tool raises a clear service-not-running error against an isolated empty status dir
- `2026-06-18-mcp-service-client-P05-S19` - Update the server tests that bind the removed HTTP mount and in-process model-load expectations
- `2026-06-18-mcp-service-client-P06-S20` - Run the full unit and GPU integration suite locally and confirm green
- `2026-06-18-mcp-service-client-P06-S21` - Conduct a formal vaultspec code review and record the audit

### plan

- `2026-06-18-mcp-service-client-plan` - `mcp-service-client` plan

### research

- `2026-06-18-mcp-service-client-research` - `mcp-service-client` research: `MCP backend rework as a thin service client`
