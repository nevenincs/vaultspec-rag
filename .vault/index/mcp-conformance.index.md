---
generated: true
tags:
  - '#index'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
related:
  - '[[2026-06-30-mcp-conformance-P01-S01]]'
  - '[[2026-06-30-mcp-conformance-P01-S02]]'
  - '[[2026-06-30-mcp-conformance-P01-S03]]'
  - '[[2026-06-30-mcp-conformance-P02-S04]]'
  - '[[2026-06-30-mcp-conformance-P02-S05]]'
  - '[[2026-06-30-mcp-conformance-P03-S06]]'
  - '[[2026-06-30-mcp-conformance-P03-S07]]'
  - '[[2026-06-30-mcp-conformance-P04-S08]]'
  - '[[2026-06-30-mcp-conformance-P04-S09]]'
  - '[[2026-06-30-mcp-conformance-P04-S10]]'
  - '[[2026-06-30-mcp-conformance-P05-S11]]'
  - '[[2026-06-30-mcp-conformance-P06-S12]]'
  - '[[2026-06-30-mcp-conformance-P06-S13]]'
  - '[[2026-06-30-mcp-conformance-adr]]'
  - '[[2026-06-30-mcp-conformance-audit]]'
  - '[[2026-06-30-mcp-conformance-plan]]'
  - '[[2026-06-30-mcp-conformance-reference]]'
  - '[[2026-06-30-mcp-conformance-research]]'
---

# `mcp-conformance` feature index

Auto-generated index of all documents tagged with `#mcp-conformance`.

## Documents

### adr

- `2026-06-30-mcp-conformance-adr` - `mcp-conformance` adr: `MCP service-discovery on the machine-singleton model` | (**status:** `accepted`)

### audit

- `2026-06-30-mcp-conformance-audit` - `mcp-conformance` audit: `MCP conformance verify-phase review`

### exec

- `2026-06-30-mcp-conformance-P01-S01` - Add a machine-singleton discovery resolver that returns the live service port and token from read_machine_discovery validated by machine_lock_live_holder and heartbeat staleness
- `2026-06-30-mcp-conformance-P01-S02` - Make the machine-global resolution authoritative and demote the per-status-directory service.json to a non-overriding hint
- `2026-06-30-mcp-conformance-P01-S03` - Route \_default_service_port and the MCP \_require_port through the per-call status-directory-independent resolver
- `2026-06-30-mcp-conformance-P02-S04` - Report the resolution failure class and the discovery source and resolved port instead of an empty-bodied transport error
- `2026-06-30-mcp-conformance-P02-S05` - Fail fast on an absent service with the start-the-service remediation as an isError tool result
- `2026-06-30-mcp-conformance-P03-S06` - Remove the admin and lifecycle tools from the MCP surface and stop registering them
- `2026-06-30-mcp-conformance-P03-S07` - Remove the duplicate get_index_status tool
- `2026-06-30-mcp-conformance-P04-S08` - Add tool annotations and display titles to the surviving search and refresh and retrieval tools
- `2026-06-30-mcp-conformance-P04-S09` - Add outputSchema and structuredContent and a stable return shape to the search tools
- `2026-06-30-mcp-conformance-P04-S10` - Align the MCP search default result count with the CLI default
- `2026-06-30-mcp-conformance-P05-S11` - Treat a stale or orphaned machine pointer as absence and isolate the leaked test token under the managed-storage isolation discipline
- `2026-06-30-mcp-conformance-P06-S12` - Add real-behavior tests for cross-status-directory discovery resolution and staleness rejection
- `2026-06-30-mcp-conformance-P06-S13` - Add conformance tests for the narrowed MCP surface and tool annotations

### plan

- `2026-06-30-mcp-conformance-plan` - `mcp-conformance` plan

### reference

- `2026-06-30-mcp-conformance-reference` - `mcp-conformance` reference: `MCP specification baseline and conformant search surface`

### research

- `2026-06-30-mcp-conformance-research` - `mcp-conformance` research: `MCP conformance: connection defect and CLI parity gap`
