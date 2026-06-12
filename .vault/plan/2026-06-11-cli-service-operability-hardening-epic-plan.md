---
tags:
  - '#plan'
  - '#cli-service-operability-hardening'
date: '2026-06-11'
related:
  - '[[2026-06-11-vaultspec-rag-cli-service-ux-audit]]'
  - '[[2026-06-11-service-status-convergence-adr]]'
  - '[[2026-06-11-service-jobs-operability-adr]]'
  - '[[2026-06-11-search-freshness-and-empty-results-adr]]'
  - '[[2026-06-11-server-bound-search-production-readiness-adr]]'
  - '[[2026-06-11-service-status-convergence-research]]'
  - '[[2026-06-11-service-jobs-operability-research]]'
  - '[[2026-06-11-search-freshness-and-empty-results-research]]'
  - '[[2026-06-11-server-bound-search-production-readiness-research]]'
---

# `cli-service-operability-hardening` epic plan

Date: 2026-06-11
Status: Draft execution basis
Source audit: `audit/2026-06-11-vaultspec-rag-cli-service-ux-audit`

## Purpose

Harden the VaultSpec RAG CLI and resident service so the command-line interface is
production-usable for real operators and agent users.

This epic responds to a live user journey where `vaultspec-rag` was used to discover its
own implementation. The tool eventually worked, but the experience exposed failures in
timeout behavior, service-bound performance, stale-index detection, jobs display,
status/health/log naming, MCP deconflation, and operator feedback.

The work must converge the CLI and server around simpler, standardized, cross-referenced
operability surfaces. The goal is not to add more commands. The goal is to make the
existing operational model coherent.

## Operating Constraints

- Keep the current running RAG service alive for as long as possible during the work.
- Prefer service-backed `vaultspec-rag` searches while the service is healthy.
- Do not restart the service unless the current implementation must be swapped in for
  validation.
- When a restart is required, the MCP and RAG services on this workstation are available
  for the executor to manage.
- Every implementation wave must end with manual, non-test-driven CLI usage using an
  explicit user persona. This is required even when automated tests pass.
- Automated tests remain required, but they are not sufficient. The CLI must be exercised
  as a product.

## Referenced ADRs

The epic should create or update ADRs before implementation. Based on RAG discovery, the
work should be split into four decision records:

1. `service-status-convergence`

   - Supersedes: status/jobs/logs/health shape from
     `adr/2026-06-01-service-observability-adr`
   - References:
     - `adr/2026-06-07-mcp-server-deconflation-adr`
     - `adr/2026-06-06-cli-tree-overhaul-adr`
     - `adr/2026-06-09-operability-hardening-adr`
     - `adr/2026-05-31-service-token-identity-adr`

1. `service-jobs-operability`

   - Supersedes: jobs portion of `adr/2026-06-01-service-observability-adr`
   - References:
     - `adr/2026-06-01-service-operability-adr`
     - `adr/2026-06-04-async-service-index-adr`
     - `adr/2026-06-02-watcher-targeted-reindex-adr`
     - `adr/2026-04-12-index-progress-bars-adr`

1. `search-freshness-and-empty-results`

   - Supersedes: implicit empty-result behavior in
     `adr/2026-05-28-cli-backend-parity-adr`
   - References:
     - `adr/2026-05-28-cli-search-filters-adr`
     - `adr/2026-04-04-test-and-paths-adr`
     - `adr/2026-05-30-cli-index-default-adr`
     - `adr/2026-06-10-preprocess-hooks-adr`

1. `server-bound-search-production-readiness`

   - Supersedes: timeout/search behavior portions of
     `adr/2026-06-04-async-service-index-adr`
   - References:
     - `adr/2026-06-05-qdrant-performance-adr`
     - `adr/2026-06-07-sparse-search-latency-adr`
     - `adr/2026-06-05-service-stress-watcher-adr`
     - `adr/2026-06-02-index-perf-hardening-adr`
     - `adr/2026-06-02-index-gpu-pipeline-adr`

The existing `mcp-server-deconflation` and `cli-mcp-decoupling` decisions must be
referenced explicitly. The audit shows those campaigns did not fully remove
MCP-shaped business logic from CLI/service operations.

## Per-Wave VaultSpec Pipeline

Every wave uses the same embedded pipeline:

1. Hardening

   - Reproduce the user-facing failure or rough edge.
   - Define the behavior that would have prevented the failure.
   - Add or update real-behavior tests where appropriate.

1. Research

   - Use `vaultspec-rag` to find prior ADRs, plans, tests, and implementation locations.
   - Compare the intended decision history against the live CLI behavior.
   - Record gaps in the wave notes.

1. ADR / Plan Alignment

   - Confirm the relevant ADR exists or create/update it.
   - Verify the wave still matches the accepted decision.
   - If implementation discovers a decision conflict, stop and revise the ADR before
     continuing.

1. Implementation

   - Make the smallest coherent code change that moves the CLI/server surface toward the
     wave objective.
   - Preserve compatibility unless the ADR explicitly authorizes a breaking change.
   - Keep MCP as an adapter, not as the owner of service-domain behavior.

1. Code Review

   - Review for correctness, architecture, command UX, error semantics, and test quality.
   - Specifically check for repeated MCP/server/CLI conflation.
   - Specifically check that JSON envelopes report failures consistently.

1. Repeating Patterns

   - Identify durable rules that should be codified.
   - Promote patterns such as "service-domain owns operations; MCP adapts" only after the
     implementation proves them.

1. Manual CLI Persona Test

   - Run the current CLI manually as a named persona.
   - Do not rely only on tests.
   - Capture commands, observed output, confusion points, and whether the interface is
     actionable.
   - Update the audit or wave notes with any new testimonial findings.

## Wave 00 - Baseline Reproduction And Decision Setup

Objective: Freeze the current failure evidence and create/update the ADRs needed to govern
implementation.

Pipeline:

Hardening:

- Re-run a bounded reproduction of the observed rough edges:
  - service status,
  - empty search / stale index behavior,
  - jobs default output,
  - logs access,
  - `server info` bad request behavior,
  - timeout behavior with serialized same-project service work.
- Do not intentionally overload the service with unbounded parallel calls; one controlled
  reproduction is enough.

Research:

- Use `vaultspec-rag search --type vault` for prior ADRs and plans.
- Use `vaultspec-rag search --type code` for implementation locations.
- Confirm whether the running service index is fresh before relying on search results.

ADR / Plan Alignment:

- Draft the four ADRs listed above or update existing ones if maintainers decide to
  supersede in place.
- Each ADR must name superseded/referenced ADRs explicitly.

Implementation:

- No product implementation in this wave except safe documentation/audit corrections.

Code Review:

- Review the ADR set for overlap. Reject any ADR that tries to solve two independent
  problems.

Repeating Patterns:

- Candidate pattern: "Every CLI operability feature must include manual persona testing."
- Candidate pattern: "CLI/server/MCP parity must be expressed through a service-domain
  operation, not an MCP-shaped command."

Manual CLI Persona Test:

- Persona: "Codex agent trying to orient itself before touching code."
- Commands:
  - `vaultspec-rag server status --json`
  - `vaultspec-rag server jobs --json --limit 5`
  - `vaultspec-rag server logs --json --lines 40`
  - one service-backed code search with `--timeout 120`
- Acceptance: The executor can explain the service state and next safe action without
  reading source files directly.

Deliverables:

- ADR set ready for approval.
- Updated epic plan if ADR decisions change scope.
- Baseline CLI transcript or summarized wave note.

## Wave 01 - Canonical Status Model And MCP Deconflation

Objective: Define one canonical service status model and make CLI/server/MCP adapters use
that model consistently.

Pipeline:

Hardening:

- Reproduce confusion across `status`, `health`, `info`, `jobs`, and `logs`.
- Reproduce MCP terminology leaking into service commands, such as `MCP port` in service
  admin help.

Research:

- Search existing code and ADRs for:
  - service status,
  - health handler,
  - service info,
  - MCP deconflation,
  - CLI tree overhaul.

ADR / Plan Alignment:

- Govern this wave with `service-status-convergence`.
- Reference `mcp-server-deconflation` and `cli-mcp-decoupling`.

Implementation:

- Introduce or clarify a service-domain status object.
- Make `server status` the concise operational surface:
  - process state,
  - readiness,
  - active jobs summary,
  - index freshness summary,
  - resource pressure summary when available,
  - next action.
- Keep `/health` readiness-only.
- Either remove `server info` as a competing concept or fold it into a clearly named
  detail/status subcommand.
- Rename service command help away from MCP terminology.
- Ensure CLI and MCP call into the same service-domain operation instead of duplicating
  or MCP-owning business logic.

Code Review:

- Check for call paths that still make CLI semantics depend on MCP admin-tool naming.
- Check JSON envelope semantics: service-domain failure must produce outer CLI failure.

Repeating Patterns:

- Codify "MCP is an adapter, not the service-domain owner" if the implementation confirms
  the pattern.
- Codify naming guidance for health/status/jobs/logs if it survives manual testing.

Manual CLI Persona Test:

- Persona: "Operator checking whether the resident service is usable before running a
  search."
- Commands:
  - `vaultspec-rag server status`
  - `vaultspec-rag server status --json`
  - `vaultspec-rag server health --json` if retained or added
  - `vaultspec-rag server jobs --limit 5`
- Acceptance:
  - The user can tell whether the service is ready, busy, stale, or degraded.
  - The output uses service terminology, not MCP terminology, unless the command is under
    `server mcp`.
  - The next action is obvious.

Deliverables:

- Canonical status model implemented.
- CLI/server/MCP adapter boundary clarified.
- Manual persona transcript summarized.

## Wave 02 - Jobs As An Operator Interface

Objective: Replace the simplistic jobs history table with an actionable job inspection
surface.

Pipeline:

Hardening:

- Reproduce current jobs failure:
  - default history overwhelms current work,
  - table breaks or becomes hard to read,
  - no useful filtering,
  - no initiator/wrapper/request/resource context.

Research:

- Search code and vault history for:
  - jobs registry,
  - async indexing,
  - watcher reindex,
  - progress bars,
  - GPU/index pipeline.

ADR / Plan Alignment:

- Govern this wave with `service-jobs-operability`.

Implementation:

- Make running jobs first by default.
- Bound default output.
- Add filters:
  - `--running`,
  - `--failed`,
  - `--source`,
  - `--trigger`,
  - `--job-id`,
  - `--since` if feasible.
- Add detail mode for a single job.
- Add initiator metadata:
  - CLI/MCP/watcher/service,
  - command/tool name,
  - request/correlation id,
  - project root.
- Add liveness fields:
  - runtime,
  - last progress age,
  - queue/writer-lock wait if known.
- Add resource context where feasible:
  - process memory,
  - GPU memory,
  - Qdrant/upsert phase.
- Make JSON bounded and stable for agents.

Code Review:

- Check that jobs are not only pretty output; they must answer operational questions.
- Check terminal-width behavior.
- Check that no tests fabricate business logic or mirror implementation shortcuts.

Repeating Patterns:

- Candidate pattern: "Operator lists must default to current actionable state, not full
  history."
- Candidate pattern: "Every long-running operation gets a correlation id and liveness
  fields."

Manual CLI Persona Test:

- Persona: "Maintainer watching a long code index and deciding whether it is stuck."
- Commands:
  - `vaultspec-rag index --type code --port 8766 --json`
  - `vaultspec-rag server jobs`
  - `vaultspec-rag server jobs --running`
  - `vaultspec-rag server jobs --job-id <id> --json`
  - `vaultspec-rag server logs --job-id <id>` if log filtering is implemented
- Acceptance:
  - Running work is visible immediately.
  - The job view explains who started the job, what it is doing, how long it has been
    doing it, and whether progress is stale.
  - The user does not need to dump the entire job history.

Deliverables:

- Jobs CLI redesigned.
- Job model extended with initiator/liveness/correlation fields.
- Manual persona transcript summarized.

## Wave 03 - Search Freshness, Empty Results, And Target Identity

Objective: Make empty or poor search results actionable instead of ambiguous.

Pipeline:

Hardening:

- Reproduce empty search behavior against a stale or missing code/vault index.
- Reproduce local status lock confusion while the service owns Qdrant.
- Reproduce target mismatch if possible.

Research:

- Search code/vault history for:
  - CLI backend parity,
  - search filters,
  - index metadata,
  - config target,
  - preprocessing hooks.

ADR / Plan Alignment:

- Govern this wave with `search-freshness-and-empty-results`.

Implementation:

- Include index freshness metadata in search responses:
  - source type,
  - indexed document/chunk count,
  - last indexed time,
  - index target root,
  - current requested target root,
  - stale/missing status.
- When results are empty, include an explanation:
  - no matching results,
  - index missing,
  - index stale,
  - target mismatch,
  - service busy or degraded.
- Suggest the next command when safe:
  - `vaultspec-rag index --type code --port <port>`
  - `vaultspec-rag server status`
  - `vaultspec-rag server jobs --running`
- Make local status lock errors point to service-safe status when the resident service
  owns the store.

Code Review:

- Check that empty-result guidance is based on real metadata, not guesses.
- Check that JSON shape is stable and scriptable.

Repeating Patterns:

- Candidate pattern: "Empty responses from agent-facing commands must include state
  metadata and next-action guidance."

Manual CLI Persona Test:

- Persona: "Agent searching for implementation locations in a codebase that may not be
  indexed yet."
- Commands:
  - `vaultspec-rag search \"health jobs logs\" --type code --json --port 8766 --timeout 120`
  - `vaultspec-rag index --type code --dry-run --json`
  - `vaultspec-rag index --type code --port 8766 --json`
  - repeat the search after indexing
- Acceptance:
  - Empty results explain whether the problem is no match, stale index, missing index, or
    target mismatch.
  - The user can recover without knowing internal Qdrant/index details.

Deliverables:

- Search response metadata implemented.
- Empty-result recovery guidance implemented.
- Manual persona transcript summarized.

## Wave 04 - Timeout, Backpressure, And Production Search Readiness

Objective: Make service-bound search latency understandable, tunable, and production
credible.

Pipeline:

Hardening:

- Reproduce timeout behavior with controlled same-project concurrent searches.
- Reproduce search while indexing.
- Capture current latency breakdown if instrumentation exists; otherwise record the lack
  of breakdown as the starting defect.

Research:

- Search prior ADRs for:
  - async service index,
  - Qdrant performance,
  - sparse search latency,
  - service stress watcher,
  - index GPU pipeline.

ADR / Plan Alignment:

- Govern this wave with `server-bound-search-production-readiness`.

Implementation:

- Reassess default timeout:
  - make it high enough for current server-bound behavior, or
  - make it adaptive based on queue/service state.
- Add fail-fast option for scripts that want short timeouts.
- Add request timing:
  - queue wait,
  - embedding time,
  - Qdrant query time,
  - rerank/postprocess time,
  - response serialization time.
- Add queue/backpressure signals:
  - same-project serialized wait,
  - active indexing conflict,
  - service busy state.
- Add diagnostic output on timeout:
  - service ready/degraded,
  - active jobs,
  - queue wait if known,
  - suggested retry command.
- Compare current service-bound search against prior benchmark expectations.

Code Review:

- Check that higher timeouts do not hide regressions.
- Check that latency instrumentation has low overhead.
- Check that concurrency changes respect local Qdrant process constraints.

Repeating Patterns:

- Candidate pattern: "Timeouts must report service state and next action."
- Candidate pattern: "Performance fixes need explicit latency phase attribution."

Manual CLI Persona Test:

- Persona: "Power user running several agent searches while an index may be active."
- Commands:
  - one normal service-backed search,
  - one search with explicit short timeout,
  - one search while a background index is running,
  - `server status`,
  - `server jobs --running`,
  - `server logs` with relevant correlation if implemented.
- Acceptance:
  - Timeout behavior is understandable.
  - The default path no longer feels broken.
  - Slow responses show where time was spent.
  - The user can decide whether to wait, retry, stop work, or investigate performance.

Deliverables:

- Timeout policy updated.
- Latency instrumentation implemented.
- Performance regression notes produced.
- Manual persona transcript summarized.

## Wave 05 - Epic Integration, Review, And Pattern Codification

Objective: Verify the redesigned CLI/service operability model as one product and promote
durable rules.

Pipeline:

Hardening:

- Run the complete operator journey from cold orientation through search, index, jobs,
  logs, status, and timeout recovery.
- Include both human-readable output and JSON output.

Research:

- Use `vaultspec-rag` to search the updated codebase and vault for the new commands and
  decisions.
- Confirm semantic discovery works without manual index confusion.

ADR / Plan Alignment:

- Ensure all ADRs reflect final implementation.
- Mark superseded ADR sections clearly where applicable.

Implementation:

- Final cleanup only:
  - help text,
  - docs,
  - command aliases,
  - compatibility notes,
  - deprecation warnings if needed.

Code Review:

- Perform a formal code review focused on:
  - architecture boundaries,
  - CLI UX,
  - JSON contracts,
  - service/MCP deconflation,
  - performance instrumentation,
  - manual testing evidence.

Repeating Patterns:

- Codify proven rules into project rules:
  - service-domain operation ownership,
  - manual CLI persona testing for CLI features,
  - operator views default to actionable current state,
  - empty results include state and recovery context,
  - timeout messages include service state and next actions.

Manual CLI Persona Test:

- Persona: "New maintainer using only `vaultspec-rag` to diagnose and search this repo."
- Full journey:
  - check service,
  - inspect status,
  - inspect jobs,
  - run search,
  - handle empty/stale result if present,
  - run or observe index,
  - inspect logs,
  - repeat search,
  - export JSON for an agent.
- Acceptance:
  - The maintainer does not need hidden implementation knowledge.
  - The CLI explains service state and recovery paths.
  - The server and CLI expose the same concepts with consistent names.
  - MCP appears only where MCP is actually the user-facing concern.

Deliverables:

- Final code review findings addressed.
- Repeating patterns codified.
- Manual usage transcript summarized.
- Audit updated with before/after user testimonial.

## Wave 06 - Human Review Of Modified CLI Interface

Objective: Walk a human reviewer through the modified CLI operation surface one command
at a time, using the original audit and accepted ADRs as the comparison baseline.

### Phase W06.P01 - Redesign `server status` Human Output

Objective: Replace the fragile table-shaped default `server status` output with a
plain, human-first operator summary while preserving advanced diagnostics behind explicit
flags.

Progress tracking:

- [ ] Confirm the default output answers the human review questions:
  - is the server running,
  - is it healthy,
  - is it currently processing a request,
  - what is the queue status,
  - how many jobs has it processed,
  - what is the clickable service address,
  - what is the current job name and age when present,
  - how long has the service been running in short human-readable form.
- [ ] Move low-level process, token, model, and backend capability metadata behind
  `--verbose`, `--debug`, or `--json`.
- [ ] Remove Rich table rendering from the default `server status` human output.
- [ ] Keep `--json` stable and full-fidelity for agent/script use.
- [ ] Add or update real-behavior tests for the human output contract.
- [ ] Run manual CLI review and wait for human acceptance before closing the phase.

Status/health convergence cluster:

- [ ] Treat `server status` as the only default human-facing service-state command.
- [ ] Keep backend `/health` as a readiness endpoint for automation and adapters.
- [ ] Do not maintain a second rich human `server health` output that duplicates status.
- [ ] If CLI `server health` remains, make it minimal and automation-oriented; otherwise
  de-emphasize, alias, or remove it through an explicit compatibility path.
- [ ] Ensure help text tells users to call `server status` when they want to know whether
  the service is working or what to check next.

Agent brief:

- Start with Phase `W06.P01`.
- Read the original UX audit, the four governing ADRs, the four research notes, and the
  W05 summary before editing code.
- Treat the command-line UX reviewer feedback as accepted design input:
  - no table layout for default `server status`,
  - use stable plain labels such as `Server:`, `Health:`, `Busy:`, `Address:`,
    `Uptime:`, `Queue:`, `Jobs:`, and `Current job:`,
  - show the address as a full URL including the port,
  - use short human-readable uptime,
  - summarize jobs and queue state in human language,
  - reserve process identity, token checks, model details, and backend capability
    metadata for advanced flags.
- Do not broaden the command tree unless the human reviewer approves it.
- Human review has approved a status-only human model:
  - `server status` is the human operator surface,
  - `/health` is backend/readiness parity,
  - `server health` must not remain a parallel rich status display,
  - literal route parity is less important than semantic parity for the CLI.
- Do not change generated provider artifacts unless the project tooling requires it.
- Use `uv run` or `uv run --no-sync` for project commands.

### Phase W06.P02 - Redesign `server jobs` Human Output And Monitoring

Objective: Replace the fragile table-shaped default `server jobs` output with a
command-line-native operator feed that makes running, failed, and recent jobs readable,
project-scoped, and monitorable.

Progress tracking:

- [ ] Remove table rendering from the default human `server jobs` output.
- [ ] Use common command-line notation for job state, including a simple prefix such as
  `*` for running/current jobs.
- [ ] Keep a simple header or summary line, not a box/table layout.
- [ ] Include project or repository identity for each job so the user can tell which
  project requested the operation.
- [ ] Reword implementation triggers into user-facing operation names, for example
  `index update` instead of raw `watcher`.
- [ ] Show failed jobs clearly in the default or an obvious filtered view.
- [ ] Order output so the latest job is last in the default human stream, matching common
  terminal/log reading expectations.
- [ ] Translate compact internal results such as `+0 /1 -0 (22231ms)` into human-facing
  language.
- [ ] Preserve `--json` as the full-fidelity agent/script format.
- [ ] Add continuous monitoring with auto-refresh and complete terminal content
  management for interactive monitoring.
- [ ] Add or update real-behavior tests for default output, filters, failed jobs, and
  monitoring behavior where feasible.
- [ ] Run manual CLI review and wait for human acceptance before closing the phase.

Agent brief:

- Start with Phase `W06.P02`.
- Read the original jobs audit findings, `service-jobs-operability` ADR and research,
  and the current `server jobs` implementation before editing code.
- Treat the human review feedback as accepted design input:
  - default `server jobs` table output is the worst remaining interface and must be
    replaced,
  - running jobs should be visually obvious with a simple CLI notation such as `*`,
  - output should read like a terminal feed or compact report, not a registry dump,
  - latest information should appear last by default,
  - project/repository identity is required,
  - failed jobs must be visible and filterable,
  - `watcher` should become a human phrase such as `index update`,
  - continuous monitoring should use a proper auto-refresh/watch mode rather than users
    repeatedly rerunning the command.
- Keep advanced or raw registry fields behind `--json` or detail flags.
- Do not change generated provider artifacts unless the project tooling requires it.
- Use `uv run` or `uv run --no-sync` for project commands.

### Phase W06.P03 - Redesign `server logs` Human Activity Feed

Objective: Replace raw default `server logs` output with a human-facing activity feed
while preserving raw log access and JSON output for diagnostics and automation.

Progress tracking:

- [ ] Keep raw log access available through an explicit flag or mode.
- [ ] Make default human `server logs` output an activity feed, not raw implementation
  log lines.
- [ ] Collapse duplicate lifecycle/access-log entries where they describe the same
  operation.
- [ ] Convert structured lifecycle lines into readable activity rows:
  - time,
  - operation,
  - project/repository,
  - result count or job outcome,
  - duration,
  - request/job id when useful.
- [ ] Keep `--contains <request_id>` and `--job-id <id>` useful for correlation.
- [ ] Preserve `--json` as the full-fidelity machine-readable log-tail envelope.
- [ ] Avoid formatting that wraps badly in narrow terminals.
- [ ] Add or update real-behavior tests for activity formatting, raw mode, and filters.
- [ ] Run manual CLI review and wait for human acceptance before closing the phase.

Agent brief:

- Start with Phase `W06.P03`.
- Own the CLI log viewing surface, not global logging internals.
- Treat the human review feedback as accepted design input:
  - default log output is currently raw, duplicated, noisy, and wraps badly,
  - lifecycle events are useful but should be rendered as operator activity,
  - raw log lines still matter, but they belong behind an explicit raw/detail mode,
  - request ids must remain searchable and joinable from search responses.
- Avoid changing centralized logger configuration or broad logging call sites; that is
  W06.P04.
- Use `uv run` or `uv run --no-sync` for project commands.

### Phase W06.P04 - Standardize Centralized Logging Enrollment

Objective: Standardize logging calls and message structure across the RAG codebase using
the project's centralized, customizable logging interface, independent of CLI log-view
formatting.

Progress tracking:

- [ ] Inventory current logger creation and direct logging calls across the codebase.
- [ ] Identify call sites that bypass or misuse the centralized logging interface.
- [ ] Standardize event names, severity levels, and structured fields for service
  lifecycle, search, jobs, watcher, indexing, and request correlation.
- [ ] Ensure normal lifecycle/activity events are not logged as warnings unless they are
  actual warnings.
- [ ] Keep emitted messages suitable for downstream parsing by `server logs`, MCP, and
  external log collectors.
- [ ] Avoid changing the human CLI log renderer owned by W06.P03 except by agreed
  contract fields.
- [ ] Add or update tests for normalized log emission where feasible.
- [ ] Produce an audit note for any broad call-site migration that should be staged
  separately.

Agent brief:

- Start with Phase `W06.P04`.
- Own centralized logging enrollment and message standardization, not the human
  `server logs` display.
- Read `src/vaultspec_rag/logging_config.py`, existing service lifecycle logging, jobs,
  watcher, index, search, and server route logging before editing.
- Treat the current raw `WARNING service.lifecycle event=search ...` output as evidence
  that levels and message semantics need tightening.
- Preserve request/job correlation semantics; do not remove useful structured fields.
- Coordinate with W06.P03 only through stable event fields, not display formatting.
- Use `uv run` or `uv run --no-sync` for project commands.

### Phase W06.P05 - Research Search Result Output In Mature CLI Tools

Objective: Ground the `vaultspec-rag search` human output redesign in mature,
respected command-line tools before changing the search result renderer.

Progress tracking:

- [ ] Identify mature CLI tools with search, ranked result, reporting, or operational
  listing output that is respected by working developers and operators.
- [ ] Use primary or authoritative sources where possible, such as official
  documentation, manpages, and long-lived project references.
- [ ] Compare how those tools handle:
  - stable line-oriented output,
  - TTY-aware color and decoration,
  - non-TTY output suitable for pipes,
  - long paths and snippets,
  - result scores or ranks,
  - line numbers or locations,
  - JSON, NDJSON, or other machine-readable modes,
  - explicit context/detail flags,
  - truncation and wrapping behavior.
- [ ] Treat `ragx` as a possible stable handoff format for long or structured result
  inspection, not as a substitute for a good default CLI result view.
- [ ] Produce design recommendations for `vaultspec-rag search` that keep default
  output easily grabbable, stable, and never silently truncated.
- [ ] Do not implement the search output redesign until the human reviewer accepts the
  research direction.

Agent brief:

- Start with Phase `W06.P05`.
- Research mature, relevant CLI utilities; avoid random fresh repositories as design
  precedent.
- Focus on tools such as `ripgrep`, `git grep`, GNU/BSD `grep`, GitHub CLI search,
  `kubectl`, `journalctl`, or other established CLIs only where their output model is
  directly relevant.
- Distinguish semantic/ranked search from exact text search: score is useful metadata,
  but it must not be conflated with line numbers or result count.
- Treat wrapping card layouts as rejected design input unless the research proves a
  bounded variant is appropriate behind an explicit detail mode.
- Prefer recommendations that are line-oriented, copyable, pipe-friendly,
  TTY-sensitive, and stable under terminal width changes.
- Include example output shapes and the rationale behind each recommendation.
- Do not edit source code.
- Use `uv run` or `uv run --no-sync` for project commands if local CLI examples are
  needed.

### Phase W06.P06 - Redesign `search` Human Result Output

Objective: Replace the fragile default `vaultspec-rag search` table with a mature,
line-oriented result format that is stable, copyable, pipe-friendly, and consistent with
the redesigned status, jobs, and logs surfaces.

Progress tracking:

- [ ] Remove Rich table rendering from default human search results.
- [ ] Use a line-oriented default result shape based on mature CLI search conventions.
- [ ] Keep source locations mechanically grabbable and never silently truncated.
- [ ] Show rank as explicit ranking metadata, not as a source coordinate.
- [ ] Keep numeric scores behind an explicit detail flag unless human review approves
  showing them by default.
- [ ] Keep `--json` envelope output stable and full-fidelity.
- [ ] Preserve empty-result diagnostics and timeout diagnostics from earlier waves.
- [ ] Ensure service-backed and local search share the same human output contract.
- [ ] Add or update real-behavior tests for default output, JSON output, detail flags,
  and no table/truncation regressions.
- [ ] Run manual CLI review and wait for human acceptance before closing the phase.

Agent brief:

- Start with Phase `W06.P06`.
- Treat W06.P05 research and human review feedback as accepted design input.
- Own the search result rendering path only, primarily:
  - `src/vaultspec_rag/cli/_render.py`,
  - `src/vaultspec_rag/cli/_search.py` only if flags or command wiring are needed,
  - focused tests under `src/vaultspec_rag/tests/`.
- You are not alone in the codebase; other agents have active edits in status, jobs,
  logs, server, logging, and tests. Do not revert or reformat unrelated work.
- Match the conventions now being enrolled in other human CLI surfaces:
  - plain text by default,
  - no boxed tables or card layouts,
  - short human labels only when labels clarify metadata,
  - stable output that remains readable in narrow terminals,
  - full-fidelity machine output behind `--json`,
  - implementation metadata behind explicit flags.
- Default output should be closer to `grep`/`ripgrep` result lines than to inventory
  tables. Prefer a shape like:
  `path[:line][:column]: rank=1 snippet text`
- If source line numbers are unavailable, use the best stable locator already present
  in the result, such as anchor, locator, path, or document id, without inventing fake
  coordinates.
- Do not silently truncate paths or snippets with ellipses in default output.
- Do not conflate rank, result count, score, or source line number.
- Add flags only where needed for the accepted design; avoid broad command tree churn.
- Use `uv run` or `uv run --no-sync` for project commands.

### Phase W06.P07 - Remove Human CLI Table Formatting Mandate-Wide

Objective: Treat table removal as an endemic CLI operability hardening mandate for
human-facing default output, not as a one-command preference.

Progress tracking:

- [ ] Remove Rich table output from user-facing default paths touched by the current
  operability wave.
- [ ] Replace backend-contract tables in search timeout/error diagnostics with plain,
  human-facing text.
- [ ] Translate internal backend fields such as `same_project_search_strategy` into
  natural user-facing language or move them behind `--json` or an explicit detail/debug
  path.
- [ ] Keep machine-readable and full-fidelity diagnostic fields in `--json`.
- [ ] Add tests that fail on table borders, wrapped columns, or internal strategy names
  in default human output.
- [ ] Record remaining table-using CLI commands as follow-up inventory if they are
  outside the current review wave.
- [ ] Run manual CLI review and wait for human acceptance before closing the phase.

Agent brief:

- Start with Phase `W06.P07` after or alongside W06.P06 if the same renderer owns the
  output.
- The human reviewer has identified the table problem as endemic. Do not solve only the
  success-path search result table while leaving timeout/error tables in place.
- In default human output, remove:
  - boxed Rich table borders,
  - column truncation,
  - backend-contract labels,
  - raw internal field names such as `same_project_search_strategy`.
- Preferred timeout/error language should answer:
  - did the request time out,
  - is the service reachable,
  - is work currently running,
  - what should the user run next.
- Keep detailed backend capability fields available through JSON; do not delete useful
  diagnostic data from the service contract.
- Avoid broad unrelated rewrites of older CLI commands unless they are directly emitted
  by the reviewed status/jobs/logs/search/timeout surfaces.
- Use `uv run` or `uv run --no-sync` for project commands.

Pipeline:

Hardening:

- Re-run the changed CLI surfaces interactively with a human reviewer:
  - `server status`,
  - `server health`,
  - `server jobs`,
  - `server logs`,
  - service-backed `search`,
  - timeout diagnostics.
- For each command, compare the current behavior against the original audit failure it
  was meant to address.

Research:

- Before each review step, use `vaultspec-rag` and the vault paper trail to restate the
  relevant decision basis:
  - original audit finding,
  - governing ADR,
  - research note,
  - implementation summary where relevant.

ADR / Plan Alignment:

- Treat this wave as a post-implementation human acceptance review, not a new
  implementation decision.
- If the reviewer finds a new semantic conflict, record it as a new audit finding before
  changing code.

Implementation:

- No product implementation by default.
- Only add notes, transcripts, or follow-up findings unless the reviewer explicitly
  authorizes a code change.

Code Review:

- Review the observed CLI output as product behavior:
  - command naming,
  - flag discoverability,
  - table scanability,
  - JSON shape,
  - remediation clarity,
  - consistency with service-domain ownership.

Repeating Patterns:

- Identify whether the new command surfaces teach a stable operator mental model.
- Record any repeating confusion around names, flags, defaults, or output hierarchy.

Manual CLI Persona Test:

- Persona: "Human maintainer reviewing whether the modified CLI now matches the accepted
  operability decisions."
- Review protocol for every command:
  - provide a one-sentence summary in the exact form:
    `I achieved this because of that and this is the outcome.`
  - show the exact CLI command,
  - show the command output,
  - explain the significant CLI input or operation-surface shifts,
  - explain the flags and commands that can manipulate the output,
  - provide the expected output signals and response interpretation,
  - wait for human feedback before running the next command.

Acceptance:

- The reviewer can say whether each changed surface is understandable and actionable.
- The reviewer can identify which flags change scope, filtering, output format, and
  timeout behavior.
- Any remaining rough edges become explicit follow-up findings instead of hidden
  implementation assumptions.

Deliverables:

- Human review transcript or summarized wave note.
- New audit findings for any remaining UX defects.
- Follow-up implementation plan only if the review discovers material gaps.

## Epic Done Criteria

The epic is complete only when all of the following are true:

- Four governing ADRs are accepted or equivalent existing ADRs are explicitly updated.
- `server status` is the canonical operational status surface.
- `/health` remains readiness-only and no longer competes with status.
- `server jobs` is actionable by default and supports focused inspection.
- Empty search results distinguish no-match from stale/missing/mismatched index state.
- Timeout failures explain service state, queue/backpressure, and next action.
- CLI/server/MCP naming is consistent.
- CLI business logic does not depend on MCP-shaped admin semantics.
- Automated tests pass.
- Manual CLI persona testing has been run and recorded for every wave.
- The running service has been managed deliberately: left up when possible, restarted only
  when needed to validate the current implementation.

## Initial Execution Order

1. Wave 00: Baseline and ADR setup.
1. Wave 01: Status convergence and MCP deconflation.
1. Wave 02: Jobs operability.
1. Wave 03: Search freshness and empty-result recovery.
1. Wave 04: Timeout/backpressure/performance readiness.
1. Wave 05: Integration, review, and codification.
1. Wave 06: Human review of the modified CLI interface.

Wave 01 should precede the others because names and ownership boundaries determine how
jobs, search freshness, and timeout diagnostics should be exposed.

## Execution Summary: Wave 05 Integration

Status as of 2026-06-12:

- Status convergence shipped and pushed:
  - `server status --port <port>` is supported.
  - `server status` no longer recommends `server info` as the healthy idle next action.
  - stale `service.json` no longer blocks an explicit healthy localhost port.
- Jobs operability shipped and pushed:
  - bounded jobs list,
  - focused `--job-id` inspection,
  - `--running`, `--failed`, `--since`, source/trigger/query filters,
  - initiator and liveness fields,
  - OS user, serving PID, parent PID, executable/venv context, RSS, and CUDA memory
    snapshots.
- Logs parity shipped and pushed:
  - `GET /logs`, `GET /logs/json`, CLI `server logs`, and MCP `get_logs` share
    `job_id` and `contains` filters.
  - filtered log requests search a bounded maximum window before returning the requested
    filtered tail.
- Search freshness and timeout diagnostics shipped and pushed:
  - service search responses include `index_state`, empty-result diagnostics, and coarse
    route timing.
  - search timing now includes model-load, project-lease, embedding, Qdrant, rerank, and
    postprocess phase fields.
  - timeout errors include health/jobs/backpressure diagnostics and next actions.
  - redundant cold pre-search status work was removed; manual cold search showed
    near-zero `status_seconds`, and remaining cold cost is now visible through setup and
    search phase fields.
  - GPU-lock queue wait is measured as numeric `queue_wait_seconds` and
    `phases.gpu_queue_wait_seconds`.
  - service-backed search responses include `request_id`, and the service logs emit
    `service.lifecycle event=search request_id=<id>` for log correlation.
  - service startup now preloads the shared reranker, and health/status expose
    `reranker_loaded`; manual first-search timing after restart dropped cold
    `project_lease_seconds` from about `6.53s` to about `1.35s`.
- Process identity parity shipped:
  - `/health` reports serving PID and interpreter/venv context.
  - heartbeat and `server start` persist the serving daemon PID instead of the Windows
    launcher PID.
  - `server status`, `server jobs`, and job runtime records agree on the active daemon
    process.
- Code review completed:
  - CR-13 and CR-14 were found in W05 review and fixed before final push.
- Codified project rules:
  - `service-domain-owns-operability`,
  - `cli-operability-needs-persona-tests`,
  - `operator-views-are-bounded`.

Manual integration persona:

- Persona: new maintainer using only `vaultspec-rag` to diagnose and search this repo.
- Commands exercised against resident service PID `62940` on port `8766`:
  - `uv run vaultspec-rag server status --json --port 8766`
  - `uv run vaultspec-rag server status --port 8766`
  - `uv run vaultspec-rag server jobs --limit 5 --port 8766`
  - `uv run vaultspec-rag server logs --json --lines 1 --contains service.lifecycle --port 8766`
  - `uv run vaultspec-rag search "server status jobs logs search timeout diagnostics" --type code --json --max-results 2 --port 8766 --timeout 180`
- Observed:
  - status reported healthy service state and a valid port-specific next action,
  - jobs were bounded and current-state oriented,
  - filtered logs returned a matching lifecycle line even with `--lines 1`,
  - service search returned indexed target metadata and timing.

Remaining deferred work:

- Startup readiness now includes shared reranker loading, which makes first-search
  setup substantially faster but keeps cold service startup around tens of seconds on
  the tested GPU workstation. A future performance pass should compare this service
  startup/readiness tradeoff against prior near-instant benchmark expectations.
