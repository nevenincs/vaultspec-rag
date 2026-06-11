---
tags: ['#exec', '#cli-service-operability-hardening']
date: '2026-06-11'
step_id: 'W02.S01'
related:
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-service-jobs-operability-adr]]'
---

# `cli-service-operability-hardening` W02.S01 - operator-grade jobs filters

## Step

Made the jobs surface bounded and filterable across HTTP, MCP, and CLI.

## Changes

- Added `/jobs` filters for `phase`, `source`, `trigger`, `query`, and `limit`.
- Added `total`, `returned`, `summary`, and `filters` metadata to the jobs response.
- Extended the MCP `get_jobs` tool and CLI HTTP admin client to pass the same filters.
- Added CLI options `--phase`, `--source`, `--trigger`, `--query/-q`, `--running`, and a default `--limit 20`.
- Reworked the Rich jobs table around compact ID/source/trigger/phase/age/detail columns.

## Verification

- `uv run pytest src/vaultspec_rag/tests/integration/test_service_jobs.py`
- `uv run vaultspec-rag index --type code --port 8766 --json`
- `uv run vaultspec-rag server jobs --limit 5 --json`
- `uv run vaultspec-rag server jobs --source code --trigger tool --query write --limit 5 --json`
- `uv run vaultspec-rag server jobs --running --limit 5 --json`

## Outcome

Operators can now ask for latest bounded jobs, running jobs, source/trigger-specific jobs, and text-filtered jobs instead of scrolling a fragile full-history table.

## Deferred

The registry still lacks OS user, wrapper identity, PID, and memory fields, so those cannot be truthfully surfaced yet.
