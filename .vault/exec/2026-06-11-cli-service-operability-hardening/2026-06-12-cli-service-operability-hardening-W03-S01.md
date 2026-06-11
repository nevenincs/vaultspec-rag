---
tags: ['#exec', '#cli-service-operability-hardening']
date: '2026-06-12'
step_id: 'W03.S01'
related:
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-search-freshness-and-empty-results-adr]]'
---

# `cli-service-operability-hardening` W03.S01 - search empty-result diagnostics

## Step

Implemented the first Wave 03 slice: service-backed search responses now include
actionable index state and empty-result recovery guidance.

## Changes

- Added service search `index_state` metadata:
  - `source`,
  - `indexed_count`,
  - `vault_count`,
  - `code_count`,
  - `indexed_target_root`,
  - `requested_target_root`,
  - `target_matches`,
  - `status`.
- Added `empty` diagnostics for zero-result searches with:
  - `reason`,
  - `message`,
  - `remediation`.
- Preserved successful service response metadata in the CLI instead of collapsing it to a
  bare result list.
- Added prose rendering for empty service results, including reason, next actions, and
  target/count context.
- Converted invalid search project roots from HTTP 500 into structured `bad_request`
  responses.
- Normalized direct HTTP `type="code"` search diagnostics so code searches report code
  index state instead of vault index state.

## Verification

- `uv run pytest src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`
- `uv run pytest src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py src/vaultspec_rag/tests/integration/test_service_state.py`
- `uv run pytest src/vaultspec_rag/tests/integration/test_service_jobs.py`
- `uv run pytest src/vaultspec_rag/tests/test_cli.py -k SearchTimeoutDefaults`
- `uv run ruff check src/vaultspec_rag/server/_routes.py src/vaultspec_rag/cli/_http_search.py src/vaultspec_rag/cli/_search.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`

## Manual Persona Test

Persona: Agent searching for implementation locations in a codebase that may not be
indexed yet.

Commands:

- `uv run vaultspec-rag server stop`
- `uv run vaultspec-rag server start`
- `uv run vaultspec-rag --target $root search "health jobs logs" --type vault --json --port 8766 --timeout 120`
- `uv run vaultspec-rag --target $root search "health jobs logs" --type vault --port 8766 --timeout 120`
- `uv run vaultspec-rag search "search diagnostics empty index_state" --type code --json --max-results 3 --port 8766 --timeout 120`

Observed:

- The first manual setup without `.vaultspec/` failed at the workspace resolver before
  reaching the service. After adding `.vaultspec/`, the service-backed empty search
  returned `index_state.status=missing` and `empty.reason=index_missing`.
- Human output included the no-results reason, next actions, indexed count, requested
  target, and indexed target.
- A normal service-backed code search still returned ranked results and included
  `index_state.status=available`.

## Outcome

Empty service-backed searches no longer look like silent failure when the requested
index source is missing. The user gets a machine-readable reason and safe recovery
commands.

## Deferred

- No last-indexed timestamp exists yet, so this slice cannot distinguish stale from
  merely available.
- Target mismatch diagnostics need a real source of independently recorded index target
  identity before they can be implemented truthfully.
