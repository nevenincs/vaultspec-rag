---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S18'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add a read-only survey MCP tool delegating to the service

## Scope

- `src/vaultspec_rag/mcp/_admin_tools.py`

## Description

Built the read-only survey as a service-owned surface and a thin MCP delegate over it - the
one storage surface the ADR sanctions as service-domain-owned. Added a token-gated
`storage/survey` route on the daemon that is server-mode only (a local store has nothing to
reconcile), reuses the existing survey gathering against the managed server, and returns a
bounded, filterable envelope: an optional status filter (live / orphaned / unknown /
unverifiable) and a clamped limit, with returned/total/limit reported. Mapped the route in
the shared service client so both CLI and MCP reach it through the one admin transport. Added
the MCP survey tool delegating to that route and performing no mutation. Made the CLI survey
service-first: when a daemon is running it reads the route so operator, CLI, and MCP share one
classification, falling back to the existing CLI-direct client when no service answers.

## Outcome

The survey now flows through three consistent surfaces over one service-owned classification:
the daemon route, the MCP tool, and the service-first CLI. The view is bounded and filterable
per the operator-views discipline, token-gated like every other monitoring route, and read-
only - the destructive verbs stay CLI-direct. Real-backend integration tests drive the route,
the admin client filter mapping, and the MCP tool against a live server-mode service; all
pass.

## Notes

The survey gathering runs on a worker thread off the GPU lock (pure storage classification).
The MCP tool-registration manifest test was updated for the added tool. The CLI fallback
returns to the direct client only when the service is unreachable, so a live-but-non-server-
mode service still renders the proper server-mode-required message through the direct path.
