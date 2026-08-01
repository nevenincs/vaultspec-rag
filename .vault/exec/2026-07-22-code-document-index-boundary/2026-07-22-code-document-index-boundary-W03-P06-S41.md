---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:de948b4a5bde8a3190ac34e3a9b7b0bff35c7c2700dcde79de26348eebe1eb30'
step_id: 'S41'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Keep retryable extraction as a service-owned obligation with bounded per-kind backoff and circuit state

## Scope

- `src/vaultspec_rag/jobs.py`
- `src/vaultspec_rag/watcher_retry.py`

## Description

- Add document-owned watcher retry, generation, circuit, and durable state.
- Dispatch document jobs independently from code retry state.

## Outcome

Retryable document extraction remains a bounded service convergence obligation without mutating code retry state.

## Notes

Mixed watcher cancellation and newer-generation handoff both passed.
