---
tags:
  - '#plan'
  - '#service-observability'
date: '2026-06-01'
tier: L2
related:
  - '[[2026-06-01-service-observability-adr]]'
  - '[[2026-06-01-service-observability-research]]'
  - '[[2026-06-01-service-operability-adr]]'
---

# `service-observability` `server state surface: status, logs, jobs, metrics (#142)` plan

## Description

Implements ADR-B (#142): the read/observe half of the service-operability
cluster. Every read is reachable from both the CLI and MCP; new HTTP routes are
read-only and token-gated (loopback + `service_token` bearer); control stays on
MCP. Built on the post-split modular packages (`mcp_server/`, `cli/`).

## Steps

Phases are tier-ordered: P01 the net-new in-flight registry (foundational for
jobs), P02 consolidated status, P03 logs, P04 jobs exposure, P05 metrics, P06
docs. Each phase gates on the full relevant test suite plus ruff, ruff-format,
and ty passing; every read lands on both CLI and MCP.

### Phase `P01` - in-flight activity registry (foundational)

Add a thread-safe bounded in-flight activity registry to the mcp_server package and record start/finish from the reindex tool and watcher paths.

- [x] `P01.S01` - Add the thread-safe bounded in-flight activity registry (records id/source/trigger/phase/timestamps); `src/vaultspec_rag/mcp_server/_jobs.py`.
- [x] `P01.S02` - Record activity start/finish in the reindex tool paths; `src/vaultspec_rag/mcp_server/_tools.py`.
- [x] `P01.S03` - Record activity start/finish in the watcher reindex path; `src/vaultspec_rag/watcher.py`.
- [x] `P01.S04` - Add registry unit + GPU integration tests (entries appear/finish, bounded, concurrency); `src/vaultspec_rag/tests/integration/test_jobs_registry.py`.

### Phase `P02` - tier 1 consolidated service state (CLI+MCP)

Add get_service_state MCP tool and a matching CLI subcommand exposing index counts, GPU, projects, and watcher rollup.

- [ ] `P02.S05` - Add the get_service_state MCP tool (index counts + GPU + projects + watcher rollup); `src/vaultspec_rag/mcp_server/_admin_tools.py`.
- [ ] `P02.S06` - Add the server service info CLI subcommand over the \_try_mcp_admin seam; `src/vaultspec_rag/cli/_service_info.py`.
- [ ] `P02.S07` - Add get_service_state MCP + CLI parity tests; `src/vaultspec_rag/tests/integration/test_service_state.py`.

### Phase `P03` - tier 2a logs (tool + CLI + HTTP)

Add a rotated-log reader, a get_logs MCP tool, a server service logs CLI subcommand, and a token-gated read-only GET /logs HTTP route.

- [ ] `P03.S08` - Add the rotated-log reader spanning service.log + .log.N tolerant of mid-rollover; `src/vaultspec_rag/logging_config.py`.
- [ ] `P03.S09` - Add the read-only HTTP routes module + loopback/service_token bearer token-check helper; `src/vaultspec_rag/mcp_server/_routes.py`.
- [ ] `P03.S10` - Register the GET /logs route on the inner Starlette app; `src/vaultspec_rag/mcp_server/_main.py`.
- [ ] `P03.S11` - Add the get_logs MCP tool; `src/vaultspec_rag/mcp_server/_admin_tools.py`.
- [ ] `P03.S12` - Add the server service logs CLI subcommand; `src/vaultspec_rag/cli/_service_logs.py`.
- [ ] `P03.S13` - Add logs reader unit tests + GET /logs gating + MCP/CLI parity tests; `src/vaultspec_rag/tests/integration/test_service_logs.py`.

### Phase `P04` - tier 2b jobs exposure (CLI+MCP+HTTP)

Expose the in-flight registry via a get_jobs MCP tool, a server service jobs CLI subcommand, and an optional token-gated GET /jobs route.

- [ ] `P04.S14` - Add the get_jobs MCP tool and the GET /jobs JSON route; `src/vaultspec_rag/mcp_server/_admin_tools.py`.
- [ ] `P04.S15` - Add the server service jobs CLI subcommand; `src/vaultspec_rag/cli/_service_jobs.py`.
- [ ] `P04.S16` - Add jobs exposure MCP/CLI parity + route gating tests; `src/vaultspec_rag/tests/integration/test_service_jobs.py`.

### Phase `P05` - tier 3 metrics

Add inline counters/gauges in package state and a token-gated read-only GET /metrics Prometheus-text route, with no background collector thread.

- [ ] `P05.S17` - Add inline counters/gauges to package state, incremented by search/reindex paths; `src/vaultspec_rag/mcp_server/_state.py`.
- [ ] `P05.S18` - Register the token-gated GET /metrics Prometheus-text route emitted directly; `src/vaultspec_rag/mcp_server/_routes.py`.
- [ ] `P05.S19` - Add metrics counter + /metrics format + gating tests; `src/vaultspec_rag/tests/integration/test_service_metrics.py`.

### Phase `P06` - docs parity

Document the new tools, subcommands, HTTP routes, and gating in the builtin rule (synced) and the docs tree.

- [ ] `P06.S20` - Document the new tools/subcommands/routes + gating in the builtin rule, then sync; `.vaultspec/rules/rules/vaultspec-rag.builtin.md`.
- [ ] `P06.S21` - Document the new CLI subcommands + HTTP routes + env/gating in the docs tree; `docs/cli.md`.

## Parallelization

P01 is foundational (P04 depends on it). P02, P03, P05 are mutually independent
and depend only on the shared HTTP-routes/token helper introduced in P03 for
their HTTP pieces (their MCP+CLI pieces are independent). P06 is last. Within a
phase, implementation steps precede their test step.

## Verification

The plan is complete when every step is closed. Gates: every new read is
reachable from BOTH the CLI and MCP; HTTP routes are read-only and token-gated
while `/health` stays ungated; no background thread is introduced (metrics/jobs
update inline); the in-flight registry is bounded and thread-safe; the full
relevant test suite (incl. real-GPU integration) plus ruff, ruff-format, and ty
are clean; docs updated in the builtin rule and docs tree. Final sign-off is a
vaultspec-code-review pass.
