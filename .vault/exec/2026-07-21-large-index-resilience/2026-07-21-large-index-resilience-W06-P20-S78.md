---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:85409659a7bed968e05d358aa805d5c035aa001890b93b373ee6b1a15354d0a5'
step_id: 'S78'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Audit the start verb's exit paths against the lifecycle envelope contract and rebuild the collection the pin move stranded

## Scope

- `src/vaultspec_rag/cli/_service_start.py`
- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Read every terminal path in the start verb rather than inferring compliance from its test coverage, and confirmed each routes through the two shared lifecycle renderers.
- Checked for the failure modes the contract exists to prevent: a bare exit, a second envelope, a missing one, or human text printed on a JSON path. None present.
- Exercised the verb against the running service: an already-running start exits zero with an already-running status and exactly one envelope.
- Declined to stop the operator's service to exercise a cold start, since the service is a machine singleton and the cold path is covered by tests that spawn real services, including startup rollback, readiness expiry, and reaping a pre-readiness store.
- Rebuilt the code collection the pin move stranded, which was the documented remedy carried in the failure message itself.

## Outcome

The start verb complies by construction: every success and every failure converges on one renderer each, so the branch deciding envelope against human lines exists once and cannot drift per path. No defect found, and none invented to have something to report.

The stranded collection was confirmed from the service's own job history before acting - an ingest verification failure naming an expected point count against a smaller applied one, on the collection carried across the storage-schema change.

## Notes

That job history also confirmed both classification fixes against real failures rather than constructed ones. The stranded-collection failure and a lock contention failure were both recorded as the catch-all kind, because the service predates the commits that classify them. The two fixes therefore have production evidence for the exact conditions they were written for.

The rebuild is derived data reconstructed from source, so it is reversible by recomputation rather than a destructive edit. It was run because the incremental path could not recover on its own: every update against that collection failed the same verification, so it was stale and staying stale.
