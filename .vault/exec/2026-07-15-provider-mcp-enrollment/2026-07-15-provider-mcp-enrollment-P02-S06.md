---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
step_id: 'S06'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Implement placement-aware MCP extra reconciliation and durable ownership provenance

## Scope

- `src/vaultspec_rag/commands/_mcp_extra.py`

## Description

- Add mode-aware MCP-extra reconciliation for tool, dependency, and dev placement.
- Preserve exact original requirement strings in location-bearing ownership state.
- Restore only owned edits and refuse ambiguous, unowned, or drifted placements.
- Keep dry-run byte-inert and route all writes through the existing atomic TOML helper.

## Outcome

`reconcile_mcp_extra` now leaves unowned project state alone in tool mode, reverses
an owned dependency/dev edit when transitioning to tool mode, updates the existing
runtime or default-dev declaration without moving it, records reversible provenance,
and preserves an already-correct unowned extra.

## Notes

Verified with Ruff, BasedPyright, and a real temporary-file probe covering tool-mode
transition cleanup, dry-run immutability, runtime apply/remove byte restoration, dev
placement, idempotency, and unowned-extra preservation. Core-dependent wiring remains
in later Steps.
