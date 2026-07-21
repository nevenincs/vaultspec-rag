---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-19'
step_id: 'S20'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Run the full unit suite, lints (ruff, ty, basedpyright), and an end-to-end preprocess index benchmark on a rule-matched corpus to confirm the per-file cost returns to the process-spawn baseline

## Scope

- `src/vaultspec_rag/`

## Description

- Run the full unit suite via the main worktree interpreter with PYTHONPATH shadowing.
- Run ruff, ty, and basedpyright.
- Benchmark per-file hook cost with a 20-file rule-matched corpus and a trivial JSON-emitting hook.

## Outcome

Unit suite: 1598 passed, 3 failed - all three fail identically on unmodified main (two machine-singleton environmental collisions with the live service; one stale MCP-parity test already fixed on the parallel in-flight branch). ruff, ty, and basedpyright all clean. Benchmark: 20 rule-matched files preprocessed at 78 ms/file (previously ~5000-8000 ms/file under the sandbox; ~50 ms/file pre-hook chunking baseline).

## Notes

Benchmark methodology: `run_preprocessor` measured directly, isolating the launch path that regressed; the embed pipeline was untouched by this feature.
