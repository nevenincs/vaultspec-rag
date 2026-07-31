---
tags:
  - '#plan'
  - '#server-watch-observability'
date: '2026-07-29'
modified: '2026-07-30'
tier: L2
related:
  - '[[2026-07-29-server-watch-observability-adr]]'
  - '[[2026-07-29-server-watch-observability-research]]'
  - '[[2026-07-29-server-watch-observability-reference]]'
---

# `server-watch-observability` plan

Deliver one bounded server-watch console that shows indexing jobs, served searches, and
the actual source-grouped managed log pool without launching compute during development.

## Description

Phase P01 implements the service-owned search activity truth required by the accepted
server-watch decision. Phase P02 adapts the already-accepted managed-log contract into a
faithful global raw view. Phase P03 replaces the jobs-only composition with one
responsive owner used by both watch entry points. The authorizing ADR, research, and
reference in frontmatter define privacy, retention, source identity, and compute-free
verification constraints for every Step.

## Steps

### Phase `P01` - Server search activity ledger

Add bounded service-domain truth for active and recent search requests, including exactly-once terminal accounting and authenticated reads.

- [x] `P01.S01` - Write compute-free regression coverage for active, retained, filtered, bounded, concurrent, and every terminal search outcome; `src/vaultspec_rag/tests/test_search_activity.py`.
- [x] `P01.S02` - Implement typed exactly-once search activity lifecycle and finite retention; `src/vaultspec_rag/server/_search_activity.py`.
- [x] `P01.S03` - Own the process-wide search activity ledger beside existing server metrics; `src/vaultspec_rag/server/_state.py`.
- [x] `P01.S04` - Record admission and terminal outcomes across every search route branch without persisting query text; `src/vaultspec_rag/server/_routes_search.py`.
- [x] `P01.S05` - Expose a token-gated bounded and filterable search activity response; `src/vaultspec_rag/server/_routes.py`.
- [x] `P01.S06` - Add the canonical search activity admin transport mapping; `src/vaultspec_rag/serviceclient/_transport.py`.

### Phase `P02` - Source-grouped raw global logs

Expose both managed producers in a recurring raw terminal view while preserving origin, bounds, sanitization, and truncation truth.

- [x] `P02.S07` - Write real managed-file and Textual regressions proving both sources and every raw record remain visible; `src/vaultspec_rag/tests/test_cli_jobs_tui_log.py`.
- [x] `P02.S08` - Implement the source-grouped raw log widget with sanitization and visible bounds markers; `src/vaultspec_rag/cli/_server_watch_log.py`.
- [x] `P02.S09` - Poll the canonical all-source managed-log response with generation ordering and independent failure state; `src/vaultspec_rag/cli/_jobs_tui.py`.

### Phase `P03` - Dual-lane server watch application

Unify root and jobs watch entry points under one responsive owner that gives indexing and search equal operational visibility.

- [x] `P03.S10` - Write the wide and narrow dual-lane server-watch regression before changing composition; `src/vaultspec_rag/tests/test_cli_jobs_tui.py`.
- [x] `P03.S11` - Replace the jobs-only owner with one responsive ServerWatchApp and migrate imports without aliases; `src/vaultspec_rag/cli/_jobs_tui.py`.
- [x] `P03.S12` - Route root watch to complete mode and jobs watch to the same owner in jobs-focused mode; `src/vaultspec_rag/cli/_service_jobs_watch.py`.
- [x] `P03.S13` - Render search pool occupancy and waiting beside encode and index pools; `src/vaultspec_rag/cli/_jobs_tui_status.py`.
- [x] `P03.S14` - Run focused lint type and compute-free unit lanes and perform formal code review; `server-watch-observability changed files`.

## Parallelization

P01 and P02 can execute concurrently with exclusive ownership: the service-ledger agent
owns server activity, route, transport, and ledger tests; the global-log agent owns the
raw widget and managed-log/TUI-log tests. P03 depends on the payload contracts from both
and owns application composition, watch-mode routing, status rendering, and the
end-to-end Textual regression. Only P03 may integrate concurrent edits in the shared TUI
owner; earlier agents must coordinate before touching it.

## Verification

- The production search ledger passes active, exactly-once terminal, bounded retention,
  filter, concurrency, and every-terminal-branch tests without starting the service.
- Real rotated service and Qdrant files render under distinct source headings with raw
  record identity, sanitization, origin, bounds, and truncation markers preserved.
- A real Textual pilot shows one index job and one search concurrently when wide, keeps
  both lane counts when narrow, and reaches both lanes and global logs by real key
  presses.
- Persistent managed logs contain request correlation and outcome metadata but no query
  text or search result bodies.
- Search pool occupancy and waiting are visible beside encode and index pool state.
- The focused Ruff, formatter check, BasedPyright, and compute-free unit commands each
  exit zero independently.
- The raw-log and dual-lane guards have recorded fail-then-pass mutation proof, with no
  mutation left on disk.
- Formal code review confirms no compatibility owner, duplicate implementation, fake,
  mock, stub, patch, monkeypatch, skip, xfail, service launch, or GPU path was introduced.
