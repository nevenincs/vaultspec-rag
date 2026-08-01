---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:e50122c3f556813ffb8518037ae4a56d426b59a72c6e502ed8ffe19885ab3239'
step_id: 'S89'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify invalid routing leaves real collections, sidecars, ledger rows, and caches unchanged

## Scope

- `src/vaultspec_rag/tests/integration/test_content_policy_fail_closed.py`

## Description

- Seed a real local code collection, metadata sidecar, and extraction-cache
  sentinel before exercising conflicting explicit ownership.
- Exercise both full and incremental public index operations and assert the
  collection, sidecar, and cache remain byte-for-byte unchanged.
- Invoke the public application programming interface in a fresh interpreter
  with model execution unavailable and verify routing refusal precedes model,
  store, or project-state acquisition.
- Exercise service job admission against invalid routing and compare the real
  canonical job snapshot and durable JSON state before and after refusal.

## Outcome

Invalid policy and conflicting ownership fail before observable mutation.
Existing collection identifiers, metadata bytes, cache bytes, canonical jobs,
durable job state, and the project storage directory retain their prior state.

Commit `b0236fe` lands the real collection, sidecar, cache, and durable-job
refusal coverage that supplies this step's implementation evidence.

The W01.P01 phase-boundary invocation passed all 50 policy, preprocessing,
fingerprint, and fail-closed tests, including four real-resource S89 cases.

## Notes

The tests use real temporary files, a real local vector store, and a fresh
Python subprocess. They contain no fake, mock, stub, patch, monkeypatch, skip,
or expected-failure shortcut. No CUDA execution or shared service storage was
used.
