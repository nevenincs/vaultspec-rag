---
tags:
  - '#exec'
  - '#cli-mcp-decoupling'
date: '2026-06-05'
modified: '2026-07-27'
body_hash: 'sha256:617cc6d6ba089081d83b2e593eec426ab34e6678d125d08cc8eed55f7c568775'
step_id: 'S02'
related:
  - "[[2026-06-05-cli-mcp-decoupling-plan]]"
---

## Description

### Scope

- `src/vaultspec_rag/cli/_benchmark.py`

- Clean up `handle_benchmark` to remove direct model loading, database opening, and timing code.

- Delegate entire benchmark run to backend facade API `run_benchmark`.

- Format results into a Rich `Table` for terminal rendering.

- Catch ValueError and translate "No vault documents indexed" to exit code 1.

## Outcome

- The CLI benchmark subcommand is now a thin transport/formatting wrapper delegating to the backend.

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.
