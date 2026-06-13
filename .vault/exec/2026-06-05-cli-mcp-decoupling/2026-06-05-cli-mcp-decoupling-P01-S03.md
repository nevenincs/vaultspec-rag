---
tags:
  - '#exec'
  - '#cli-mcp-decoupling'
date: '2026-06-05'
modified: '2026-06-05'
step_id: 'S03'
related:
  - "[[2026-06-05-cli-mcp-decoupling-plan]]"
---

# Extract synthetic quality testing logic from CLI into new backend API function run_quality_probe

## Scope

- `src/vaultspec_rag/api.py`

## Description

- Implement `run_quality_probe` in `src/vaultspec_rag/api.py` using a temporary directory slot.
- Generate synthetic vault, index it, run needle-based precision probes, and calculate precision.
- Close and evict the temporary project slot prior to cleaning up.
- Expose the function in the public `__all__` facade list.

## Outcome

- Successfully extracted the quality probe logic into the unified backend API function in `src/vaultspec_rag/api.py`.

## Notes
