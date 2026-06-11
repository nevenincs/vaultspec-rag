---
tags:
  - '#research'
  - '#service-status-convergence'
date: '2026-06-11'
related:
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-vaultspec-rag-cli-service-ux-audit]]'
  - '[[2026-06-01-service-observability-adr]]'
  - '[[2026-06-07-mcp-server-deconflation-adr]]'
  - '[[2026-06-06-cli-tree-overhaul-adr]]'
  - '[[2026-06-09-operability-hardening-adr]]'
---

# `service-status-convergence` research: `canonical service status model`

This research grounds the decision to converge the resident service's operational
interfaces around one canonical status model. It is based on the live CLI audit and a
bounded Wave 00 reproduction through `vaultspec-rag`.

## Findings

### R1. Existing status-like surfaces overlap without a clear hierarchy

The live CLI exposes `server status`, `server jobs`, `server logs`, and `server info`.
The service exposes `/health`, `/jobs`, `/logs`, `/logs/json`, and `/service-state`.
The user-facing naming does not explain which surface answers the operator's primary
question: "is the service usable and what is it doing?"

The current shape emerged from the accepted service-observability work, which added
read-only HTTP routes and CLI/MCP parity. The audit shows that route parity did not
produce a coherent operator model.

### R2. `server status` is closest to the canonical surface

`server status --json` returns process state, heartbeat freshness, token match, port
state, and embedded `/health` data. It is the best candidate for the canonical concise
operator view.

It currently omits active jobs summary, index freshness, resource pressure, and next
action. Those omissions force users to manually combine status, jobs, logs, and index
commands.

### R3. `/health` should remain readiness-only

`/health` is ungated and returns readiness, CUDA availability, model-loaded state,
project count, uptime, backend capabilities, and `service_token`. It is useful for
automation and identity checks, but it should not expand into the full operator status
surface.

If the CLI exposes `server health`, it should mirror readiness only and should not compete
with `server status`.

### R4. `server info` has a broken contract

`server info --json --port 8766` returned an outer success envelope with an inner service
error because `/service-state` requires `project_root`, while the CLI command exposes no
project-root option and did not propagate global `--target`.

The command should either be folded into the canonical status/detail model or fixed so
its required inputs and failure semantics are explicit.

### R5. MCP deconflation remains incomplete

RAG search surfaced documentation and implementation snippets that describe service CLI
commands as parity with MCP tools such as `get_logs` and `get_jobs`. Help text and code
still use MCP-shaped language for service operations, including `MCP port` in service
admin contexts.

The prior deconflation decisions need to be extended: MCP should be an adapter over a
service-domain operation model, not the conceptual owner of status, jobs, logs, or search
semantics.

### R6. Recommended direction

Define a service-domain status contract and make all adapters use it:

- CLI: `server status` renders the concise status and `--json` returns the same domain
  shape.
- HTTP: `/status` or `/service/status` returns the same domain shape.
- MCP: a tool may expose the same status, but it adapts the service-domain operation.
- `/health` remains readiness-only.
- `jobs` and `logs` become cross-referenced subresources, not competing status concepts.

The ADR should supersede the status/health/jobs/logs parity shape from
`service-observability` while preserving the loopback and token-gating constraints.
