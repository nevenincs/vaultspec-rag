---
tags: ['#exec', '#cli-service-operability-hardening']
date: '2026-06-11'
step_id: 'W01.S01'
related:
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-service-status-convergence-adr]]'
---

# `cli-service-operability-hardening` W01.S01 - status and health parity

## Step

Implemented the first convergence slice for service health and service state.

## Changes

- Added `vaultspec-rag server health` as a JSON/table CLI entry point over the service `/health` probe.
- Changed `server info` to require a project root from `--project-root` or global `--target`.
- Passed the project root into the service-state admin route.
- Stopped wrapping service-side bad requests as successful `service.info` envelopes.
- Reworded server-facing port help away from "MCP port" toward "Service port".

## Verification

- `uv run pytest src/vaultspec_rag/tests/integration/test_service_state.py`
- `uv run vaultspec-rag server health --json`
- `uv run vaultspec-rag server info --project-root . --json`
- `uv run vaultspec-rag server info --json`

## Outcome

The CLI now has a direct local health entry point and `server info` produces actionable failure when project context is missing.
