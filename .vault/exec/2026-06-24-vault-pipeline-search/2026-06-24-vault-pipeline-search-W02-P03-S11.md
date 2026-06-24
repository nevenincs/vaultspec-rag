---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S11'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Reindex and regression-test that status and related are present on results

## Scope

- `src/vaultspec_rag/tests/integration/test_vault_payload_fields.py`

## Description

- Authored `test_vault_payload_fields.py` (quality-marked), driving a freshly indexed
  synthetic corpus that now emits all three ADR heading formats and pipeline edges.
- Asserted: a modern-status ADR surfaces its exact status; the legacy no-marker ADR resolves
  to empty status; a linked document surfaces its related edges; and no result title leaks
  the `(**status:` marker.

## Outcome

All four tests pass on the real GPU index in ~41s. This confirms the W02 data layer
end-to-end: extraction, payload write, and result mapping for both status and related, with
the title-cleaning fix in place. `ruff` and `ty` pass.

## Notes

The synthetic fixture reindexes fresh each session, so it exercises the new extraction. The
long-lived running service indexed the real vault before this code landed; it must be
restarted and reindexed to populate status on the live index (the auto-reindexer reacts to
file changes, not to code changes). No blockers.
