---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S17'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Add the explicit --intent orientation or debug flag and its validation

## Scope

- `src/vaultspec_rag/cli/_search.py`

## Description

- Exposed explicit search intent in the CLI through an inline `intent:` query token
  (`intent:orientation` / `intent:debugging`) rather than a `--intent` flag.
- Added `intent` to the query-parser token pattern and key map in `search/_parsing.py`, and
  made the searcher prefer an explicit `intent` argument, falling back to the parsed
  `intent:` token, when selecting the profile.

## Outcome

`vaultspec-rag search "decision on gpu lock scope intent:debugging"` selects the debugging
profile; the token is stripped from the embedded query text. Verified by parser smoke test.
`ruff` and `ty` pass.

## Notes

A `--intent` Typer flag was implemented first but reverted: it pushed `handle_search` to 24
arguments, breaching the project's frozen `max-args = 23` lint ratchet ("never raise these"),
and the test mandate forbids lint skips. The inline token is consistent with the existing
`type:` / `lang:` filter-token UX and needs no new function argument. The displayed CLI scope
(`cli/_search.py`) therefore ended unchanged; the change landed in `_parsing.py` and
`_searcher.py`. No blockers.
