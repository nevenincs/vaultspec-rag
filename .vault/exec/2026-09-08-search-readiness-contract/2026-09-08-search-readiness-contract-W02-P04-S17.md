---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:52f4f140eebba2160b36dd41115c5d422e8325bd9916762d36f83c620da3584f'
step_id: 'S17'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Prove freshness-wait configuration defaults overrides and upper-bound validation

## Scope

- `src/vaultspec_rag/tests/test_config.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_config.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/test_config.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_config.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_config.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_config.py -k search_freshness_wait_max --disable-warnings` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_config.py --disable-warnings` -> `pass`
- `verify:` `git diff --check` -> `pass`
