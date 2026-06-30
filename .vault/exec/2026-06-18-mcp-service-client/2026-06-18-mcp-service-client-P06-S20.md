---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S20'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Run the full unit and GPU integration suite locally and confirm green

## Scope

- `src/vaultspec_rag/tests`

## Description

- Ran the full unit suite (`-m unit`): **1042 passed, 569 deselected, 0 failures** in ~116s.
- Ran the GPU integration suite (`tests/integration`) twice; both runs were blocked by environmental GPU exhaustion (see Outcome/Notes), not by a code fault.
- Ran the targeted MCP admin integration test (`test_mcp_admin_tools.py`) to validate the changed MCP-to-`serviceclient`-to-daemon surface; its `live_service` fixture could not start because the GPU had under 2 GB free.

## Outcome

The unit gate - the project's authoritative pre-merge gate - is fully green at 1042
passed. The GPU integration suite could not be confirmed green: the host GPU was
saturated by a concurrent workstream (a live `vaultspec_rag.server` daemon from a
separate worktree), leaving 1.8 GB free of 16 GB at 100% utilization, so the integration
tests' own services could not load models. Every integration failure was a setup-time
service-start timeout or a reranker forward-pass hang in the untouched search/rerank
engine - never a logic failure in the reworked MCP/client surface. The rework's
correctness is independently validated by the 1042 unit tests, the dedicated mock-free
import-isolation and no-local-fallback guards, `basedpyright` 0, `ruff` clean, and the
formal code review (PASS-WITH-FOLLOWUPS, both MEDIUM findings resolved).

## Notes

- Root cause of the integration block: the host GPU (16 GB) was at ~14.2 GB used / 100%
  utilization, held by a concurrent `vaultspec_rag.server` daemon from another active
  worktree plus other GPU applications. The integration services need roughly 2 GB to
  load the dense, sparse, and reranker models; with 1.8 GB free they could not start, so
  the first reranker `predict()` blocked for the full per-test timeout.
- This is a path the rework does not touch: the dense and sparse GPU encodes during
  index build succeeded on this branch, confirming CUDA and the engine are healthy; only
  contention prevented the reranker stage from getting GPU time.
- Freeing the GPU requires stopping another workstream's running daemon, which is the
  operator's decision, not a step this execution should take unilaterally.
- **Operator decision (2026-06-19): the GPU integration run is waived.** The unit gate
  (1042 passed) plus the dedicated mock-free import-isolation and no-local-fallback
  guards, `basedpyright` 0, `ruff` clean, and the code review (PASS-WITH-FOLLOWUPS) are
  accepted as sufficient verification for this feature, whose surface does not touch the
  GPU search/rerank engine the integration suite exercises. The step is closed on that
  basis; the GPU integration suite was not run green and remains available to run on a
  free-GPU window if desired.
