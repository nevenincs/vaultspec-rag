---
name: service-domain-owns-operability
trigger: always_on
---

# Service Domain Owns Operability

## Rule

Always implement service health, status, jobs, logs, and search diagnostics as
service-domain behavior first; CLI and MCP entry points must adapt to that shared
behavior rather than own or duplicate it.

## Why

The `2026-06-11-cli-service-operability-hardening-code-review-audit` and the
`2026-06-11-service-status-convergence-adr` showed that earlier MCP deconflation did
not fully remove MCP-shaped business logic from CLI and service operations. When MCP,
CLI, and localhost routes drift independently, operators see conflicting names, JSON
contracts, and remediation commands.

## How

- Good: add a `/jobs` filter in the server route, pass the same query parameters through
  `server jobs` and MCP `get_jobs`, and keep the JSON envelope stable across adapters.
- Bad: add a CLI-only `server jobs --failed` path that computes different phases from
  the server or an MCP-only admin helper that the CLI must call to understand service
  state.
