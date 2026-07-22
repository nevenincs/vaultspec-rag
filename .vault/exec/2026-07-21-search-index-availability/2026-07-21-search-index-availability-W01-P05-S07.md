---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S07'
related:
  - "[[2026-07-21-search-index-availability-plan]]"
---

# Add a real-service assertion that same-root work for another normalized source preserves empty HTTP 200 using Sol medium

## Scope

- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`

## Description

- Add a code search for the primary resolved root with an ordinary query and an include path that cannot match.
- Expand the concurrent executor and admission barrier to exactly three participants.
- Assert the exact stable HTTP 200 missing-code-index contract without matching-job evidence or a structured error.

## Outcome

The regression now proves source isolation alongside root isolation. Active vault work for
the primary root cannot turn an empty code search into index unavailability; the absent code
index remains an ordinary empty success with `status: missing` and
`empty.reason: index_missing`.

## Notes

All three probes cross the same real admission barrier after the exact rebuild reaches its
running or lease-held handshake. Formatting, lint, and strict BasedPyright checks passed.
The graphics processing unit acceptance run remains in the plan's dedicated acceptance
phase.
