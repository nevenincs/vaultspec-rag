---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S36'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Confirm destructive routes are loopback and token gated and that control-plane verbs are absent from MCP

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

Confirmed the destructive control-plane verbs are absent from MCP and that the storage
surface keeps the loopback-plus-token boundary. Under the accepted CLI-direct architecture
there are no destructive HTTP routes at all: delete, prune, and migrate run as CLI verbs
that open their own client to the managed loopback Qdrant. The MCP exposes no
delete/prune/migrate tool; enumerated the registered MCP tools and confirmed the only
storage verb is the new read-only survey. Verified the new survey surface is read-only and
correctly gated: the service-side survey route is token-gated like every other monitoring
route, runs server-mode only, and returns a bounded, filterable classification; the MCP
survey tool is a thin delegate to that route and performs no mutation.

## Outcome

The MCP carries the read-only survey alone; no storage control-plane verb is reachable
through it, satisfying the MCP-absence invariant. The destructive verbs stay CLI-only, the
managed server binds loopback, and the survey route is token-gated and server-mode-bounded.
The MCP tool-registration manifest test was updated to include the new survey tool and its
count, and an end-to-end integration test drives the survey through the route, the service
client, and the MCP tool against a live server-mode service.

## Notes

The read-only survey MCP tool was added in this reconciliation (the one service surface the
ADR sanctions as service-domain-owned). The destructive HTTP routes and their CLI adapters
the original plan named were deliberately not built; that supersession is recorded in the
plan's reconciliation note and the shared supersession record.
