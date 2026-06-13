---
tags:
  - '#exec'
  - '#cli-mcp-decoupling'
date: '2026-06-05'
modified: '2026-06-05'
step_id: 'S02'
related:
  - "[[2026-06-05-cli-mcp-decoupling-plan]]"
---

# Refactor CLI benchmark command to call run_benchmark and render the table

## Scope

- `src/vaultspec_rag/cli/_benchmark.py`

## Description

- Clean up `handle_benchmark` to remove direct model loading, database opening, and timing code.
- Delegate entire benchmark run to backend facade API `run_benchmark`.
- Format results into a Rich `Table` for terminal rendering.
- Catch ValueError and translate "No vault documents indexed" to exit code 1.

## Outcome

- The CLI benchmark subcommand is now a thin transport/formatting wrapper delegating to the backend.

## Notes
