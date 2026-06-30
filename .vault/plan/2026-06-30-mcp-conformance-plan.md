---
tags:
  - '#plan'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
tier: L2
related:
  - '[[2026-06-30-mcp-conformance-adr]]'
  - '[[2026-06-30-mcp-search-scope-adr]]'
  - '[[2026-06-30-mcp-conformance-research]]'
---

# `mcp-conformance` plan

### Phase `P01` - Machine-singleton discovery resolution

Resolve the one resident machine service through the status-directory-independent machine-global pointer, gated by the OS-lock live holder and heartbeat staleness, authoritative over any per-status-directory service.json (SD1-SD3).

- [ ] `P01.S01` - Add a machine-singleton discovery resolver that returns the live service port and token from read_machine_discovery validated by machine_lock_live_holder and heartbeat staleness; `src/vaultspec_rag/serviceclient/_discovery.py`.
- [ ] `P01.S02` - Make the machine-global resolution authoritative and demote the per-status-directory service.json to a non-overriding hint; `src/vaultspec_rag/serviceclient/_discovery.py`.
- [ ] `P01.S03` - Route \_default_service_port and the MCP \_require_port through the per-call status-directory-independent resolver; `src/vaultspec_rag/mcp/_tools.py`.

### Phase `P02` - Legible errors and fail-fast remediation

Replace empty-bodied transport errors and silent dead ends with a legible failure class and a fail-fast start-the-service remediation surfaced as an isError tool result (SD5-SD6).

- [ ] `P02.S04` - Report the resolution failure class and the discovery source and resolved port instead of an empty-bodied transport error; `src/vaultspec_rag/serviceclient/_transport.py`.
- [ ] `P02.S05` - Fail fast on an absent service with the start-the-service remediation as an isError tool result; `src/vaultspec_rag/mcp/_tools.py`.

### Phase `P03` - MCP surface narrowing

Narrow the MCP surface to search plus index-refresh plus read-only retrieval: remove admin and lifecycle tools and the duplicate status tool, leaving operability to the CLI (SB1-SB4).

- [ ] `P03.S06` - Remove the admin and lifecycle tools from the MCP surface and stop registering them; `src/vaultspec_rag/mcp/_admin_tools.py`.
- [ ] `P03.S07` - Remove the duplicate get_index_status tool; `src/vaultspec_rag/mcp/_tools.py`.

### Phase `P04` - Spec conformance on surviving tools

Bring the surviving tools to the 2025-11-25 spec: tool annotations, display titles, outputSchema with structuredContent, a stable return shape, and CLI-aligned search defaults (SB5 and the reference recommendations).

- [ ] `P04.S08` - Add tool annotations and display titles to the surviving search and refresh and retrieval tools; `src/vaultspec_rag/mcp/_tools.py`.
- [ ] `P04.S09` - Add outputSchema and structuredContent and a stable return shape to the search tools; `src/vaultspec_rag/mcp/_tools.py`.
- [ ] `P04.S10` - Align the MCP search default result count with the CLI default; `src/vaultspec_rag/mcp/_tools.py`.

### Phase `P05` - Managed-state hygiene

Treat a stale or orphaned machine pointer as absence under the staleness contract and isolate the leaked test token in the real managed directory (SD4 hygiene).

- [ ] `P05.S11` - Treat a stale or orphaned machine pointer as absence and isolate the leaked test token under the managed-storage isolation discipline; `src/vaultspec_rag/_machine_lock.py`.

### Phase `P06` - CLI-to-MCP conformance test matrix

Add a standing real-behavior conformance test matrix covering cross-status-directory discovery, staleness rejection, the narrowed surface, and tool annotations so the surface stops regressing untested.

- [ ] `P06.S12` - Add real-behavior tests for cross-status-directory discovery resolution and staleness rejection; `src/vaultspec_rag/tests/test_machine_discovery_resolution.py`.
- [ ] `P06.S13` - Add conformance tests for the narrowed MCP surface and tool annotations; `src/vaultspec_rag/tests/test_mcp_conformance_surface.py`.

## Description

## Steps

## Parallelization

## Verification
