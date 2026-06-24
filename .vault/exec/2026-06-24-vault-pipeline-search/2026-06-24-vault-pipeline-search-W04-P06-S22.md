---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S22'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---




# Thread the new params into the searcher entry points and apply them

## Scope

- `src/vaultspec_rag/search/_searcher.py`

## Description

- Added an `intent` parameter to the `api.search_vault` and `api.search_vault_timed`
  facades and forwarded it to the underlying `VaultSearcher` calls.

## Outcome

The public search facades (the searcher entry points used by the route, the CLI in-process
path, and the quality harness) now accept and apply an explicit intent, completing the
end-to-end thread from every adapter to the prior. `ruff` and `ty` pass.

## Notes

The searcher itself already accepted `intent` (S14) and resolves the parsed `intent:` token
when the argument is None (S17). No blockers.
