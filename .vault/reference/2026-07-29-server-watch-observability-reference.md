---
tags:
  - '#reference'
  - '#server-watch-observability'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
related:
  - '[[2026-07-27-jobs-tui-adr]]'
  - '[[2026-07-21-managed-log-contract-adr]]'
---

# `server-watch-observability` reference: `the server watch screen observes only indexing`

## Summary

`server --watch` is not a server monitor. The root callback forwards to the same
jobs-only application as `server jobs --watch`, through `run_service_jobs`,
`watch_jobs`, and `run_jobs_tui` (`src/vaultspec_rag/cli/_app.py:373`,
`src/vaultspec_rag/cli/_service_jobs_collection.py:178`,
`src/vaultspec_rag/cli/_service_jobs_watch.py:42`,
`src/vaultspec_rag/cli/_jobs_tui.py:2072`). The application composes a jobs table and
one selected-job log pane, with no search-serving surface
(`src/vaultspec_rag/cli/_jobs_tui.py:733`).

The screen polls rather than consuming an event stream. Jobs refresh through recurring
`GET /jobs` worker calls, while the status bar separately polls health, metrics,
projects, watcher state, and storage (`src/vaultspec_rag/cli/_jobs_tui.py:766`,
`src/vaultspec_rag/cli/_jobs_tui.py:927`,
`src/vaultspec_rag/cli/_jobs_tui_status.py:340`). The selected job's log is fetched only
when selection changes, so new lines are not live until the row is reselected
(`src/vaultspec_rag/cli/_jobs_tui.py:1594`).

The job log request hard-codes 200 lines from the service producer, filtered by job id
(`src/vaultspec_rag/cli/_jobs_tui.py:77`,
`src/vaultspec_rag/cli/_jobs_tui.py:1611`). The renderer nevertheless contains Qdrant
parsing, even though genuine backend output is persisted to the separate
`qdrant.log` producer and the request never selects it
(`src/vaultspec_rag/cli/_jobs_tui_log.py:252`,
`src/vaultspec_rag/qdrant_runtime/_supervise.py:429`). Existing tests conceal that
unreachable production path by placing a Qdrant-shaped record inside a service group
(`src/vaultspec_rag/tests/test_cli_jobs_tui.py:331`,
`src/vaultspec_rag/tests/test_cli_jobs_tui_log.py:520`).

The canonical managed-log domain already exposes grouped raw `service`, `qdrant`, or
`all` sources, with stable source order rather than invented cross-source chronology
(`src/vaultspec_rag/logging_config.py:187`,
`src/vaultspec_rag/logging_config.py:455`). Each source is bounded to 5,000 records and
2 MiB per response (`src/vaultspec_rag/logging_config.py:83`). Filtering is applied
after that bounded tail is read, then the response is cut to the requested line limit,
so unrelated busy traffic can remove an older job's entire history before the
substring job-id filter runs (`src/vaultspec_rag/logging_config.py:488`,
`src/vaultspec_rag/logging_config.py:568`). Log retention is independent of job-record
retention: deleting a job does not delete persisted managed-log records
(`src/vaultspec_rag/jobs.py:898`, `src/vaultspec_rag/_managed_log_sink.py:107`).

`JobsLogView` replaces raw records with parsed, multi-line formatted entries, truncates
each input line to 2,000 characters, and hides polling records by default
(`src/vaultspec_rag/cli/_jobs_tui_log.py:67`,
`src/vaultspec_rag/cli/_jobs_tui_log.py:461`). That is useful as an optional inspection
mode but is not a faithful global log tank.

Search requests have no activity registry. The service keeps only aggregate totals and
last duration (`src/vaultspec_rag/server/_state.py:225`). A structured
`service.search completed|unavailable` event is emitted only through classified
non-combined outcomes, without query text (`src/vaultspec_rag/server/_routes_search.py:363`).
Combined searches bypass classification and validation failures return before that
event site (`src/vaultspec_rag/server/_routes_search.py:606`,
`src/vaultspec_rag/server/_routes_search.py:653`). The TUI's job-id filter could not
show the emitted search records anyway because they carry no job id.

Search pool state is fetched but not painted. The status parser accepts encode, index,
and search pools, while the renderer displays encode and index only
(`src/vaultspec_rag/cli/_jobs_tui_status.py:112`,
`src/vaultspec_rag/cli/_jobs_tui_status.py:429`).

The production seams are the TUI owner and status renderer, the search-route lifecycle,
the authenticated admin routes and service client, and their real Textual,
managed-file, route, and search-activity tests. The existing parsed job-log inspection
must remain distinct from the global source-grouped raw review surface.
