---
tags:
  - '#reference'
  - '#search-index-availability'
date: '2026-07-21'
modified: '2026-07-22'
related:
  - "[[2026-07-21-search-index-availability-research]]"
  - "[[2026-07-21-search-index-availability-adr]]"
  - "[[2026-07-21-search-index-availability-plan]]"
  - "[[2026-06-11-search-freshness-and-empty-results-adr]]"
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-service-job-control-plan]]"
  - "[[2026-07-21-large-index-resilience-adr]]"
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `search-index-availability` reference: `HTTP route, job state, transport, and regression seams`

This reference maps issue 252 to production code at commit
`a5881646a61b41daef989d4c5dd7010fe32f643b`. Coding starts only after the related ADR and plan
are accepted. General setup and search usage remain in `README.md`,
`docs/getting-started.md`, `docs/search-and-index.md`, and `docs/service-mode.md`.

Here, HTTP means Hypertext Transfer Protocol, MCP means Model Context Protocol, ADR means
architectural decision record, REST means representational state transfer, and JSON means
JavaScript Object Notation. A convergence job is one index operation for an exact resolved
project root and normalized `vault` or `code` source. A compatibility snapshot is the legacy
flat job record. A canonical snapshot is the service-job-control resource with a nested `spec`
mapping.

## Summary

### Controlling production behavior

- `src/vaultspec_rag/server/_routes.py:349-494` owns `POST /search`. It retrieves first,
  obtains the selected-source count from `phase_timing["indexed_count"]`, builds an ordinary
  success dictionary, and returns `JSONResponse(result)` with the default HTTP 200.
- `src/vaultspec_rag/server/_routes.py:210-226` maps only zero count to `missing` and positive
  count to `available`. `src/vaultspec_rag/server/_routes.py:229-251` maps empty results only
  to `index_missing` or `no_match`.
- `src/vaultspec_rag/server/_models.py:78` does not control the REST response. The route already
  emits fields outside that Pydantic model.
- `src/vaultspec_rag/server/_routes.py:254-321` exposes copied job snapshots through `/jobs`.

### Current and canonical job fields

The compatibility snapshot exposed by `src/vaultspec_rag/server/_jobs.py` carries top-level
`source`, `phase`, and `initiator.project_root`. It does not retain clean or generation state.
Current reindex workers originate in `start_reindex_vault` and
`start_reindex_codebase`. The route reads their copied records through legacy `snapshot`.
Line numbers are intentionally omitted because the service-job-control campaign has
uncommitted ownership of `jobs.py`.

The canonical job-control model carries `spec.operation`, `spec.source`,
`spec.project_root`, `spec.mode`, observed `state`, and an exact ID in `JobSnapshot`. The
active large-index-resilience plan will add generation and publication fields. Snapshot
normalization must therefore match the resolved requested root and normalized source exactly,
remain bounded, and tolerate both shapes without creating another state authority.

The classification contract is exact:

| Shape         | Identity and match                                                                                          | Nonterminal state                                         | Mode evidence                                      |
| ------------- | ----------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- | -------------------------------------------------- |
| Canonical     | Nonempty `id`; `spec.operation == "index"`; exact normalized `spec.source` and resolved `spec.project_root` | `queued`, `running`, `pausing`, `paused`, or `cancelling` | Only `spec.mode == "rebuild"` proves rebuilding    |
| Compatibility | Used only when `spec` is absent; nonempty `id`; exact top-level `source` and `initiator.project_root`       | `phase == "running"`                                      | None; expose `mode: null` and `status: "updating"` |

The request root is already resolved by `_resolve_root`. Snapshot roots are expanded, resolved
without requiring existence, normalized with host path-case rules, and compared for equality.
The search route maps the vault branch to `vault` and the code or codebase branch to `code`.
If the `spec` key exists, the record is canonical. A non-mapping or malformed canonical record
is ignored instead of falling back. Terminal states, resource flags, and progress prose never
override the observed-state predicate. Exact mode `rebuild` stays `rebuild`, exact
`incremental` stays `incremental`, and missing, null, non-string, or unrecognized mode becomes
`null`.

An unrelated job from another root or source is never evidence for this request. Each copied
registry snapshot is already bounded. The response exposes at most eight unique references,
ordered from the second observation followed by first-observation-only jobs and deduplicated
by exact job ID. Rebuilding evidence is computed across every unique match before truncation.
A Boolean truncation member records whether more than eight matched.

### Response and transport constraints

`src/vaultspec_rag/serviceclient/_transport.py:171-205` parses non-2xx JSON bodies.
`src/vaultspec_rag/serviceclient/_transport.py:232-299` returns the body without retaining the
numeric status. `src/vaultspec_rag/serviceclient/_transport.py:733-824` preserves an
`ok: false` search body, while `src/vaultspec_rag/cli/_search.py:50-73` treats any dictionary
containing `results` as success.

A compatible 503 body contains only `ok`, `error`, `message`, `request_id`, `index_state`, and
`remediation`. `index_state` preserves its existing source, count, and target members. It
changes `status` to `updating` or `rebuilding` and adds `matching_jobs` plus
`matching_jobs_truncated`. Each job reference contains exactly `id`, `state`, and `mode`; the
mode is `incremental`, `rebuild`, or `null`. The complete example and message template are in
the accepted feature ADR. The body omits `results`, `summary`, `empty`, and `timing`. Direct
HTTP clients observe 503. The shared client preserves the body, and the command-line
interface (CLI) takes its existing structured-failure path because `results` is absent.

The MCP adapter needs a separate guard before `SearchResults.model_validate`. Its current
default `results` list would otherwise turn `ok: false` into a successful empty tool result.
For every structured daemon search failure, the adapter raises an actionable `RuntimeError`
containing the error code, message, and remediation; FastMCP maps that recoverable failure to
`isError: true`. The regression uses the official client against the real MCP stdio shim. It
asserts `CallToolResult.isError is True`, actionable `index_unavailable` text, and no
structured `results` member.

Successful nonempty responses and stable empty responses retain their existing HTTP 200
shape. No response performs an implicit reindex. No `Retry-After` header is emitted without a
credible estimate.

### Narrow insertion seam

A central-processing-unit-only helper in the server domain can normalize copied job
snapshots and identify exact root-and-source work. `search_route` can capture matching work
before retrieval and recheck before emitting an empty success. The first observation closes
work already nonterminal at admission. The second closes work that begins during retrieval.
A nonempty result stays successful.

This helper belongs beside the existing search diagnostics in
`src/vaultspec_rag/server/_routes.py` or in a narrowly named server leaf module. It must not
edit `src/vaultspec_rag/jobs.py`, add a registry, acquire GPU locks, or recompute future
generation policy.

### Regression test contract

`src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py:52-122` already owns
real-service empty-index diagnostics. The regression uses the existing synthetic corpus
builder with 256 documents and seed 252, a real clean vault reindex, and the returned exact
job ID. It polls authenticated `/jobs` every 50 milliseconds for at most 10 seconds. A
compatibility job is ready when `phase: running` and `progress.step` is not `queued`. A
canonical job is ready when `state: running` and `resources.project_lease_held: true`. It then
admits the concurrent probes and sends raw `POST /search` with the query
`type:nonexistent availability authority probe` and a 300-second deadline. It asserts:

- an exact matching nonterminal convergence job plus an empty outcome returns HTTP 503;
- the body equals the ADR-defined contract, reports the exact job ID, and omits `results`;
- unrelated root or source work does not cause 503;
- after matching work converges, the same guaranteed non-match returns HTTP 200 with the
  ordinary empty diagnostic;
- the shared HTTP search client preserves the structured error instead of manufacturing an
  empty success;
- the real MCP stdio result has `isError: true` before `SearchResults` can add an empty list.

The primary root contains the generated corpus. The unrelated-root request uses a second
empty project. The unrelated-source request searches code in the primary root with
`include_paths: ["__availability_no_match__/**"]`. The nonempty request searches the primary
vault with the first manifest needle. Shared-client and MCP requests use the primary root and
guaranteed no-match query. One primary clean job is sufficient because every probe is admitted
concurrently after that job owns the primary project lease.

The test polls the exact job every 100 milliseconds for at most 300 seconds until compatibility
`phase: done` or canonical `state: succeeded`. Other terminal outcomes fail with exact job
evidence. Timeout diagnostics include `/health`, the exact `/jobs` response, `/metrics`, and
the last search response. All invariants are staged into one real service-and-job lifecycle so
the local graphics processing unit (GPU) model is loaded once, but each plan Step remains a
separate commit.

The test imports production code and uses real files, Qdrant, and GPU models. It introduces no
fake, stub, mock, monkeypatch, skip, expected failure, or mirrored policy.

### Known races and campaign ownership

Before/after job snapshots narrow but do not eliminate a generation that starts and finishes
between observations. They also cannot identify a failed clean generation after its job
terminates. The accepted resilience ledger closes both gaps by publishing generation identity
and `rebuild_incomplete` state for destructive generations. This fix must consume that state
for otherwise-empty responses when it becomes available. It does not block useful nonempty
responses; changing that policy requires another ADR.

`src/vaultspec_rag/jobs.py` and `src/vaultspec_rag/memory_probe.py` are already modified by
other campaigns. The service-job-control plan also reserves later edits to
`src/vaultspec_rag/server/_routes.py`, `src/vaultspec_rag/server/_routes_jobs.py`, and
`src/vaultspec_rag/serviceclient/_transport.py`. Keep the current change narrow and coordinate
the route edit rather than overwriting concurrent work.
