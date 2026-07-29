---
tags:
  - '#research'
  - '#server-watch-observability'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
related:
  - '[[2026-07-29-server-watch-observability-reference]]'
  - '[[2026-07-27-jobs-tui-adr]]'
  - '[[2026-07-21-managed-log-contract-adr]]'
  - '[[2026-06-01-service-observability-adr]]'
---

# `server-watch-observability` research: `equal operational visibility for indexing and search`

The root watch command observes an indexing control surface, not the resident search
service as a balanced two-lane system. It has neither a global view of the raw managed
service/Qdrant log pool nor any view of searches being served. The implementation
already has a suitable bounded raw-log domain, but it lacks a search-request activity
domain. The evidence favors one canonical server-watch application that adapts both
domains: a recurring raw global log view over the existing grouped producers and a new
bounded service-owned active/recent search registry. The ADR must settle ownership,
retention, query privacy, and layout parity.

## Findings

### The root watch command is a jobs alias, not a server monitor

`server --watch` forwards into the same jobs-only screen as `server jobs --watch`.
The application contains a jobs table, status header, and selected-job log pane; it has
no server-activity model or search lane
(`src/vaultspec_rag/cli/_app.py:373`,
`src/vaultspec_rag/cli/_service_jobs_watch.py:42`,
`src/vaultspec_rag/cli/_jobs_tui.py:733`). Carrying a second TUI beside it would leave
two live implementations over the same server state. Extending the concrete owner and
letting the jobs verb select a jobs-focused mode avoids that drift.

### The managed-log contract already supplies the global raw material

The logging domain returns raw records grouped by `service`, `qdrant`, or `all`, spans
rotated generations, preserves producer identity, and makes truncation visible
(`src/vaultspec_rag/logging_config.py:455`,
`src/vaultspec_rag/logging_config.py:568`). Per-source response limits of 5,000 records
and 2 MiB make a recurring snapshot bounded
(`src/vaultspec_rag/logging_config.py:83`). The accepted managed-log boundary rejects a
fabricated cross-source chronology, so the view must keep grouped sources.

The current pane instead requests 200 service-only lines after selection and filters
them by job id (`src/vaultspec_rag/cli/_jobs_tui.py:77`,
`src/vaultspec_rag/cli/_jobs_tui.py:1611`). It is not a live tail and makes the pane's
Qdrant parser unreachable for real backend output, which is written to its own file
(`src/vaultspec_rag/qdrant_runtime/_supervise.py:429`).

### The existing log presentation is an inspection mode, not a raw review surface

Every line is parsed and repacked into formatted blocks, input lines are capped at
2,000 characters, and reflected polling requests are hidden by default
(`src/vaultspec_rag/cli/_jobs_tui_log.py:67`,
`src/vaultspec_rag/cli/_jobs_tui_log.py:461`). The global log tank should default to
sanitized raw records exactly once, with source headings, producer origin, bounds, and
visible truncation markers. Structured formatting and noise suppression may remain
explicit opt-in modes. Terminal control escapes still need sanitizing because raw means
uninterpreted content, not executable terminal bytes.

### Search activity has no state surface to adapt

The server tracks only aggregate search count and last duration
(`src/vaultspec_rag/server/_state.py:225`). It emits a structured completion event only
for classified non-combined searches, without query text
(`src/vaultspec_rag/server/_routes_search.py:363`). Combined requests bypass that site,
and validation failures return before it
(`src/vaultspec_rag/server/_routes_search.py:606`,
`src/vaultspec_rag/server/_routes_search.py:653`). Logs alone therefore cannot produce
complete active/recent query visibility.

A service-owned activity ledger can represent running requests while in flight and
terminal requests after every success, rejection, and exception. It should mirror the
useful jobs-surface shape - bounded list, filters, counts, stable request id - while
remaining a distinct search domain rather than pretending searches are durable jobs.

### Query text needs a different retention boundary from search metadata

Actual query text is necessary for review, but persisting it to rotated logs creates a
longer-lived disclosure channel than the TUI needs. Queries can contain source
fragments, filenames, incident details, or credentials. Full bounded text should live
only in the token-gated in-memory active/recent response; persistent `service.search`
records should carry correlation and outcome metadata but not the query. Result bodies
are unnecessary for operational review and should not enter the ledger.

### Equal visibility requires equal screen presence

On a wide terminal, indexing jobs and search requests can be presented side by side so
concurrent load is visible without navigation. On a narrow terminal, the same data
models can use tabs, with both lane counts in the header. The raw global logs need a
separate full-height view. The existing status parser already fetches the search pool
but omits it from rendering, so search occupancy/waiting should join encode and index
pool state (`src/vaultspec_rag/cli/_jobs_tui_status.py:112`,
`src/vaultspec_rag/cli/_jobs_tui_status.py:429`).

### The credible alternatives are incomplete

Parsing `service.search` records is insufficient because combined, rejected, running,
and exceptional requests lack a complete lifecycle and query text should not be
persisted. Adding only a CLI tab would put domain behavior in an entry point. Building
a second root-monitor TUI would duplicate jobs rendering, status polling, terminal
ownership, and key handling. An unbounded event bus or database-backed audit history is
unnecessary for a live bounded operator surface.

### Validation can remain real-behavior and compute-free

The production ledger can be exercised directly with real request records and real
concurrent threads. Managed-log coverage can write actual rotated files under a
temporary status directory and read them through `query_managed_logs`. Textual's real
pilot can drive the production application with production snapshots and assert rows,
source labels, truncation markers, focus, resizing, and keys. These tests need no
daemon, GPU, fake, mock, stub, patch, monkeypatch, skip, or xfail.

The first regression should prove that one index job, one served query, one service
line, and one Qdrant line all appear in one wide server-watch screen; then prove the
narrow layout preserves both lane counts and exposes each lane and logs by real key
presses. A guard mutation must make one source or lane disappear, observe the named
assertion fail, restore it, and observe it pass.

### Boundaries

This research did not launch the service, execute a search, run a GPU test, or attempt
to repair degraded semantic discovery. It did not investigate remote multi-tenant
deployment or long-term query auditing.

## Sources

- `src/vaultspec_rag/cli/_app.py:373`
- `src/vaultspec_rag/cli/_service_jobs_watch.py:42`
- `src/vaultspec_rag/cli/_jobs_tui.py:77`
- `src/vaultspec_rag/cli/_jobs_tui.py:733`
- `src/vaultspec_rag/cli/_jobs_tui.py:1611`
- `src/vaultspec_rag/cli/_jobs_tui_log.py:67`
- `src/vaultspec_rag/cli/_jobs_tui_log.py:461`
- `src/vaultspec_rag/cli/_jobs_tui_status.py:112`
- `src/vaultspec_rag/cli/_jobs_tui_status.py:429`
- `src/vaultspec_rag/logging_config.py:83`
- `src/vaultspec_rag/logging_config.py:455`
- `src/vaultspec_rag/logging_config.py:568`
- `src/vaultspec_rag/qdrant_runtime/_supervise.py:429`
- `src/vaultspec_rag/server/_routes_search.py:363`
- `src/vaultspec_rag/server/_routes_search.py:606`
- `src/vaultspec_rag/server/_routes_search.py:653`
- `src/vaultspec_rag/server/_state.py:225`
