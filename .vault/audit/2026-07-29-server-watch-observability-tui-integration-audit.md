---
tags:
  - '#audit'
  - '#server-watch-observability'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:a8591a065e910d791e09891edc8dca5a95024f3327828185d512c109564dfadb'
related:
  - "[[2026-07-29-server-watch-observability-plan]]"
---

# `server-watch-observability` audit: `P03 dual-lane TUI integration`

## Scope

Reviewed the P03 dual-lane terminal integration: the one concrete watch owner,
root/jobs mode routing, served-search presentation and polling, search-pool status,
the managed-log boundary, and focused regressions. Review remained source-only where
the environment lacks the test dependencies; no service, compute, or semantic-search
recovery action was performed.

## Findings

### root-watch-routing | medium | Root mode regression is source inspection only

`src/vaultspec_rag/tests/test_cli_server.py` checks that the root callback contains the
server-mode literal. It does not execute the root watch route through its terminal
handoff, so it would not detect the literal becoming unreachable while the live route
stops selecting balanced mode.

### canonical-watch-handoff | medium | Jobs watch delegation is source inspection only

`src/vaultspec_rag/tests/test_cli_jobs_watch_interrupt.py` checks the concrete import
and call spelling. It does not prove a filtered request reaches `run_server_watch` with
the expected mode, because exercising that handoff without a substitute terminal owner
would launch the interactive application.

No critical or high finding was identified. The reviewed production path has one
`ServerWatchApp` owner, independent job/search/log worker groups and generations, a
bounded authenticated activity read, source-grouped raw logs, and search-pool output.

## Recommendations

Before treating the routing regression as fully verified, add a non-interactive
production-owned observation point for watch launch selection, then drive it without a
mock, patch, substitute terminal owner, or resident service. Keep the existing
Textual/transport regressions as the behavior proof for the app itself.

Run the focused Textual, status, and CLI tests plus Ruff and strict type gates once the
existing environment supplies their declared binaries. The absence of those binaries is
a verification limit, not a passing result.
