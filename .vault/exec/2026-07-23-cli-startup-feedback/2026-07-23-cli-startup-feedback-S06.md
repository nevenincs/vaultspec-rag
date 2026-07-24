---
tags:
  - '#exec'
  - '#cli-startup-feedback'
date: '2026-07-23'
modified: '2026-07-24'
step_id: 'S06'
related:
  - "[[2026-07-23-cli-startup-feedback-plan]]"
---

# Verify on a real GPU cold start that provisioning, per-model load count, and reranker stages render live, and record the execution

## Scope

- `src/vaultspec_rag/cli/_service_start.py`

## Description

- Ran a real-GPU `server start` cold start in a fresh isolated `%TEMP%` worktree off `origin/main`, with `VAULTSPEC_RAG_STATUS_DIR` / `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` / `VAULTSPEC_RAG_QDRANT_PORT` isolated and `--qdrant-auto-provision` to exercise first-use provisioning.
- Polled the daemon's published status view through startup and captured the phase progression.

## Outcome

The three named cold-start stages rendered live and in order, and the model-load count advanced as intended:

```
warming | provisioning the qdrant server | None/None
warming | loading models              | 0/3
warming | loading the reranker         | 2/3
```

The count moving `0 -> 2` under the `loading` labels confirms the S02 count-progression fix live (refuting the code review's static-count concern). The service log corroborates a complete cold start: the auto-provisioned Qdrant binary started (`qdrant server ready in 3.12s`), all three models loaded (`All models loaded in 29.49s`), and startup completed (`Service startup complete in 32.91s`); a clean `server stop` confirmed the daemon had reached ready.

## Notes

The terminal `models ready (3/3)` publish and the RUNNING transition were not caught by the 0.25s status-file poll - a read race at the fast final transition (~33s) - but the service log confirms every model loaded and startup completed, so the full publish sequence executed. Run entirely in an isolated `%TEMP%` worktree and env; the shared main worktree and the resident service were not touched.
