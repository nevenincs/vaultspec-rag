---
tags:
  - '#exec'
  - '#cli-mcp-decoupling'
date: '2026-06-05'
modified: '2026-06-30'
step_id: 'S01'
related:
  - "[[2026-06-05-cli-mcp-decoupling-plan]]"
---

# Extract latency benchmark logic from CLI into new backend API function run_benchmark

## Scope

- `src/vaultspec_rag/api.py`

## Description

- Implement `run_benchmark` in `src/vaultspec_rag/api.py` to timing-bench search latency over a leased slot.
- Query p50, p95, p99, mean, stdev, document counts, and GPU memory metrics.
- Expose the function in the public `__all__` facade list.

## Outcome

- Successfully extracted the latency benchmark orchestration logic to `src/vaultspec_rag/api.py`.

## Notes
