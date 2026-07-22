---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S19'
related:
  - "[[2026-07-21-search-index-availability-plan]]"
---

# Implement bounded root and source job matching plus the structured unavailable response using Terra xhigh

## Scope

- `src/vaultspec_rag/server/_search_availability.py`

## Description

- Normalize canonical and compatibility job snapshots without importing lifecycle code.
- Match nonterminal index work by exact resolved root and normalized source.
- Merge post-search evidence before pre-search evidence by stable job identifier.
- Bound public job references while retaining pre-truncation rebuild evidence.
- Build the exact structured index-unavailable response and remediation.

## Outcome

Implemented `build_index_unavailable_response` in a CPU-only server helper. Focused Ruff
formatting and lint checks passed, basedpyright reported no errors, and independent review
approved the implementation against the accepted response contract.

## Notes

Malformed records with a `spec` key are ignored instead of falling back to compatibility
fields. Compatibility records never infer rebuild mode. No registry or lifecycle state was
introduced.
