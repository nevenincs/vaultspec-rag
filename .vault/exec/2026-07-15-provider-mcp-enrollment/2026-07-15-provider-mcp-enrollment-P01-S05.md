---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
step_id: 'S05'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Preserve Core per-provider outcomes in structured reports and CLI rendering

## Scope

- `src/vaultspec_rag/commands/_models.py`
- `src/vaultspec_rag/cli/_render.py`
- `and src/vaultspec_rag/tests/test_cli.py`

## Description

- Aggregate every Core `per_tool` result by provider without flattening host identity.
- Serialize counters, items, errors, and warnings under a deterministic
  `sync_providers` JSON object.
- Render explicit Claude and Codex MCP outcome lines from the same report data.
- Prove install and uninstall report parity with Core's real `SyncResult` contract.

## Outcome

Structured install and uninstall reports now retain provider-local MCP results instead
of exposing only global totals. JSON callers receive stable Claude/Codex objects with
all counters and diagnostics; human output renders the same outcomes and provider-local
warnings. Multiple MCP reconciliation passes aggregate by provider while preserving
each action item.

## Notes

The plan scope was expanded before execution to include the real renderer regression
tests. Ten focused report tests pass with Ruff, formatting, BasedPyright, Ty, and the
full repository complexity gate.
