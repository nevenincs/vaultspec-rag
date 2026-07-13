---
tags:
  - '#plan'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
tier: L2
related:
  - '[[2026-07-13-control-plane-affordances-adr]]'
  - '[[2026-07-13-control-plane-affordances-research]]'
---

# `control-plane-affordances` plan

### Phase `P01` - Root-scoped survey lookup

Expose the per-root collection prefix and namespace lookup through the one survey surface: route, transport, CLI, and MCP all pass a root parameter to GET /storage/survey, which computes the authoritative prefix server-side.

- [x] `P01.S01` - Extend the storage survey route to accept an optional root query parameter, resolve it through root_collection_prefix, narrow the namespace list to the matching prefix, and add the top-level queried_root object (present only when root is passed, returned even for unindexed roots); `src/vaultspec_rag/server/_routes.py`.
- [x] `P01.S02` - Admit root into the survey transport params and thread the optional root argument through the MCP survey client and the get_storage_survey tool surface; `src/vaultspec_rag/serviceclient/_transport.py`.
- [x] `P01.S03` - Add --root to server storage survey, pass it through both the service-first and CLI-direct paths, and render queried_root in human and --json output; `src/vaultspec_rag/cli/_service_storage.py`.
- [x] `P01.S04` - Cover the root-scoped lookup end to end: indexed root returns prefix plus populated namespaces, unindexed root returns prefix plus empty list, and the CLI and MCP adapters pass the parameter through; `src/vaultspec_rag/tests/integration/test_storage_survey_service.py`.

### Phase `P02` - Stop envelope parity

Give server stop the --json outcome envelope contract already shipped for start: one structured envelope per exit path, idempotent success statuses, and a hard failure for the identity-unconfirmed skip.

- [x] `P02.S05` - Add --json to server stop with one envelope per exit path (stopped, already_stopped, cleaned, reclaimed as ok:true and identity_unconfirmed as ok:false) and make the identity-unconfirmed skip exit 1 in both human and json modes, covering the --port variant; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P02.S06` - Assert the stop --json envelope and exit code on each exit path alongside the existing start --json matrix; `src/vaultspec_rag/tests/integration`.

## Description

Implements the accepted control-plane-affordances ADR: a root-scoped lookup
on the storage survey (the route computes the authoritative collection prefix
via `root_collection_prefix` and returns it as `queried_root`, threaded
through the serviceclient transport, the CLI `--root` option, and the MCP
tool argument) and `--json` envelope parity for `server stop` matching the
start contract from the rag-broker-affordances work. The vaultspec-dashboard
team's embedding-scroll path and start/stop broker scripting are the
consumers; landing this lets them delete their sanctioned prefix
recomputation exception.

## Steps

## Parallelization

The two Phases are independent and may run in parallel. Within `P01`, `S01`
(route) must land before `S02`/`S03` (adapters), and `S04` (tests) last.
Within `P02`, `S05` precedes `S06`.

## Verification

- `GET /storage/survey?root=<path>` returns `queried_root.prefix` equal to
  `root_collection_prefix(<path>)` for both indexed (populated namespaces)
  and unindexed (empty namespaces) roots; integration test asserts both.
- `server storage survey --root` and MCP `get_storage_survey(root=...)` pass
  the parameter through to the one route; adapters compute nothing.
- `server stop --json` emits exactly one envelope per exit path; the
  identity-unconfirmed skip exits 1 in both modes; the not-running case is
  `already_stopped` with exit 0; tests assert envelope and exit code.
- Full local gate green: ruff, basedpyright/ty, and the unit + integration
  test suites; GPU-touching tests run locally per project mandate.
