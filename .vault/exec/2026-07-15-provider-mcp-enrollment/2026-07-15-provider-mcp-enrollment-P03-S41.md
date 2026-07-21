---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S41'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Repair service attribution and deterministic release-test isolation

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`
- `service-job behavior tests`
- `and isolated real service fixtures`

## Description

- Carry explicit `cli` and `mcp` initiator identities through the shared reindex
  transport and retain them in the real service job registry.
- Isolate every shared service fixture by status directory, storage root, service
  port, Qdrant port, and machine lock; capture logs and verify exact service and
  Qdrant process termination.
- Align Qdrant, admin, and real integration-client deadlines to the measured
  thirty-second service envelope while preserving structured timeout results and
  avoiding retries.
- Ground eviction timing in a real pre-admission residency check and refresh the
  retained project before admitting the eviction candidate.
- Update stale operator-rendering and empty-index phase assertions to the current
  production contracts without weakening positive or negative behavior checks.
- Split large real-behavior assertions into focused helpers so the complexity gate
  remains within its calibrated ceiling.

## Outcome

- Passed two full eviction repetitions and three full lifecycle repetitions after
  their final timeout corrections.
- Passed a fresh sequential ten-file service ledger: 142 tests across doctor,
  eviction, jobs, lifecycle, logs, metrics, search diagnostics, service state, and
  storage survey.
- Passed 271 focused CLI and transport tests plus 57 MCP conformance, isolation,
  and no-local-fallback tests.
- Passed Ruff, path-scoped format validation, `ty`, strict BasedPyright,
  complexity, provider-artifact validation, Vaultspec validation, and lock
  consistency.
- Built the source and wheel distributions and passed isolated installed-wheel
  smoke against public `vaultspec-core 0.1.44`, including native Claude and Codex
  project enrollment.

## Notes

- The first storage-survey invocation reached the command harness's five-minute
  ceiling before pytest terminated. It received no credit; the complete rerun
  passed all eleven tests in 289.36 seconds.
- One older service process matched the worktree path but predated this execution
  and could not be attributed to the timed-out test, so it was left untouched.
- Full-tree format inspection reports a byte-identical `origin/main` drift outside
  this Step. CI does not run that format gate; all twelve changed Python files pass
  the repository's staged-path format contract.
