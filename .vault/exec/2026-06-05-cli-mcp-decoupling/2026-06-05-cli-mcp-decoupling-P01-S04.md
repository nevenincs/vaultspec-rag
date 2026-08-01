---
tags:
  - '#exec'
  - '#cli-mcp-decoupling'
date: '2026-06-05'
modified: '2026-07-27'
body_hash: 'sha256:d81a6bb6fb9e9f55d3b5d5069738c91d50b7abf1ac91494527191e5d58e8355e'
step_id: 'S04'
related:
  - "[[2026-06-05-cli-mcp-decoupling-plan]]"
---

## Description

### Scope

- `src/vaultspec_rag/cli/_quality.py`

- Clean up `handle_quality` to remove temporary directories, synthetic corpus creation, indexing, search, and precision loop logic.

- Delegate quality tests to backend API `run_quality_probe`.

- Render the table of probes and print precision percentages and pass/fail status.

- Raise `typer.Exit(code=1)` if the precision drops below the threshold.

## Outcome

- The CLI quality command is now a thin transport/formatting wrapper delegating to the backend.

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.
