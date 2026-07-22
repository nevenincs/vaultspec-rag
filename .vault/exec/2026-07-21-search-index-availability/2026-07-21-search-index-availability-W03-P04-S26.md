---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S26'
related:
  - "[[2026-07-21-search-index-availability-plan]]"
---

# Convert a matching rebuild collection-disappearance race into the canonical structured HTTP 503 response using Terra xhigh

## Scope

- `src/vaultspec_rag/server/_routes.py`
- `src/vaultspec_rag/server/_search_availability.py`
- `src/vaultspec_rag/tests/test_search_availability.py`
- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`

## Description

- Recognize only structured Qdrant collection-missing HTTP 404 responses.
- Reuse exact root/source canonical nonterminal evidence to produce the canonical HTTP 503.
- Re-raise declined backend failures and unify normal and recovered route completion.
- Add focused real-object conversion and decline coverage, then rerun immutable acceptance.

## Outcome

Commit `fe1e007b0abcbb92feeaa31bb9672978dc1e5bb3` closes the observed race. A matching
collection disappearance now returns `index_unavailable`; non-404 responses and a
collection-missing 404 without exact matching job evidence are declined. One frozen
classification drives body, status, watcher, metrics, and bounded log evidence, with
`availability_cause=collection_missing` retained as log-only diagnostics.

Ruff was clean, BasedPyright reported zero errors, warnings, or notes, 33 focused tests and 116
adjacent tests passed, and local real-Qdrant/GPU acceptance passed with one selected test and
seven deselected in 59.90 seconds.

## Notes

The preserved pre-fix trace shows a real Qdrant collection-missing 404 escaping as HTTP 500.
The GPU regression was reused unchanged and need not hit that narrow window deterministically;
focused tests with real `UnexpectedResponse` and `JobManager` objects establish the branch and
its negative guards. No fake, mock, stub, patch, monkeypatch, skip, or expected failure was added.
