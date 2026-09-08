---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:d006a2140ec4fcf91baeebbb87ea948f379b749d27337050c044dcf662756e46'
step_id: 'S28'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Record admission before blocking and expose bounded queued-request wait observations

## Scope

- `src/vaultspec_rag/server/_search_activity.py`

## Changes

- `M` `src/vaultspec_rag/server/_search_activity.py`
- `verify:` `uv run basedpyright src/vaultspec_rag/server/_search_activity.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_search_activity.py -q` -> `pass`
