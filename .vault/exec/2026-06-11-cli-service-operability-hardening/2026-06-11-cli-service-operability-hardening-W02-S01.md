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

## Follow-Up: Focused Inspection And Liveness

Added focused job inspection and liveness metadata across HTTP, MCP, and CLI:

- `/jobs?job_id=<prefix>` filters by job id prefix.
- `/jobs?failed=true` filters to `error` and `failed` phases.
- `/jobs?since=<seconds>` filters to jobs updated within the last N seconds.
- Job records include `initiator.kind`, `initiator.command`, and, for tool-triggered
  reindex jobs, `initiator.project_root`.
- Job responses include derived `runtime_seconds` and `last_progress_age_seconds`.
- `server jobs --job-id <prefix>` renders a detail table with runtime, last progress age,
  initiator, command, project root, progress, and result.
- `server jobs --failed` and `server jobs --since <seconds>` are available for focused
  operator queries.

Manual persona check after restarting the resident service to PID `66728` on port `8766`:

- `uv run vaultspec-rag index --type code --port 8766 --json`
- `uv run vaultspec-rag server jobs --json --limit 5 --port 8766`
- `uv run vaultspec-rag server jobs --running --json --port 8766`
- `uv run vaultspec-rag server jobs --job-id 528d077d --json --port 8766`
- `uv run vaultspec-rag server jobs --since 300 --json --port 8766`
- `uv run vaultspec-rag server jobs --job-id 528d077d --port 8766`
- `uv run vaultspec-rag server jobs --failed --json --port 8766`

Observed:

- job `528d077d826c4ee8b9663160d6e385e3`
- source `code`
- trigger `tool`
- initiator `cli`
- command `reindex_codebase`
- project root `vaultspec-rag\feature-server-supervision`
- runtime about 8.37s
- progress `write metadata (1/1)`
- failed filter returned an empty, bounded result with `failed: true` in filters.

Post-review corrections:

- `--since` now uses `progress.last_updated` before falling back to finish/start time.
- Job-id detail mode rejects ambiguous prefixes instead of silently showing the first
  match.
- `snapshot()` now copies nested initiator metadata.
- CLI and MCP reindex paths now identify themselves as `cli` and `mcp` respectively.
- `--since 0` is preserved by the CLI argument builder.

## Deferred

The registry still lacks OS user, wrapper identity, PID, and memory fields, so those cannot be truthfully surfaced yet.
