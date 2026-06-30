---
tags:
  - '#audit'
  - '#cli-service-operability-hardening'
date: '2026-06-11'
modified: '2026-06-30'
related:
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
---

# VaultSpec RAG CLI and Service UX Audit

Date: 2026-06-11
Audience: VaultSpec RAG maintainers
Basis: Direct Codex user journey while trying to discover the implementation shape for server and CLI health, jobs, and logs using `vaultspec-rag`.

## Executive Summary

The current VaultSpec RAG CLI and resident service are powerful enough to support semantic codebase discovery, but the user experience is brittle under normal agent workflows.

The rough edges are not cosmetic. They change the user's ability to reason about the system. A user can hit empty search results, search timeouts, lock errors, route contract mismatches, oversized job output, and stale index ambiguity before they understand whether the tool is working, overloaded, stale, or being called incorrectly.

The session eventually succeeded, but only after manual inference:

- The resident service was running and healthy.
- The initial service-backed semantic searches returned empty results.
- A parallel search batch saturated or queued behind the service enough for every call to time out.
- Local status could not run because the service owned the Qdrant lock.
- `server info` returned a wrapped bad request because the route wanted a project root that the CLI command does not expose.
- A code index dry-run showed 306 indexable files.
- A service-backed code index refresh was needed.
- Job polling showed the refresh running, then stalling from the user's point of view, then completing.
- Only after that did semantic discovery produce useful code locations.

This is a real user journey through the CLI. The observed failures should become product work, not just documentation notes.

## Scope And Evidence

This audit covers the user-facing CLI and localhost service surfaces encountered while discovering:

- Server health
- Server jobs
- Server logs
- CLI health
- CLI jobs
- CLI logs

Commands used through `vaultspec-rag` included:

- `vaultspec-rag --help`
- `vaultspec-rag search --help`
- `vaultspec-rag server status --json`
- `vaultspec-rag search ... --type code --json --port 8766`
- `vaultspec-rag status --json`
- `vaultspec-rag server info --json --port 8766`
- `vaultspec-rag index --type code --dry-run --json`
- `vaultspec-rag index --type code --port 8766 --json`
- `vaultspec-rag server jobs --json --port 8766`
- `vaultspec-rag server jobs --json --limit 1 --port 8766`
- `vaultspec-rag server logs --json --lines 80 --port 8766`

The service reported itself as running and ready on port `8766` with CUDA available, models loaded, one project, and backend capabilities showing:

- Backend: `qdrant-local`
- Concurrent search supported: `true`
- Same-project search strategy: `serialized`
- Cross-project search strategy: `parallel`
- Local storage process model: `exclusive`

Those capabilities were available, but they were not surfaced at the point where they mattered most: when parallel same-project searches timed out.

## Reconstructed User Journey

### 1. Initial discovery started with plain code inspection

The first pass used direct repository inspection. That was the wrong workflow for this test because the goal was to experience VaultSpec RAG as the discovery tool.

User correction: use `vaultspec-rag` only.

UX note: this exposed a realistic agent failure mode. When RAG does not make its own route obvious or trustworthy, agents and developers fall back to filesystem search. The product should make the RAG path easier than bypassing it.

### 2. CLI help showed the broad command surface

`vaultspec-rag --help` showed `search`, `status`, and `server` as the relevant surfaces.

`vaultspec-rag search --help` showed service delegation through `--port`, timeout configuration through `--timeout`, and JSON output.

UX note: the command reference exists, but it does not tell the user how to diagnose the common state machine: service running, index stale, service busy, local lock held, or route requires target.

### 3. Service status was healthy

`vaultspec-rag server status --json` returned a running service:

- `state`: `running`
- `status`: `ready`
- `cuda`: `true`
- `models_loaded`: `true`
- `port`: `8766`
- `service_token_match`: `true`

UX note: this gave confidence that service-backed search should work. That made the next failure more confusing.

### 4. Parallel service-backed semantic searches timed out

Six code searches were launched in parallel against port `8766`. All failed with:

`HTTP search on port 8766 timed out after 10.0s.`

This is a major user experience failure. The service itself says same-project search is serialized, but the CLI allowed an agent workflow to fire parallel same-project searches without any warning, queue visibility, or targeted error message.

The timeout message did not suggest:

- The service may be busy.
- Same-project searches serialize.
- Retry with fewer concurrent calls.
- Retry with `--timeout`.
- Check `vaultspec-rag server jobs`.
- Check `vaultspec-rag server status`.
- Check whether an index refresh is in progress.

The user had to infer all of that.

### 5. Empty search results looked like absence instead of stale index

Focused code searches for exact health symbols returned:

`"results": []`

At this point, the service was healthy, but search was not useful. The CLI did not indicate whether:

- The code index was missing.
- The code index was stale.
- The current target was not the target indexed by the service.
- The query was too exact.
- The service had no code collection for this workspace.
- The service was using an older index.

The user had to discover this by running an index dry-run and then refreshing the code index.

### 6. Local `status` hit the Qdrant lock

`vaultspec-rag status --json` failed because the resident service owned local Qdrant storage:

`Cannot query index status - another process holds the lock`

This message was technically useful, but the larger workflow was still rough. The user wanted to know whether the service index was current. The CLI exposed a local status command that could not answer while the service was running.

UX note: when a resident service owns the store, local status should either delegate to the service or clearly point to the equivalent service-safe command.

### 7. `server info` had a route and CLI contract mismatch

`vaultspec-rag server info --json --port 8766` returned:

```json
{
  "ok": true,
  "command": "service.info",
  "data": {
    "ok": false,
    "error": "bad_request",
    "message": "project_root is required - supply it in the request body (POST) or as a query parameter (GET)."
  }
}
```

This is a bad shape for users and agents:

- The outer command says `ok: true`.
- The inner service response says `ok: false`.
- The command has no visible `--project-root` option.
- Passing global `--target .` did not fix the request.

UX note: this is a direct parity gap. A CLI command wraps a service route but does not expose the route's required input.

### 8. Index dry-run revealed the likely issue

`vaultspec-rag index --type code --dry-run --json` found 306 files.

This was the first strong signal that the codebase was available and indexable. That signal came too late and required the user to know which command to try.

UX note: empty code search results should have suggested this path automatically.

### 9. Code index refresh succeeded but needed manual job polling

`vaultspec-rag index --type code --port 8766 --json` started a service-backed background job:

`codebase_job_id: 898e175f635745cca1adbdc2ff6ff0d3`

The user then had to poll:

- `vaultspec-rag server jobs --json --port 8766`
- `vaultspec-rag server jobs --json --limit 1 --port 8766`
- `vaultspec-rag server logs --json --lines 80 --port 8766`

The job initially advanced, then appeared stuck at `2240 / 4042` chunks for multiple polls, with no CLI-level explanation that a larger batch or Qdrant upsert could take time.

It eventually completed:

`+306 /0 -0 (269937ms)`

UX note: job progress existed, but the default jobs view was noisy and the job state did not provide enough liveness detail for a user staring at an unchanged counter.

### 10. Semantic discovery worked after refresh

After the index refresh, semantic code search found the relevant implementation locations:

- `src/vaultspec_rag/server/_lifespan.py`
- `src/vaultspec_rag/server/_routes.py`
- `src/vaultspec_rag/server/_main.py`
- `src/vaultspec_rag/jobs.py`
- `src/vaultspec_rag/logging_config.py`
- `src/vaultspec_rag/cli/_service_logs.py`
- `src/vaultspec_rag/cli/_service_jobs.py`
- `src/vaultspec_rag/cli/_service_lifecycle.py`
- `src/vaultspec_rag/cli/_process.py`
- `src/vaultspec_rag/cli/_http_search.py`
- `src/vaultspec_rag/mcp/_admin_tools.py`

UX note: the successful state is good. The path to reach it is too obscure.

## Audit Findings

### User Findings Added After Initial Audit

The following findings came directly from user review and should be treated as primary
product feedback, not secondary commentary:

- The `server jobs` table is the wrong format for inspecting jobs. A Typer/Rich table is
  fragile in terminals and does not efficiently expose the current job state.
- The jobs interface is too simplistic. It does not provide meaningful filtering,
  searching, or scoped limits for the question the user is actually asking.
- The jobs surface does not identify who or what initiated a job beyond a basic trigger
  label. It does not cross-reference active wrappers, active commands, or current memory
  usage.
- The information shown is not actionable. It is mostly a basic activity dump rather than
  an operational view.
- The default command-line experience makes it hard to see the latest jobs or currently
  running jobs because long history dominates the output.
- There are too many overlapping status-like interfaces: job info, status, logs, and
  health. The names and responsibilities conflict instead of forming one coherent
  operational model.
- CLI and server status surfaces need to converge on cross-referenced, standardized
  usage. Simpler, more consistent, and more conformant to command-line norms is better.
- The default search timeout is wrong for the current server-bound behavior. A 10-second
  default is too low for serialized or queued service-backed work, especially in agent
  workflows.
- Raising the timeout must not become a way to hide a performance regression. The current
  server-bound path appears suspiciously slow compared with prior benchmarking where RAG
  was near-instantaneous.
- In its current form, the server-bound RAG experience does not feel production usable.
- The CLI still appears to route through MCP-flavoured admin concepts even when the user
  is not doing anything related to the Model Context Protocol. That suggests previous
  deconflation work has not fully removed business logic from MCP-shaped implementation
  paths.
- The current shape is not acceptable as an operator interface.

### F1. Parallel same-project service searches can saturate or serialize into total timeout

Severity: Critical

Symptom: Six parallel `vaultspec-rag search --port 8766` calls all timed out after 10 seconds.

Evidence: The service status reported same-project search strategy as `serialized`, but the CLI permitted parallel calls with no warning or queue feedback.

Impact: Agent workflows naturally parallelize discovery queries. The current service behavior turns that into a wall of identical timeout failures.

Likely cause: The CLI treats each search independently and does not coordinate same-project concurrency. The service serializes same-project work internally, but the client does not expose queueing or backpressure.

Proposed fix:

- Add explicit busy/queued responses or progress messages for same-project serialized searches.
- Increase or adapt default timeout when the service reports serialized same-project behavior.
- Add timeout remediation text: reduce parallelism, increase `--timeout`, check `server jobs`, check `server status`.
- Consider client-side backpressure for agent-oriented search batches.

### F2. Timeout errors are technically correct but operationally weak

Severity: High

Symptom: Timeout output only said the HTTP search timed out after 10 seconds.

Impact: The user did not know whether the service was down, overloaded, stale, locked, indexing, or simply slow.

Proposed fix:

- Include service status summary in timeout diagnostics when possible.
- Include whether the service is ready, whether jobs are running, and whether same-project search is serialized.
- Suggest the exact next command.

Example better message:

`Search timed out after 10s. The service is running but same-project searches are serialized. A search or index job may be occupying the project. Try: vaultspec-rag server jobs --limit 3, then retry with --timeout 60 or fewer parallel searches.`

### F2a. Default timeout is incompatible with server-bound search behavior

Severity: High

Symptom: The default HTTP search timeout is 10 seconds. In the observed session, a
parallel batch of server-backed searches all timed out at this default.

Impact: The timeout is too low for the behavior the current service actually exposes:
serialized same-project execution, possible queueing behind indexing, and local Qdrant
contention. For users and agents, this makes the default path feel broken even when the
service is alive.

Likely cause: The timeout appears tuned for a fast-path expectation rather than for the
service-bound operational reality. Prior benchmarking suggested RAG search could be
near-instantaneous, but the current server-bound version behaved much more slowly under
ordinary discovery pressure.

Proposed fix:

- Increase the default timeout for service-backed search substantially, or make it
  adaptive based on service status, active jobs, and same-project serialization.
- Separate user-visible timeout policy from production latency expectations:
  - timeout budget: how long the CLI will wait before giving up,
  - latency SLO: how fast the system should normally respond.
- Add queue-aware timeout messaging when the request is waiting behind service work.
- Preserve a short timeout option for scripts that want fail-fast behavior.

### F2b. Server-bound search performance appears to have regressed

Severity: Critical

Symptom: Current service-backed RAG search felt suspiciously slow. Earlier benchmark
work reportedly showed RAG search as near-instantaneous, but the current server-bound
path timed out and later required long waits around indexing and search.

Impact: This is not production usable if representative. Operators need predictable
latency, clear queueing behavior, and confidence that the resident service improves
performance rather than degrading it.

Evidence from this session:

- Six parallel service-backed searches timed out at 10 seconds.
- Same-project search is reported as serialized.
- Useful semantic discovery only became reliable after a code index refresh.
- The index refresh took about 270 seconds for 306 files / 4042 chunks.
- The job appeared stalled at one progress count for multiple polls.
- Service logs showed a large local Qdrant collection warning in the active environment.

Unknowns:

- Whether the slowdown is search latency, queue wait, Qdrant local collection size,
  indexing contention, service serialization, stale index state, or version regression.
- Whether prior benchmarks used in-process search, service-backed search, a smaller
  collection, Docker/remote Qdrant, or a different version.

Proposed fix:

- Run a focused performance regression audit comparing:
  - previous known-good version,
  - current server-bound version,
  - in-process search,
  - resident-service search,
  - idle service,
  - service while indexing,
  - local Qdrant collection size effects.
- Add benchmark output to `server status` or diagnostics:
  - last search latency,
  - queue wait,
  - encode time,
  - Qdrant query time,
  - rerank/postprocess time.
- Add tracing/correlation ids so logs, jobs, and search responses can explain where time
  was spent.
- Treat this as a production-readiness blocker until latency behavior is understood.

### F3. Empty search results do not distinguish "nothing found" from stale or missing index

Severity: High

Symptom: Exact-symbol searches for known implementation areas returned empty results before the code index was refreshed.

Impact: Users and agents may conclude that code does not exist or that RAG is broken.

Likely cause: Search result responses do not carry index freshness, code collection count, target identity, or last indexed timestamp.

Proposed fix:

- Attach index metadata to empty result responses.
- If code search returns zero results and the code index is empty/stale/missing, say so.
- Suggest `vaultspec-rag index --type code --port <port>`.
- Consider a `--explain-empty` default for JSON agent workflows.

### F4. `server info` wraps a service error as an outer success

Severity: High

Symptom: `server info --json` returned `ok: true` with nested `data.ok: false`.

Impact: Agents that check only the outer envelope will treat a failed service call as success.

Likely cause: CLI command success is based on receiving a response, not on the service response's semantic success.

Proposed fix:

- If service response has `ok: false`, propagate failure to the outer envelope.
- Exit non-zero.
- Preserve the service error code and message at the top level.

### F5. `server info` requires project root indirectly but exposes no option

Severity: High

Symptom: `/service-state` requires `project_root`, but `vaultspec-rag server info` exposes only `--port` and `--json`. Global `--target .` did not satisfy the route.

Impact: The command is present but cannot perform its intended function in this context.

Proposed fix:

- Add `--project-root` or correctly propagate global `--target`.
- If no root is available, fail before the HTTP call with a CLI-level message.
- Align help text with the route contract.

### F6. Health parity is incomplete

Severity: Medium

Symptom: The service exposes `GET /health`, but the CLI has no explicit `vaultspec-rag server health` command. Health is embedded in `server status`.

Impact: Users looking for parity between localhost routes and CLI entry points must infer that `server status` is the health command.

Proposed fix:

- Add `vaultspec-rag server health`.
- Keep `server status` as the broader process/service diagnostic.
- Make `server health --json` mirror `/health` directly.

### F7. Jobs output is the wrong operational interface

Severity: High

Symptom: `server jobs` presents job activity as a simple table/history dump. In JSON mode,
`server jobs --json` returned a very large job history. The output was too large for
practical agent consumption and was truncated by the execution environment.

Impact: The useful current job was buried. In a command-line interface, the user could
not reliably see the latest jobs or the jobs currently running because historical records
blocked the operational signal. The table format is also fragile in terminals and poorly
suited to job inspection.

Likely cause: The jobs command treats the registry as a list to print rather than as an
operator view. It exposes a basic bounded registry but not the stateful questions users
need to answer: what is running, what just failed, what is blocking, who started it, what
wrapper or command owns it, and what resources it is consuming.

Proposed fix:

- Replace the default table-first view with an operator-oriented summary:
  - running jobs first,
  - then recently failed jobs,
  - then recently completed jobs.
- Default to a small recent limit, such as 10 or 20.
- Provide `--all` for full history.
- Add filters:
  - `--running`,
  - `--failed`,
  - `--source vault|code`,
  - `--trigger tool|watcher`,
  - `--job-id`,
  - `--since`,
  - `--initiator` or equivalent once initiator tracking exists.
- Add a compact line-oriented output mode that does not break across narrow terminals.
- Keep JSON as the agent/API-stable representation, but ensure it is bounded by default.
- Include actionable state fields: queue age, runtime, last progress age, current phase,
  and suggested next command.

### F8. Job progress can appear stalled without liveness explanation

Severity: High

Symptom: The code index job stayed at `2240 / 4042` chunks across several polls.

Impact: The user could not tell whether the job was stuck, processing a large batch, blocked on Qdrant, or dead.

Proposed fix:

- Add `last_updated_age_seconds`.
- Add current operation details, for example `embedding batch`, `qdrant upsert`, `writing metadata`.
- Add a warning state when progress has not changed for a threshold while the task is still alive.
- Surface task liveness separately from chunk progress.
- Include memory/resource context so the user can distinguish active GPU/Qdrant work from
  an idle or wedged task.
- Cross-reference the job with the command, wrapper, watcher, or service component that
  initiated it.

### F8a. Jobs lack initiator, wrapper, and resource correlation

Severity: High

Symptom: The jobs registry reports basic fields such as source, trigger, phase, result,
and progress, but it does not say enough about who started a job or what runtime context
the job is associated with.

Impact: The user cannot answer operational questions:

- Which CLI invocation, MCP tool, watcher, or wrapper initiated this?
- Is the watcher active for the same root?
- Is a wrapper currently waiting on the job?
- What memory or GPU pressure is associated with the work?
- Is a current timeout caused by an active job, a stale job, or a separate search?

Likely cause: The job model is activity-centric rather than operation-centric. It records
that work exists, but not enough causality or runtime context to make the work actionable.

Proposed fix:

- Add initiator metadata to job records:
  - initiator type: CLI, MCP, watcher, service internal,
  - command/tool name,
  - request id,
  - project root,
  - parent wrapper or caller when applicable.
- Add resource snapshots or links:
  - process memory,
  - GPU memory,
  - queue/writer-lock wait state,
  - active Qdrant/upsert phase if known.
- Add cross-links in output:
  - job id,
  - related watcher root,
  - related service request id,
  - related log correlation id.
- Make `server jobs --json` stable enough for agents to join jobs, logs, and status.

### F9. CLI terminology is conflated

Severity: Medium

Symptom: The user-facing language mixes server, service, MCP, HTTP, daemon, admin tool, and route concepts.

Evidence:

- Commands are under `vaultspec-rag server`.
- Function and command names use `service_*`.
- Help text says `MCP port` for HTTP service admin commands.
- Docs/search snippets refer to `server service logs/jobs`.

Impact: Users cannot easily build a mental model of what is local process status, HTTP service state, MCP adapter state, or CLI wrapper behavior.

Proposed fix:

- Choose one user-facing term for the resident process, likely `service`.
- Reserve `server mcp` for the MCP adapter.
- Rename help text from `MCP port` to `service port` where appropriate.
- Keep backwards compatibility for command names if needed, but clean the help and docs.

### F9a. Too many status-like interfaces fragment the operational model

Severity: High

Symptom: The product exposes or implies several overlapping operational surfaces:

- health,
- status,
- jobs,
- logs,
- service info,
- job information.

These names do not establish a clear hierarchy. A user who wants to answer "what is the
service doing and is it healthy?" has to manually combine multiple commands and route
responses.

Impact: The interface feels larger while communicating less. Users cannot predict which
surface contains the answer:

- `health` sounds like readiness.
- `status` sounds like the overall operational state.
- `jobs` sounds like work history and active work.
- `logs` sounds like raw diagnostics.
- `info` sounds like metadata but currently overlaps with state and index information.

The result is a fragmented operational model. CLI and server routes do not feel like two
views of the same system; they feel like separate, partially overlapping inventions.

Likely cause: Features were added as separate surfaces around implementation concerns:
route handlers, MCP tools, CLI wrappers, service status file, job registry, and log
reader. The names reflect those implementation seams rather than a user-facing
information architecture.

Proposed fix:

- Define one canonical status model for the service.
- Make CLI and HTTP expose the same concepts with the same names.
- Treat health, jobs, and logs as subresources of status/diagnostics, not competing
  status interfaces.
- Prefer a standard command hierarchy:
  - `server status`: concise overall state, running jobs summary, health, freshness,
    resource pressure, and next action.
  - `server jobs`: focused job inspection with filters and detail mode.
  - `server logs`: raw log tail, linked by request/job correlation ids.
  - `server health`: optional low-level readiness probe, primarily for automation, if
    retained.
- Standardize server routes around the same model:
  - `/status` or `/service/status` for the aggregate view,
  - `/health` for readiness only,
  - `/jobs` for job collection,
  - `/jobs/{id}` for job detail,
  - `/logs` for raw logs with correlation filters.
- Cross-reference everything:
  - status lists active job ids,
  - jobs include related log/request ids,
  - logs can filter by job/request id,
  - health stays small and readiness-oriented.

### F9b. MCP deconflation is incomplete

Severity: High

Symptom: The CLI/service discovery path still exposes MCP-shaped concepts in places that
are not Model Context Protocol workflows. Examples observed during the session include
admin tool names such as `get_logs` and `get_jobs`, help text referring to an `MCP port`
for service admin commands, and parity language that treats CLI/server functionality as
mirrors of MCP tools rather than independent service operations.

Impact: Prior deconflation campaigns have not fully removed business logic from the MCP
implementation shape. Users who are only trying to operate the resident RAG service still
encounter MCP terminology and seams. This keeps the architecture conceptually tangled:

- CLI commands appear to call "admin tools" rather than service operations.
- HTTP service routes, CLI commands, and MCP tools are not clearly layered.
- Product concepts are named after adapter mechanics.
- Future status/jobs/logs work risks reinforcing the conflation unless the ownership
  boundary is corrected first.

Likely cause: MCP began as or became the integration surface for backend operations.
Later CLI and HTTP parity work reused MCP tool names and admin-tool routing concepts
instead of defining a service-domain API first and then adapting MCP to it.

Proposed fix:

- Make the resident service domain the owner of business operations:
  - status,
  - jobs,
  - logs,
  - search,
  - index/reindex,
  - watcher control.
- Treat MCP as an adapter over the service domain, not as the source of operational
  semantics.
- Rename CLI internals and help text away from MCP where the command is service-scoped.
- Ensure the call graph is:
  - CLI -> service/domain client -> HTTP route or local domain operation,
  - MCP tool -> same service/domain client,
  - not CLI -> MCP admin concept -> service.
- Update the deconflation ADR set to explicitly cover business-logic ownership, not only
  command/module naming.

### F10. Local status and service-owned lock guidance is incomplete

Severity: Medium

Symptom: `vaultspec-rag status --json` failed because the service held the Qdrant lock.

Impact: The error was accurate, but it did not complete the user's task: inspect index state while the service owns the store.

Proposed fix:

- When local status hits a service-owned lock, detect a running service and offer or perform service delegation.
- Add a service-safe status command or route for index metadata.
- Tell the user exactly which command to run next.

### F11. The tool does not read back its own operational tape

Severity: High

Symptom: The CLI has status, jobs, and logs, but it does not synthesize them into an explanation of what happened.

Impact: The user had to manually combine:

- timeout errors,
- service status,
- job progress,
- service logs,
- index dry-run,
- index refresh result,
- empty search results,
- route bad requests.

Proposed fix:

- Add `vaultspec-rag diagnose` or `vaultspec-rag server doctor`.
- Include recent failed commands if available, service health, active jobs, index freshness, lock ownership, and suggested next action.
- For agent workflows, provide JSON diagnostics with a single top-level verdict and ordered remediations.

## Parity Map

| Surface       | Server localhost entry point          | CLI entry point                                | Current parity                                      |
| ------------- | ------------------------------------- | ---------------------------------------------- | --------------------------------------------------- |
| Health        | `GET /health`                         | `server status` indirectly via `_health_probe` | Partial. No direct `server health`.                 |
| Jobs          | `GET /jobs`                           | `server jobs`                                  | Mostly present, but default output is too large.    |
| Logs          | `GET /logs`, `GET /logs/json`         | `server logs`                                  | Present. CLI correctly uses JSON route.             |
| Service state | `GET /service-state?project_root=...` | `server info`                                  | Broken contract. CLI does not expose required root. |

## Recommended Implementation Shape

### Add explicit CLI parity commands

Add:

- `vaultspec-rag server health`
- Possibly `vaultspec-rag server state --project-root ...`

Keep:

- `server status` for process, PID, heartbeat, port, and token diagnostics.
- `server jobs` for job registry.
- `server logs` for log tail.

### Make service-backed search self-diagnosing

Search responses, especially empty results and timeouts, should include:

- service readiness,
- active job count,
- current project indexing state,
- last code index timestamp,
- code collection count,
- whether the target root matches the indexed project,
- same-project concurrency strategy.

### Make stale or missing index visible

When `--type code` returns zero results:

- If code index is empty: say it is empty.
- If code index is stale: say when it was last indexed.
- If no metadata exists: say no code index metadata exists.
- Suggest the exact index command.

### Add backpressure-aware timeout handling

The CLI should not let parallel agent calls fail identically without context.

Options:

- client-side semaphore per service/project,
- service-side queue position and busy responses,
- adaptive timeout when same-project serialization is active,
- clearer timeout diagnostics.

### Normalize language

Use these terms consistently:

- `service`: resident HTTP process.
- `service port`: localhost HTTP port.
- `MCP`: protocol adapter mounted under the service or run separately.
- `server`: only if kept as the command namespace for compatibility.

### Fix JSON envelope semantics

If an underlying service response is an error, the outer CLI JSON envelope should be an error.

Never return `ok: true` with nested `data.ok: false` for command failure.

## User Testimonial

As a user trying to use VaultSpec RAG to discover VaultSpec RAG, I could eventually get the answer, but the experience required too much manual recovery.

The tool did not guide me through its own operational model. It gave me primitives: search, status, jobs, logs, index. It did not compose those primitives into a useful explanation when things went wrong.

The hardest parts were:

- knowing whether empty search meant no code, stale index, wrong target, or bad query;
- understanding that parallel searches could time out because same-project work is serialized;
- discovering that the service was healthy but the code index still needed refresh;
- interpreting a local lock error while the service was the legitimate lock owner;
- dealing with `server info` returning a bad request that the CLI had no option to satisfy;
- polling a job that appeared stuck without knowing whether it was alive;
- sorting through terminology that blurred service, server, daemon, MCP, HTTP, and admin tools.

The implementation has the ingredients for a good experience. The CLI does not yet package them into a good experience.

## Action Basis

The next work should focus on user-facing control flow rather than adding more raw surfaces.

Priority actions:

1. Define a canonical service status model and make CLI/server routes converge on it.
1. Standardize naming and hierarchy for status, health, jobs, logs, and info.
1. Complete MCP deconflation by moving operational semantics into a service-domain layer
   and making MCP only an adapter.
1. Fix `server info` route/CLI root propagation and JSON error semantics, or fold it
   into the canonical status model.
1. Keep `/health` as readiness-only; expose it in CLI only if it has a clear automation
   role and does not compete with `server status`.
1. Add index freshness and target identity to status/search responses, especially empty
   search results.
1. Reassess the default service-backed search timeout; make it high or adaptive enough
   for the current server execution model.
1. Investigate suspected server-bound performance regression against prior near-instant
   RAG benchmark behavior.
1. Add timeout diagnostics that mention service busy state, same-project serialization,
   active jobs, and `--timeout`.
1. Add request timing breakdowns for queue wait, embedding, Qdrant query, rerank, and
   response rendering.
1. Redesign `server jobs` as an operator interface, not a simple table dump.
1. Add filtering, bounded defaults, running-first sorting, and compact output for jobs.
1. Add job initiator, wrapper, request, watcher, and resource correlation.
1. Add job liveness fields so stalled-looking progress can be interpreted.
1. Normalize CLI help terminology around service versus MCP.
1. Add a service-aware diagnostic command or status detail mode that reads status, jobs,
   logs, locks, and index metadata together.

This audit should be treated as a product defect record generated from a real failed-and-recovered user session.

## Implementation Progress Update - 2026-06-12

The original testimonial remains the baseline failure record. The hardening epic has now
implemented the following current-state improvements:

- `server status` is the canonical operator view and supports explicit `--port` checks.
- `server jobs` is bounded, running-first, filterable, and supports focused `--job-id`
  inspection.
- Job records include initiator, command, project root, liveness, OS user, serving PID,
  executable/virtualenv context, RSS, CUDA allocated memory, and CUDA reserved memory.
- `server logs` supports `--job-id` and `--contains`, with the same filters available
  through the localhost routes and MCP adapter.
- Service-backed search responses include `index_state`, empty-result diagnostics,
  phase timing, numeric GPU queue wait, and `request_id`.
- Timeout errors report service readiness, running jobs, backpressure hints, backend
  concurrency strategy, and concrete next actions.
- `/health`, heartbeat, `server start`, `server status`, and job runtime records now
  agree on the serving daemon PID rather than the Windows launcher PID.
- Search request ids are now joinable through `server logs --contains <request_id>`.
- Service readiness now includes shared reranker preload when reranking is enabled, and
  health/status expose `reranker_loaded` so the first project lease no longer pays the
  largest observed CrossEncoder setup cost.

Manual validation after request-correlation hardening used resident service PID `59728`
on port `8766`:

- `uv run vaultspec-rag search "request correlation logs" --type code --json --max-results 1 --port 8766 --timeout 180`
- `uv run vaultspec-rag server logs --json --contains 1d11935dd18e4e258c955439653fb339 --lines 5 --port 8766`

Observed result:

- The search returned `request_id: 1d11935dd18e4e258c955439653fb339`.
- The log query returned a structured `service.lifecycle event=search` line with the same
  request id.

Manual validation after reranker-readiness hardening restarted the resident service as
PID `62932` on port `8766`:

- `uv run vaultspec-rag server status --json --port 8766`
- `uv run vaultspec-rag server health --json --port 8766`
- `uv run vaultspec-rag search "cold reranker preload project lease timing" --type code --json --max-results 1 --port 8766 --timeout 180`

Observed result:

- startup completed in about `19.2s`,
- health and status reported `reranker_loaded: true` before any project was leased,
- first service-backed search returned in about `2.65s`,
- cold `project_lease_seconds` was about `1.35s`, down from the earlier observed
  `~6.53s` setup cost.

Remaining product risk:

- Cold service startup still takes tens of seconds because readiness now includes real
  shared model setup. That is more honest and improves first-search behavior, but it
  should still be compared against prior near-instant benchmark expectations.
- The audit still recommends a future higher-level diagnostic/doctor flow. The current
  implementation hardens the existing status/jobs/logs/search surfaces rather than adding
  a new umbrella command.
