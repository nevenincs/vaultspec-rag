---
tags: ['#audit', '#cli-service-operability-hardening']
date: '2026-06-11'
related:
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-service-status-convergence-adr]]'
  - '[[2026-06-11-service-jobs-operability-adr]]'
  - '[[2026-06-11-server-bound-search-production-readiness-adr]]'
---

# `cli-service-operability-hardening` code review audit

## Scope

Reviewed the first rollout slice for:

- service health CLI parity,
- project-root-aware service info,
- jobs filters and bounded display,
- service-bound search timeout defaults.

## Findings

### CR-1 | MEDIUM | Running jobs could still be hidden by completed history

`/jobs` originally filtered and applied `limit` against newest-first history only.
A long-running older job could be pushed out of the default `server jobs` view by newer
completed watcher jobs.

**Disposition:** Fixed. `/jobs` now prioritises `phase == "running"` before applying the
limit while preserving recency inside the running and non-running groups.

### CR-2 | MEDIUM | `server info` reported missing project context before stopped service

`server info --json` originally validated project root before consulting the default
service port. When the service was stopped and no project root was provided, the first
error could be `project_root_required` rather than `service_not_running`.

**Disposition:** Fixed. `server info` now checks for a running/default service port before
requiring project root when `--port` is not supplied.

### CR-3 | LOW | Jobs source filter did not accept `codebase`

The implementation only accepted the internal `source=code` value. Other public surfaces
use `codebase`, so API/MCP callers could reasonably pass `source=codebase` and receive an
empty result.

**Disposition:** Fixed. `source=codebase` now normalises to `source=code`; response
metadata reports the normalised filter.

## Verification

- `uv run pytest src/vaultspec_rag/tests/integration/test_service_jobs.py`
- `uv run pytest src/vaultspec_rag/tests/integration/test_service_state.py`
- `uv run pytest src/vaultspec_rag/tests/test_cli.py -k SearchTimeoutDefaults`
- `uv run ruff check` on touched files.
- Manual restarted-service checks:
  - `uv run vaultspec-rag server health --json`
  - `uv run vaultspec-rag index --type code --port 8766 --json`
  - `uv run vaultspec-rag server jobs --source codebase --limit 5 --json`

## Residual risks

- The jobs registry still does not capture OS user, wrapper identity, PID, or memory usage.
- Search timeout verification exercises helper behavior and a manual service search, but not
  a low-level assertion that the default propagates into `urlopen`.
- Some legacy tests still use direct token mutation around Starlette routes; a later
  hardening pass should add resident-service coverage for the status route family.
