---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
body_hash: 'sha256:27ee2ab10a269a601bf4501282f0c3c4ce36cb3633b682736a987a9541a4ab89'
step_id: 'S54'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Align real job-completion integration waits with the bounded service administration contract

## Scope

- `src/vaultspec_rag/tests/integration/test_jobs_registry.py and S53 release-gate diagnostics`

## Description

- Replace both duplicated fifty-iteration completion loops with one job-ID-scoped
  terminal-phase helper.
- Use the established 120-second real service-job completion deadline, distinct from
  the 30-second timeout for one administrative HTTP call.
- Bound each administrative HTTP poll by the deadline's remaining budget, poll at
  100-millisecond intervals, and reject terminal observations received after expiry.
- Return immediately on timely `done`, `error`, or `failed`, and retain the final job
  plus service envelope for timeout diagnostics.
- Re-run both real selectors repeatedly, the complete registry module, the related
  service-jobs integration module, and every static quality gate.

## Outcome

- Passed each exact real-service selector three times. Vault call durations were
  3.808, 20.794, and 7.583 seconds; codebase call durations were 7.133, 7.248, and
  12.134 seconds.
- Passed the complete jobs-registry module: 9 tests in 108.77 seconds.
- Passed the related service-jobs integration module: 61 tests in 178.31 seconds.
- Passed Ruff lint and touched-file formatting, Ty, BasedPyright with zero findings,
  every complexity threshold, and diff hygiene.
- Preserved real terminal failure detection: `error` and `failed` phases return to the
  caller and the existing exact `done` assertions remain authoritative.
- Completed independent re-review with PASS and no actionable findings after resolving
  the MEDIUM deadline-enforcement finding.

## Notes

- An exploratory 30-second deadline failed honestly while the real codebase job was
  still `running` at `embed + upsert chunks` with 0 of 197 chunks complete. This
  established that the administrative request timeout is not a job-completion
  contract; the final helper does not use it.
- Independent review rejected the first 120-second helper because it could accept a
  terminal response observed after expiry. The final helper passes only the remaining
  deadline budget to every real HTTP poll and checks expiry before terminal credit.
- One uncredited cold-start attempt missed the fixture's pre-existing 90-second
  readiness gate: model loading took 105.84 seconds and startup took 110.10 seconds.
  The startup gate was not changed because this repository defines no higher
  model-service startup contract for that fixture. Subsequent service setups completed
  between 30.1 and 58.8 seconds.
- No production file changed. No mock, fake, stub, patch, monkeypatch, skip, or xfail
  was introduced.
