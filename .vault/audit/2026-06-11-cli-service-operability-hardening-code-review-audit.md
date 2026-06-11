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

### CR-4 | HIGH | Timeout diagnostics could fail while explaining a timeout

`_timeout_diagnostics` called `/health` and `/jobs` with bounded HTTP probes, but those
probes could raise network exceptions. Because `_try_http_search` returned the diagnostic
payload directly from its timeout handlers, a busy or unreachable service could still
produce an unstructured exception instead of the promised `http_search_timeout` JSON
contract.

**Disposition:** Fixed. Health and jobs probes now catch diagnostic-probe failures and
return `available: false` with an error class and message. A real network regression test
uses an unused localhost port and verifies the timeout envelope survives unavailable
diagnostic probes.

### CR-5 | MEDIUM | Backpressure diagnostics overstated what the jobs probe knew

The first Wave 04 implementation treated the sampled `/jobs?limit=5&phase=running`
response as authoritative and derived `active_indexing_conflict` from the returned row
count. That could undercount running jobs and could report false confidence when the jobs
probe failed.

**Disposition:** Fixed. Running count now prefers `summary.running` from the jobs route,
structured jobs errors become `available: false`, and `active_indexing_conflict` is
`null` when the probe cannot establish the count.

### CR-6 | LOW | Coarse timing does not satisfy full phase attribution

Wave 04 now emits `status_seconds`, `search_seconds`, `serialization_seconds`, and
`server_total_seconds`, but `search_seconds` still conflates embedding, Qdrant query,
rerank, graph rerank, and post-processing work.

**Disposition:** Accepted residual risk. The Wave 04 execution record already defers true
queue wait and internal phase timings to a later instrumentation slice.

### CR-7 | LOW | Timeout tests covered happy diagnostics before probe failure

The initial live-service timeout test used an idle service and an unrealistically short
timeout. That respected the no-fakes rule, but it did not cover diagnostic probe failure.

**Disposition:** Fixed. Added a real network test for unavailable diagnostic probes
without mocks, fakes, stubs, monkeypatching, skips, or xfails.

### CR-8 | HIGH | Jobs `--since` ignored progress update time

The first focused jobs-inspection implementation described `--since` as jobs updated
within the last N seconds, but the route filtered only by `finished_at` or `started_at`.
Long-running jobs with fresh progress could disappear from the liveness view once their
start time aged out.

**Disposition:** Fixed. The jobs route now uses `progress.last_updated` first, then
falls back to `finished_at` or `started_at`. Added a real route test that starts a job,
waits, records progress, and verifies the job is included by a short `since` window.

### CR-9 | MEDIUM | Job-id prefix detail could hide ambiguous matches

`server jobs --job-id <prefix>` rendered the first matching job in prose mode even when
the prefix matched multiple jobs. JSON returned all matches, but the human detail view
could point an operator at the wrong job.

**Disposition:** Fixed. Prose detail mode now exits with an invalid-filter error when a
job-id prefix matches multiple jobs and renders the matching table so the operator can
choose a longer prefix. The route test now verifies job-id prefixes can return multiple
matches.

### CR-10 | MEDIUM | Nested initiator metadata was not copied out of the registry

Adding `initiator` introduced a nested dictionary that `snapshot()` did not copy. In-process
consumers could mutate a snapshot and corrupt live registry metadata.

**Disposition:** Fixed. `snapshot()` now copies nested `initiator` dictionaries. The
registry independence test mutates the copied initiator and verifies the live registry is
unchanged.

### CR-11 | MEDIUM | Jobs initiator kind collapsed CLI and MCP into `tool`

Tool-triggered jobs initially reported `initiator.kind: tool`, which did not distinguish
CLI-started reindexing from MCP-started reindexing.

**Disposition:** Fixed for service-delegated CLI and MCP reindexing. CLI reindex payloads
now send `initiator_kind=cli`, MCP reindex tools send `initiator_kind=mcp`, and `/reindex`
passes that identity into the job registry. Watcher jobs remain `watcher`; service/default
jobs remain `service`. The MCP integration test asserts `mcp`; manual CLI testing confirms
`cli`.

### CR-12 | LOW | CLI `--since 0` did not round-trip

The CLI dropped optional values using truthiness, so `server jobs --since 0` omitted the
filter while MCP and direct HTTP could send `since=0`.

**Disposition:** Fixed. CLI jobs argument construction now preserves zero-valued options.

### CR-13 | MEDIUM | `server status --port` can ignore a healthy explicit port

`server status --port <port>` still gates the explicit-port probe on the PID recorded in
the current `service.json`. If that file is stale or belongs to a dead prior daemon,
`src/vaultspec_rag/cli/_service_lifecycle.py` sets `port_listening` to `False` before
probing the requested port, then reports `crashed_pid_dead` and recommends
`server logs --port <port>` even when `/health` on that port is ready.

This breaks the status/health parity goal from the status convergence ADR: an operator
who follows timeout remediation to inspect a known port can get a failed canonical
status result while `server health --port <port>` would succeed against the same service.
The port-only fallback only works when `service.json` is missing, not when it is stale.

**Disposition:** Fixed. Explicit `server status --port` handling now runs before
status-file signal evaluation. A stale `service.json` no longer blocks probing the
requested port, and the regression test covers a dead PID in `service.json` with a
healthy explicit localhost service.

### CR-14 | MEDIUM | Log filters can miss matching job lines outside the unfiltered tail

The new `/logs` and `/logs/json` filters read only the last requested `lines` first and
then apply `job_id`/`contains` filtering in `src/vaultspec_rag/server/_routes.py`. That
means `server logs --job-id <id>` with the default limit can return an empty success
response if the job line is just outside the last 200 unfiltered lines, even though the
operator supplied the exact job id.

This weakens the jobs/logs join promised by the jobs operability ADR. The matching log
line can be buried by unrelated watcher or lifecycle noise, and the JSON contract reports
`total: 0` for the filtered tail rather than making clear that the full log was not
searched. The added tests keep matching lines inside the requested tail, so they do not
cover this operator failure mode.

**Disposition:** Fixed. Filtered log requests now read the bounded maximum log window,
apply `job_id`/`contains`, then return the last requested filtered lines. The regression
test covers a matching job line outside the requested unfiltered tail.

## Verification

- `uv run pytest src/vaultspec_rag/tests/integration/test_service_jobs.py`
- `uv run pytest src/vaultspec_rag/tests/integration/test_service_state.py`
- `uv run pytest src/vaultspec_rag/tests/test_cli.py -k SearchTimeoutDefaults`
- `uv run ruff check` on touched files.
- `uv run pytest src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`
- Manual restarted-service checks:
  - `uv run vaultspec-rag server health --json`
  - `uv run vaultspec-rag index --type code --port 8766 --json`
  - `uv run vaultspec-rag server jobs --source codebase --limit 5 --json`
  - `uv run vaultspec-rag search "intentional short timeout diagnostics" --type code --json --max-results 2 --port 8766 --timeout 0.000001`

## Residual risks

- The jobs registry still does not capture OS user, wrapper identity, PID, or memory usage.
- Search timeout verification exercises helper behavior and a manual service search, but not
  a low-level assertion that the default propagates into `urlopen`.
- Some legacy tests still use direct token mutation around Starlette routes; a later
  hardening pass should add resident-service coverage for the status route family.
