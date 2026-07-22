---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S03'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Prove ambient and in-test path changes cannot redirect singleton writers into a test-owned trap outside the session root

## Scope

- `src/vaultspec_rag/tests/test_managed_singleton_isolation.py`

## Description

- Exercise hostile status and storage paths inherited before an exec child imports production code.
- Attempt to disable and re-anchor the process-pinned guard during a running test.
- Prove each configured anchor fails closed independently and every singleton record remains unchanged.
- Keep a real sentinel process alive across service termination and orphan-reap attempts.
- Start a verified provisioned Qdrant child and prove an escaped configuration cannot stop it.
- Restore contained configuration and perform bounded production cleanup for every child.

## Outcome

Seven real-behavior regressions now prove that ambient and same-test path changes cannot
redirect singleton writers, lock probes, record deletion, log-directory creation, service
control, or supervised Qdrant control outside the session root. Both configured anchors are
independently load-bearing, mutable environment transport cannot replace process-local
authority, and the exact real child PIDs remain alive until contained cleanup is restored.

## Notes

The first formal review found missing direct coverage for `_resolve_log_path` and the live
`QdrantSupervisor.stop` branch, plus one Ruff simplification finding. The follow-up uses the
manifest-backed provisioned binary through `start_supervised_from_config`, resolves both
findings, and passed re-review with no residual issue.

The focused suite passed seven tests. Ruff format and lint passed, BasedPyright reported zero
diagnostics, and source inspection confirmed no fake, mock, stub, patch, monkeypatch, skip, or
expected-failure shortcut.
