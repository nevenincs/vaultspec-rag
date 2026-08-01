---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:c5062a622143d377b4da38507d5282ddf24d92ae6a1f369a8ea627840a5d7eb4'
step_id: 'S08'
related:
  - "[[2026-07-21-search-index-availability-plan]]"
---

# Add a real-service assertion that matching nonterminal work preserves usable nonempty HTTP 200 using Sol medium

## Scope

- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`

## Description

- Select the first generated manifest document and use its unique needle in a matching-root vault search.
- Publish the real baseline, restart with a matching rebuild persisted in `paused` state, and
  issue the nonempty request against the unchanged storage.
- Assert HTTP 200 and require a real result with the selected manifest document identity.

## Outcome

The real-daemon regression preserves useful search results while matching index work is
nonterminal. A known indexed document remains an ordinary HTTP 200, the completed log names the
exact paused job, and the job revision remains unchanged.

## Notes

Final immutable acceptance passed Ruff, strict BasedPyright, 33 focused tests, 116 adjacent
tests, and the local graphics processing unit regression with one passed and seven deselected.
