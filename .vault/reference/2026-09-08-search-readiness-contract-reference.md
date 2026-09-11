---
tags:
  - '#reference'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:b18e80e7bd0f2fadd9d1dd8168264d08d793762964f9c2334e86b0c9a110dabc'
related:
  - "[[2026-09-08-search-readiness-contract-research]]"
  - "[[2026-07-21-search-index-availability-reference]]"
---

# `search-readiness-contract` reference: `cross-surface search contract inventory`

This inventory traces the current service classifier through HTTP, CLI, MCP, and combined search,
and identifies the canonical job, generation, index-state, timing, and outcome models to extend.

## Summary

### Canonical production seams

- `src/vaultspec_rag/server/_search_availability.py` owns exact matching, bounded job evidence,
  collection-disappearance recognition, and the empty-only 503. Do not reproduce it in adapters.
- `src/vaultspec_rag/_search_state.py` owns shared index-state shaping; add a typed
  readiness/freshness model beside it rather than more unrelated dictionaries.
- `src/vaultspec_rag/job_models.py` and `src/vaultspec_rag/jobs.py` own mode, generation,
  resilience, controller, and generation-summary facts. Search should project copied state.
- `src/vaultspec_rag/server/_routes_search.py` owns request validation, response shaping, timing,
  HTTP status, and combined dispatch. Its combined branch currently skips classification.
- `src/vaultspec_rag/server/_search_activity.py`, compute tickets, the search limiter, project
  lease, and store calls are existing measurement boundaries. Do not add serialization.
- `src/vaultspec_rag/search/_outcomes.py` is the per-domain combined authority and should carry
  each source readiness fact.
- `src/vaultspec_rag/serviceclient/_search_transport.py` preserves service envelopes.
- `src/vaultspec_rag/cli/_search.py` and `src/vaultspec_rag/mcp/_tools.py` are renderers. MCP must
  stop reducing transient failures to a string.

### Surface conformance inventory

| Surface   | Current behavior                                                      | Required seam                                             |
| --------- | --------------------------------------------------------------------- | --------------------------------------------------------- |
| Service   | Empty plus matching work becomes 503; updating success loses evidence | Typed per-source readiness/freshness/wait fact            |
| HTTP      | One aggregate state; no wait or retry contract                        | Validate policy and map canonical codes/deadlines         |
| CLI JSON  | Preserves payload                                                     | Pass through the canonical envelope                       |
| CLI human | Drops freshness/job/wait facts                                        | Render concise state, identifiers, cause, and remediation |
| MCP       | Stringifies failures                                                  | Preserve structured content and actionable text           |
| Combined  | Bypasses availability                                                 | Preserve per-source facts and derive a coherent aggregate |

### Test anchors and missing proof

`src/vaultspec_rag/tests/test_search_availability.py` pins current classification;
`test_http_search_errors.py` pins the combined bypass and must change; `test_search_outcomes.py`
covers mixed outcomes; `test_cli_search.py` covers rendering; and the service diagnostics modules
cover HTTP and MCP.

Add one service-domain scenario matrix reused across adapters, virtual-clock deadline/wake/cancel
tests, distinct wait-cause concurrency tests, mixed combined states, and a load regression. Every
negative or architectural guard must be mutation-proven on its named assertion.

### Compatibility constraints

Immediate return remains default. A complete prior generation stays usable during updates, but an
empty answer is non-authoritative when evidence cannot prove absence. Emit `Retry-After` only from
a defensible canonical deadline. Preserve retrieval/ranking behavior, GPU lock scope, bounded
evidence, and no-wait performance. Explicitly supersede the prior MCP string-error rule.
