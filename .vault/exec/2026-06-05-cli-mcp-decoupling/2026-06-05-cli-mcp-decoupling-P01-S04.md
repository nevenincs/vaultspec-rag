---
tags:
  - '#exec'
  - '#cli-mcp-decoupling'
date: '2026-06-05'
step_id: 'S04'
related:
  - "[[2026-06-05-cli-mcp-decoupling-plan]]"
---

# Refactor CLI quality command to call run_quality_probe and print the results

## Scope

- `src/vaultspec_rag/cli/_quality.py`

## Description

- Clean up `handle_quality` to remove temporary directories, synthetic corpus creation, indexing, search, and precision loop logic.
- Delegate quality tests to backend API `run_quality_probe`.
- Render the table of probes and print precision percentages and pass/fail status.
- Raise `typer.Exit(code=1)` if the precision drops below the threshold.

## Outcome

- The CLI quality command is now a thin transport/formatting wrapper delegating to the backend.

## Notes
