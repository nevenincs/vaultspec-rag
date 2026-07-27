---
tags: ['#exec', '#cli-service-operability-hardening']
date: '2026-06-11'
modified: '2026-07-27'
related:
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-service-jobs-operability-adr]]'
---

# `cli-service-operability-hardening` W02.S01 - operator-grade jobs filters

## Description

### Step

Made the jobs surface bounded and filterable across HTTP, MCP, and CLI.

### Changes

- Added `/jobs` filters for `phase`, `source`, `trigger`, `query`, and `limit`.
- Added `total`, `returned`, `summary`, and `filters` metadata to the jobs response.
- Extended the MCP `get_jobs` tool and CLI HTTP admin client to pass the same filters.
- Added CLI options `--phase`, `--source`, `--trigger`, `--query/-q`, `--running`, and a default `--limit 20`.
- Reworked the Rich jobs table around compact ID/source/trigger/phase/age/detail columns.

### Verification

- `uv run pytest src/vaultspec_rag/tests/integration/test_service_jobs.py`
- `uv run vaultspec-rag index --type code --port 8766 --json`
- `uv run vaultspec-rag server jobs --limit 5 --json`
- `uv run vaultspec-rag server jobs --source code --trigger tool --query write --limit 5 --json`
- `uv run vaultspec-rag server jobs --running --limit 5 --json`

## Outcome

Operators can now ask for latest bounded jobs, running jobs, source/trigger-specific jobs, and text-filtered jobs instead of scrolling a fragile full-history table.

## Notes

### Follow-Up: Focused Inspection And Liveness

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
- project root `C:\projects\worktrees\feature-server-supervision`
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

### Deferred

The registry still lacks OS user, wrapper identity, PID, and memory fields, so those cannot be truthfully surfaced yet.

### Follow-Up: Runtime Ownership And Resource Context

Implemented the missing job ownership/resource context across the registry, HTTP route,
status summary, and CLI detail view:

- Job records now include `runtime.pid`, `runtime.parent_pid`, `runtime.user`,
  `runtime.executable`, `runtime.prefix`, `runtime.base_prefix`, and `runtime.virtual_env`.
- Job records now include resource snapshots with RSS, CUDA allocated memory, and CUDA
  reserved memory at job start and finish.
- Running jobs are enriched with a current resource snapshot in the `/jobs` response.
- Job summaries now include `initiators`, `active_initiators`, and `users` buckets.
- `server jobs` compact table includes an owner column such as `cli/hello`.
- `server jobs --job-id <prefix>` renders PID, OS user, executable, virtualenv, and
  resource usage.
- `/health`, heartbeat, and `server start` now publish/persist the serving daemon PID
  rather than leaving `service.json` pinned to the Windows venv launcher PID.
- `server status --json` carries the same health PID and operational jobs initiator/user
  rollups, so status and jobs agree about the active service process.

Verification:

- `uv run ruff check src/vaultspec_rag/jobs.py src/vaultspec_rag/server/_jobs.py src/vaultspec_rag/server/_routes.py src/vaultspec_rag/server/_lifespan.py src/vaultspec_rag/server/_lifecycle.py src/vaultspec_rag/server/_models.py src/vaultspec_rag/cli/_service_jobs.py src/vaultspec_rag/cli/_service_lifecycle.py src/vaultspec_rag/cli/_service_status.py src/vaultspec_rag/cli/__init__.py src/vaultspec_rag/tests/integration/test_jobs_registry.py src/vaultspec_rag/tests/integration/test_service_jobs.py src/vaultspec_rag/tests/integration/test_service_lifecycle.py`
- `uv run ty check src/vaultspec_rag/jobs.py src/vaultspec_rag/server/_jobs.py src/vaultspec_rag/server/_routes.py src/vaultspec_rag/server/_lifespan.py src/vaultspec_rag/server/_lifecycle.py src/vaultspec_rag/server/_models.py src/vaultspec_rag/cli/_service_jobs.py src/vaultspec_rag/cli/_service_lifecycle.py src/vaultspec_rag/cli/_service_status.py src/vaultspec_rag/cli/__init__.py src/vaultspec_rag/tests/integration/test_jobs_registry.py src/vaultspec_rag/tests/integration/test_service_jobs.py src/vaultspec_rag/tests/integration/test_service_lifecycle.py`
- `uv run --no-sync python tools/complexity_gate.py`
- `uv run pytest src/vaultspec_rag/tests/integration/test_service_lifecycle.py::test_stale_pid_recovery src/vaultspec_rag/tests/integration/test_service_lifecycle.py::test_service_status_running src/vaultspec_rag/tests/integration/test_jobs_registry.py src/vaultspec_rag/tests/integration/test_service_jobs.py`
- `uv run vaultspec-rag server stop`
- `uv run vaultspec-rag server start --port 8766`
- `uv run vaultspec-rag index --type vault --port 8766 --json`
- `uv run vaultspec-rag server jobs --json --port 8766 --job-id 7d4f1c64 --limit 5`
- `uv run vaultspec-rag server jobs --port 8766 --job-id 7d4f1c64`
- `uv run vaultspec-rag server status --json --port 8766`

Observed:

- `server status` and `/health` agreed on serving PID `60276` during manual validation.
- The job detail for `7d4f1c646d3b4412bc48b98d4dfa7626` reported `initiator.kind: cli`,
  OS user `hello`, PID `60276`, `.venv` executable/prefix metadata, RSS `2311.3 MB`,
  CUDA allocated `3520.1 MB`, and CUDA reserved `3532.0 MB`.
- The final resident service was restarted on port `8766` with serving PID `32848`.

### Follow-Up: Logs Filtering Parity

Implemented a small logs parity slice so operators can narrow the service log without
dumping the whole tail:

- `GET /logs` and `GET /logs/json` accept `job_id` and `contains` query filters.
- `vaultspec-rag server logs` exposes `--job-id` and `--contains`.
- MCP `get_logs` accepts the same optional filters.
- JSON log responses now include `lines`, `total`, and `filters`.

Verification:

- `uv run ruff check src/vaultspec_rag/server/_routes.py src/vaultspec_rag/cli/_http_search.py src/vaultspec_rag/cli/_service_logs.py src/vaultspec_rag/mcp/_admin_tools.py src/vaultspec_rag/tests/integration/test_service_logs.py src/vaultspec_rag/tests/test_http_search_routing.py`
- `uv run ty check src/vaultspec_rag/server/_routes.py src/vaultspec_rag/cli/_http_search.py src/vaultspec_rag/cli/_service_logs.py src/vaultspec_rag/mcp/_admin_tools.py src/vaultspec_rag/tests/integration/test_service_logs.py src/vaultspec_rag/tests/test_http_search_routing.py`
- `uv run pytest src/vaultspec_rag/tests/integration/test_service_logs.py src/vaultspec_rag/tests/test_http_search_routing.py`
- `uv run vaultspec-rag server stop`
- `uv run vaultspec-rag server start --port 8766`
- `uv run vaultspec-rag server status --json --port 8766`
- `uv run vaultspec-rag server logs --json --lines 80 --contains service.lifecycle --port 8766`
- `uv run vaultspec-rag server logs --lines 80 --contains service.lifecycle --port 8766`
- `uv run vaultspec-rag server logs --json --lines 80 --job-id nonexistent-job --port 8766`

Observed against current resident service PID `64688` on port `8766`:

- Filtered JSON included `filters: {"contains": "service.lifecycle"}` and a bounded
  `total`.
- Human output only showed matching lifecycle lines.
- A non-matching `--job-id` returned `ok: true` with `lines: []`, `total: 0`, and the
  selected filter metadata.

Post-review correction:

- Filtered log requests now search the bounded maximum log window before applying the
  requested tail size. This prevents `server logs --job-id <id>` from returning empty
  just because unrelated recent log noise pushed the matching job line outside the last
  N unfiltered lines.
