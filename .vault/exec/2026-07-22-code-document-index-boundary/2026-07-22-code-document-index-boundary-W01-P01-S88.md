---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S88'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Gate index and job entry points on a valid resolved policy before acquiring store, ledger, cache, writer, or GPU mutation authority

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `src/vaultspec_rag/jobs.py`

## Description

- Resolve one read-only `CodeIndexPreflight` containing the immutable policy and
  its discovered code work before mutation authority is available.
- Forward that exact preflight through the public API, canonical job admission,
  dispatch, restart restoration, and full or incremental index execution.
- Reject missing, wrong-root, inconsistent-fingerprint, and out-of-root
  preflights before the writer lock or collection path is entered.
- Reuse preflight discovery instead of rescanning after model and project-store
  acquisition.
- Remove impossible optional epoch branches so the policy-bound metadata writer
  remains clean under strict type analysis.

## Outcome

Invalid or unmigrated routing now fails at the API and job front doors before
registry model loading, project-store leasing, durable job creation, writer
locking, cache clearing, collection preparation, or GPU execution. Valid jobs
retain the exact resolved policy and discovered paths that admission approved;
restart restoration resolves one fresh preflight before rebinding work.

Commit `b0236fe` lands policy validation ahead of durable service-job mutation,
commit `3602ee9` lands the shared read-only preflight before index writer
authority, and commit `95e9b05` carries the immutable policy through execution
and publication.

The W01.P01 phase-boundary invocation passed all 50 policy, preprocessing,
fingerprint, and fail-closed tests. Focused Ruff and Ty checks reported no
finding in the S88 implementation scope.

## Notes

The initial semantic discovery request timed out after 74 seconds while the
resident index service was saturated, so source grounding continued with
targeted symbol search and full epicentre reads. Shared commit `3602ee9`
cross-committed the indexer half of this step with watcher policy-snapshot work;
the remaining API and service-domain changes retain that commit as ancestor
traceability. No destructive Git command, stash operation, model load, or CUDA
test was used.
