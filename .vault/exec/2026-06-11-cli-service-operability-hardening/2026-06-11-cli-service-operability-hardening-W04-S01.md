---
tags: ['#exec', '#cli-service-operability-hardening']
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'W04.S01'
related:
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-server-bound-search-production-readiness-adr]]'
---

# `cli-service-operability-hardening` W04.S01 - service search timeout hardening

## Step

Raised the service-bound search timeout default and manually rolled the service.

## Changes

- Added `DEFAULT_SEARCH_TIMEOUT_SECONDS = 300.0`.
- Changed default and invalid-env fallback behavior from 10 seconds to 300 seconds.
- Updated `search --timeout` help to disclose the default and environment override.

## Verification

- `uv run pytest src/vaultspec_rag/tests/test_cli.py -k SearchTimeoutDefaults`
- `uv run ruff check` on touched source and test files.
- `uv run vaultspec-rag server stop`
- `uv run vaultspec-rag server start`
- `uv run vaultspec-rag search "server jobs filter phase query health" --type code --json --max-results 3 --port 8766`

## Outcome

The restarted local service is running the current implementation, and default service searches no longer inherit the previous 10-second budget.
