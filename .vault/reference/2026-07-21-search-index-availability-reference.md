---
tags:
  - '#reference'
  - '#search-index-availability'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:29cbef3fb2492692744af8963d56494c5f1d91a95496051dcf531cd56c9f56ab'
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

This reference maps issue 252 to implemented authority at commits
`94b4600fdec57c6ba6ece013755fbe05b8cdfd63` and
`fe1e007b0abcbb92feeaa31bb9672978dc1e5bb3`. General setup and search usage remain in `README.md`,
`docs/getting-started.md`, `docs/search-and-index.md`, and `docs/service-mode.md`.

Here, HTTP means Hypertext Transfer Protocol, MCP means Model Context Protocol, ADR means
architectural decision record, REST means representational state transfer, and JSON means
JavaScript Object Notation. A convergence job is one index operation for an exact resolved
project root and normalized `vault` or `code` source. A canonical snapshot is the copied
`JobManager` resource with a nested `spec` mapping.

## Summary

### Controlling production behavior

- `src/vaultspec_rag/server/_routes.py` owns `POST /search`, captures a canonical job snapshot
  before retrieval, and classifies the response against a second snapshot before emission.
- `src/vaultspec_rag/server/_search_availability.py` owns exact root/source/state matching,
  after-first deduplication, the eight-reference exposure bound, and the canonical HTTP 503
  body. One frozen classification drives body, status, watcher scheduling, and log evidence.
- The same helper recognizes a structured Qdrant collection-missing HTTP 404. The route converts
  it only with exact matching nonterminal evidence and re-raises every declined failure.
- `src/vaultspec_rag/server/_routes.py` retains the selected-source count and ordinary
  `index_missing` or `no_match` diagnostics for authoritative HTTP 200 empty results.

### Canonical job fields

The canonical job-control model carries `spec.operation`, `spec.source`,
`spec.project_root`, `spec.mode`, observed `state`, and an exact ID in `JobSnapshot`. Search
availability reads copied records from `JobManager`. The active large-index-resilience plan
will add generation and publication fields. Snapshot normalization must match the resolved
requested root and normalized source exactly, remain bounded, and avoid creating another state
authority.

The classification contract is exact:

| Identity and match                                                                                          | Nonterminal state                                         | Mode evidence                             |
| ----------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- | ----------------------------------------- |
| Nonempty `id`; `spec.operation == "index"`; exact normalized `spec.source` and resolved `spec.project_root` | `queued`, `running`, `pausing`, `paused`, or `cancelling` | `spec.mode` is `incremental` or `rebuild` |

The request root is already resolved by `_resolve_root`. Snapshot roots are expanded, resolved
without requiring existence, normalized with host path-case rules, and compared for equality.
The search route maps the vault branch to `vault` and the code or codebase branch to `code`.
Records with a missing, non-mapping, or malformed `spec` are ignored. Terminal states,
resource flags, and progress prose never override the observed-state predicate. Exact mode
`rebuild` stays `rebuild`, and exact `incremental` stays `incremental`. Missing, null,
non-string, and unrecognized modes do not match.

An unrelated job from another root or source is never evidence for this request. Each copied
`JobManager` snapshot is already bounded. The response exposes at most eight unique references,
ordered from the second observation followed by first-observation-only jobs and deduplicated
by exact job ID. Rebuilding evidence is computed across every unique match before truncation.
A Boolean truncation member records whether more than eight matched.

### Response and transport constraints

`src/vaultspec_rag/serviceclient/_transport.py:171-205` parses non-2xx JSON bodies.
`src/vaultspec_rag/serviceclient/_transport.py:232-299` returns the body without retaining the
numeric status. `src/vaultspec_rag/serviceclient/_transport.py:733-824` preserves an
`ok: false` search body. It accepts a success only when a nonempty dictionary contains a
`results` list. Empty dictionaries, bare lists, invalid JSON, and other malformed daemon
shapes become the stable `invalid_service_response` failure.

The 503 body contains only `ok`, `error`, `message`, `request_id`, `index_state`, and
`remediation`. `index_state` preserves its existing source, count, and target members. It
changes `status` to `updating` or `rebuilding` and adds `matching_jobs` plus
`matching_jobs_truncated`. Each job reference contains exactly `id`, `state`, and `mode`; the
mode is `incremental` or `rebuild`. The complete example and message template are in the
accepted feature ADR. The body omits `results`, `summary`, `empty`, and `timing`. Direct HTTP
clients observe 503. The shared client preserves the body, and the command-line interface
(CLI) takes its existing structured-failure path because `results` is absent.
`availability_cause` is internal correlation metadata written only to `service.search` logs;
it is not a response member.

The MCP adapter guards the response before `SearchResults.model_validate`. It accepts only a
dictionary success envelope containing a `results` list. For every structured daemon search
failure, the adapter raises an actionable `RuntimeError` containing the error code, message,
and remediation. Non-dictionaries and malformed successes raise `invalid_service_response`.
FastMCP maps these recoverable failures to `isError: true`. The regression uses the official
client against the real MCP stdio shim. It asserts `CallToolResult.isError is True`, actionable
`index_unavailable` text, and no structured `results` member.

Successful nonempty responses and stable empty responses retain their existing HTTP 200
shape. No response performs an implicit reindex. No `Retry-After` header is emitted without a
credible estimate.

### Implemented insertion seam

The central-processing-unit-only server helper normalizes copied snapshots and identifies exact
root-and-source work. `search_route` captures work before retrieval and rechecks at response
time. The second observation is ordered first so its state wins on duplicate IDs. Classification
uses the complete unique match set before exposing at most eight references and records explicit
truncation.

The route also catches only Qdrant `UnexpectedResponse`. A structured collection-missing 404 is
fed through the same classifier with an instantaneous zero count. If exact matching evidence is
absent, or the response is not the recognized collection-missing shape, a bare re-raise preserves
the original backend failure. No path edits `jobs.py`, creates another registry, acquires a GPU
lock, or recomputes generation policy.

### Regression test contract

`src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py` owns the real-service
contract. It builds 256 documents with seed 252, initializes the official MCP session, submits
a real clean vault rebuild, and polls authenticated `/jobs` until the exact job is running. A
five-party barrier then admits:

- a raw matching-root vault request for the guaranteed no-match query;
- raw unrelated-root and unrelated-source controls;
- the production shared HTTP client for the matching query; and
- the official MCP stdio client for the matching query.

The matching raw request returns the exact HTTP 503 body with no `results`; unrelated controls
remain HTTP 200; the shared client preserves the failure envelope; and MCP returns
`CallToolResult.isError: true` with no structured results. After the exact job succeeds, the
matching query returns HTTP 200 with `empty.reason: no_match`.

A second lifecycle stops the daemon, writes a real matching rebuild in `paused` state to the
canonical persistence file, and restarts against the same Qdrant storage. A known published
document remains a nonempty HTTP 200. The completed log reports the exact paused job and bounded
evidence, while the job revision and inactive resource state remain unchanged.

Timeout diagnostics read the live token from `/health` and include exact `/jobs`, `/metrics`,
and response evidence. The green GPU lifecycle proves the public behavior but is not timed to
force the collection-disappearance branch. The preserved real red trace plus focused tests with
real `UnexpectedResponse` and `JobManager` objects prove that narrow conversion and its decline
guards.

The test imports production code and uses real files, Qdrant, and GPU models. It introduces no
fake, stub, mock, monkeypatch, skip, expected failure, or mirrored policy.

### Known races and campaign ownership

Before/after job snapshots narrow but do not eliminate a generation that starts and finishes
between observations. They also cannot identify a failed clean generation after its job
terminates. Collection disappearance during a matching nonterminal job is handled immediately;
durable generation and publication authority remains owned by large-index resilience. Useful
nonempty results remain available, and changing that policy requires another ADR.

The implementation commits changed only their declared search-specific files. Later shared-main
job-control and index-policy commits do not supersede the reviewed search path.
