---
tags:
  - '#exec'
  - '#index-perf-hardening'
date: '2026-06-02'
modified: '2026-06-30'
body_hash: 'sha256:a040e4be61b70b3f466a97076675f89a2a662626fcb57661147836b340644abe'
step_id: 'S07'
related:
  - "[[2026-06-02-index-perf-hardening-plan]]"
---

# Add a benchmark that captures chunk and embed wall-clock before and after on a large synthetic tree

## Scope

- `src/vaultspec_rag/tests/benchmarks/`

## Description

- Add a CPU-only chunk-stage benchmark (serial vs parallel) on a synthetic tree, asserting parity and a wall-clock win.

## Outcome

Demonstrated ~3x on 2000 files / 24 cores; surfaced and drove the fix for a small-codebase regression (the byte gate).

## Notes

None.
