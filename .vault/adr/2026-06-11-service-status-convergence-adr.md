---
tags:
  - '#adr'
  - '#service-status-convergence'
date: '2026-06-11'
modified: '2026-06-30'
related:
  - '[[2026-06-11-service-status-convergence-research]]'
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-vaultspec-rag-cli-service-ux-audit]]'
  - '[[2026-06-01-service-observability-adr]]'
  - '[[2026-06-07-mcp-server-deconflation-adr]]'
  - '[[2026-06-06-cli-tree-overhaul-adr]]'
  - '[[2026-06-09-operability-hardening-adr]]'
---

# `service-status-convergence` adr: `canonical service status model` | (**status:** `accepted`)

## Problem Statement

The resident service exposes too many overlapping status-like surfaces. Users must
manually combine health, status, jobs, logs, and service info to answer whether the
service is usable and what it is doing.

The accepted service-observability decision established read-only HTTP and CLI/MCP parity,
but the live CLI audit showed that parity at the route/tool level is not enough. The
product needs one canonical operational status model.

## Considerations

- `server status` already combines process status, heartbeat, identity, port state, and
  health.
- `/health` is useful as an ungated readiness and identity probe.
- `server info` currently overlaps with status but fails when the required project root
  is not supplied.
- Existing CLI help and docs leak MCP terminology into service operations.
- Jobs and logs are operational subresources, not separate status models.

## Constraints

- `/health` must remain lightweight and ungated for readiness and identity checks.
- The loopback-bound service token gate for monitoring routes must remain intact.
- Backwards-compatible command names should be preserved unless a later decision approves
  a breaking CLI change.
- MCP must become an adapter over service-domain operations, not the owner of status
  semantics.

## Implementation

Define a service-domain status contract. `server status` becomes the canonical concise
operator view. It should include process state, readiness, active job summary, index
freshness summary when available, resource pressure when available, and an actionable next
step.

`/health` remains readiness-only. If a CLI health command is exposed, it mirrors readiness
and does not compete with `server status`.

`server info` must either be folded into the status/detail model or fixed so its required
project-root input and failure semantics are explicit.

CLI, HTTP, and MCP adapters must use the same service-domain model and names.

## Rationale

The live audit demonstrated that users cannot reliably infer operational state from
separate primitive commands. A standard command-line interface needs a predictable status
surface and subordinate detail commands.

The earlier observability ADR is superseded for the shape of status, health, jobs, and
logs. Its security and loopback monitoring constraints remain valid.

## Consequences

The CLI becomes simpler to reason about, but implementation must touch multiple adapters:
CLI rendering, HTTP routes, MCP tools, help text, docs, tests, and JSON envelopes.

Some older documentation language around `server service` and MCP parity must be revised.

## Codification candidates

- **Rule slug:** `service-domain-owns-operability`.
  **Rule:** CLI, HTTP, and MCP operability surfaces must adapt a service-domain operation
  instead of making MCP tools or route names the source of business semantics.

- **Rule slug:** `manual-cli-persona-required`.
  **Rule:** Every CLI operability change must end with a named manual persona test in
  addition to automated tests.
