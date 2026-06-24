---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S19'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---




# Add the --status control with the default active set and opt-in widening

## Scope

- `src/vaultspec_rag/cli/_search.py`

## Description

- Added a `status:` query token to the parser (key map -> `status`).
- Added `apply_status_filter(results, spec)` to `_intent_rank.py`: `all`/empty is a no-op,
  `active` keeps active-status ADRs, an explicit comma set keeps matching-status ADRs; every
  non-ADR result is always retained (only ADRs carry status).
- Wired the filter into the searcher after the intent prior, gated on a `status:` token.

## Outcome

Status is now manually controllable: `status:active` or `status:accepted` narrows ADRs to
active/accepted while keeping research/plan/exec; `status:all` shows everything. Verified:
active and accepted drop a superseded ADR but keep a research doc; all keeps both ADRs.
`ruff` and `ty` pass.

## Notes

The default (no token) leaves results unfiltered - the intent prior already surfaces active
ADRs and deranks inactive ones, so the filter is the explicit opt-in narrowing the ADR D5
calls for, exposed via the token to respect the max-args ratchet. No blockers.
