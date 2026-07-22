---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S06'
related:
  - "[[2026-07-21-search-index-availability-plan]]"
---

# Add a real-service assertion that same-source work for another resolved project root preserves empty HTTP 200 using Sol medium

## Scope

- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`

## Description

- Create a distinct resolved project root containing only an empty `.vault` directory.
- Admit its vault search concurrently with the matching-root empty probe after the deterministic running-job handshake.
- Assert the exact stable HTTP 200 missing-index contract and exclude structured unavailable fields and matching-job evidence.

## Outcome

Same-source work for the primary root no longer contaminates the unrelated-root assertion.
The secondary root must return an ordinary empty success with a six-field vault index state,
zero indexed items, `status: missing`, and `empty.reason: index_missing`.

## Notes

The two requests share a real daemon and cross a two-party barrier before issuing HTTP.
Formatting, lint, and strict BasedPyright checks passed. The graphics processing unit
acceptance run remains in the plan's dedicated acceptance phase.
