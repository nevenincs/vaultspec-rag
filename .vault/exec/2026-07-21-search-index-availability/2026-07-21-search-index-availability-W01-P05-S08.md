---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S08'
related:
  - "[[2026-07-21-search-index-availability-plan]]"
---

# Add a real-service assertion that matching nonterminal work preserves usable nonempty HTTP 200 using Sol medium

## Scope

- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`

## Description

- Select the first generated manifest document and use its unique needle in a matching-root vault search.
- Admit the nonempty request through the same four-party barrier as the existing empty probes.
- Assert HTTP 200 and require a real result with the selected manifest document identity.

## Outcome

The real-daemon regression now preserves useful search results while matching index work is
nonterminal. A known indexed document remains observable as an ordinary HTTP success rather
than being converted to the structured unavailable envelope.

## Notes

Formatting, lint, and strict BasedPyright checks passed. The graphics processing unit run
remains held for the review gate and the plan's dedicated acceptance phase.
