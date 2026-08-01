---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:464d33b6087a47a5f5b66ed96987d6f84a55e85d0c759c92a4b245ebfb5e6337'
step_id: 'S22'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Verify real daemon restart and shutdown preserve queued and paused intent, mark interrupted attempts, and close stores only after worker release using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`

## Description

- Add real-daemon restart coverage for durable queued and paused jobs.
- Verify two daemon lives dispatch queued running intent while preserving dormant paused intent under the same exact IDs.
- Add graceful shutdown coverage for a live code attempt that owns every manager-tracked execution resource.
- Require worker, limiter, lease, writer-lock, and pipeline release before interruption becomes durable.
- Assert attempt completion precedes store closure, registry closure, supervised Qdrant shutdown, and clean service completion.
- Reopen the isolated storage under a second daemon and serve a real code search.
- Use `_service_env` as the single host-Qdrant resolver and isolated binary-plus-manifest mirror.
- Run scoped lint, formatting, strict typing, syntax, complexity, diff, test-integrity, and exact-node collection checks.

## Outcome

The restart scenario restores two canonical resources, dispatches only queued
running intent, and preserves the paused resource across both service lives.
The shutdown scenario observes complete runtime ownership before signalling.
It then observes a durable interrupted result only after every worker and
storage owner releases.

The shutdown log proves attempt completion precedes project-store closure.
Registry closure precedes supervised Qdrant shutdown, and clean service
completion occurs last. A replacement daemon reopens the same isolated storage
and serves a real code search.

The two focused GPU-backed cases passed together during S22 implementation.
The correction pass completed without another daemon run. Ruff, Ruff format,
BasedPyright, AST parsing, cognitive complexity, nesting, Xenon, diff hygiene,
the prohibited-double scan, and exact collection of both nodes pass. Eight
changed functions measure maximum grade C and average grade B.

Independent review returned PASS with no critical or high findings. The two
medium corrections are resolved: host binary lookup now uses the established
integration helper path, and the complexity evidence reports C/B accurately.

## Notes

The shared-host correction run did not start another GPU daemon. Removing the
redundant pre-context mirror preserves behavior because `_service_env` resolves
the host provisioned binary before isolation, copies its manifest unchanged,
and leaves the production pre-execution digest check active.

No fake, mock, stub, patch, monkeypatch, skip, or expected-failure path was
introduced. No production file changed, and no data was lost.
