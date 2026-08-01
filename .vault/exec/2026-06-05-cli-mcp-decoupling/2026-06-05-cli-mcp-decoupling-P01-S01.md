---
tags:
  - '#exec'
  - '#cli-mcp-decoupling'
date: '2026-06-05'
modified: '2026-07-27'
body_hash: 'sha256:5ae6d8d98f20cbe3f9d259a54067b8996fcb012112f6187db407435c46ed36fa'
step_id: 'S01'
related:
  - "[[2026-06-05-cli-mcp-decoupling-plan]]"
---

## Description

### Scope

- `src/vaultspec_rag/api.py`

- Implement `run_benchmark` in `src/vaultspec_rag/api.py` to timing-bench search latency over a leased slot.

- Query p50, p95, p99, mean, stdev, document counts, and GPU memory metrics.

- Expose the function in the public `__all__` facade list.

## Outcome

- Successfully extracted the latency benchmark orchestration logic to `src/vaultspec_rag/api.py`.

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.
