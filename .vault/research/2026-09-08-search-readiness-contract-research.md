---
tags:
  - '#research'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:eb0285ad8b3803e03e9b359849c80d1b9801b7c2e47f84417aea640407336702'
related:
  - "[[2026-06-11-search-freshness-and-empty-results-adr]]"
  - "[[2026-06-11-server-bound-search-production-readiness-adr]]"
  - "[[2026-07-21-search-index-availability-adr]]"
---

# `search-readiness-contract` research: `unified readiness, freshness, bounded waits, and backpressure`

Search needs one service-owned account of whether a request can use the served index, how
current and authoritative that answer is, and what bounded capacity or convergence wait
occurred. The existing code has the right raw authorities but exposes only a narrow empty-result
guard. The evidence favors a neutral per-source readiness model, a combined aggregate derived
from those source facts, and an event/revision-based bounded waiter; the ADR must fix the exact
state vocabulary, wait target, transport schema, aggregation rules, and compatibility boundary.

## Findings

### Availability is narrower than the evidence already available

The shared index-state model can say only `missing` or `available` and cannot express served or
desired generation, freshness, authority, waits, or job/controller evidence
(`src/vaultspec_rag/_search_state.py:107`). The only availability classifier matches exact
root/source nonterminal work, exposes at most eight jobs, and rewrites only an empty result to
HTTP 503 (`src/vaultspec_rag/server/_search_availability.py:123`,
`src/vaultspec_rag/server/_search_availability.py:292`). A nonempty result retains HTTP 200 but
loses the matching-job evidence already computed. The failure has no retryability, deadline,
wait duration, remaining bound, generation, or controller fields
(`src/vaultspec_rag/server/_search_availability.py:210`).

Canonical snapshots already carry requested/effective mode, generation, resilience, and
controller/runtime state (`src/vaultspec_rag/job_models.py:548`,
`src/vaultspec_rag/job_models.py:651`). The job manager owns per-source generation summaries
(`src/vaultspec_rag/jobs.py:685`). A new contract can project those facts without another state
authority.

### Wait attribution is incomplete and sometimes unobservable

Compute-ticket admission happens before returned phase timing, while the search limiter wraps the
whole worker without separate measurement (`src/vaultspec_rag/server/_routes_search.py:699`,
`src/vaultspec_rag/server/_routes_search.py:995`). Search-activity admission waits on a condition
without a deadline and creates its record only after capacity opens, so a queued request cannot
explain its wait while queued (`src/vaultspec_rag/server/_search_activity.py:187`). Named bounded
measurements belong at existing admission, limiter, compute/GPU, project lease,
index/controller, and storage boundaries. Attribution must not add GPU serialization.

### Combined search and adapters break the one-fact boundary

Combined search bypasses availability classification (`src/vaultspec_rag/server/_routes_search.py:979`).
Its domain outcomes lack per-source readiness (`src/vaultspec_rag/search/_outcomes.py:95`), so an
aggregate cannot preserve a degraded constituent or prove an empty combined answer authoritative.

CLI JSON preserves the HTTP body, but human success omits updating/job/generation facts
(`src/vaultspec_rag/cli/_search.py:128`). MCP turns every structured service failure into a plain
`RuntimeError` (`src/vaultspec_rag/mcp/_tools.py:137`). The service client also synthesizes
timeout diagnosis instead of passing through canonical wait attribution
(`src/vaultspec_rag/serviceclient/_search_transport.py:138`).

### The prior decisions require an explicit roll-up

The accepted empty-result decision requires freshness, target, and active-job context. The later
availability decision protects only empty responses, keeps useful nonempty results available,
omits `Retry-After` without a credible estimate, and leaves generation authority to future work.
The new ADR must retain nonempty availability and truthful header semantics while superseding the
narrow envelope, MCP string-error policy, and job-only proof of freshness.

### The ADR has material choices to close

The decision must pin readiness/freshness enums and authority invariants; the freshness target;
immediate default and maximum bounded wait; monotonic timeout, wake, and cancellation semantics;
one bounded-evidence schema; HTTP mapping; named wait causes; combined aggregation; MCP structured
failure behavior; and hot-path compatibility. Polling job snapshots is simpler but weaker because
job terminality is not publication. Adapter-side waits repeat existing ownership drift.

FastMCP wire behavior and load thresholds were not independently benchmarked here; the plan must
pin them through the official MCP client and existing benchmark harness.

## Sources

- `src/vaultspec_rag/_search_state.py:107`
- `src/vaultspec_rag/server/_search_availability.py:123`
- `src/vaultspec_rag/server/_search_availability.py:210`
- `src/vaultspec_rag/server/_search_availability.py:292`
- `src/vaultspec_rag/server/_routes_search.py:699`
- `src/vaultspec_rag/server/_routes_search.py:979`
- `src/vaultspec_rag/server/_routes_search.py:995`
- `src/vaultspec_rag/server/_search_activity.py:187`
- `src/vaultspec_rag/job_models.py:548`
- `src/vaultspec_rag/job_models.py:651`
- `src/vaultspec_rag/jobs.py:685`
- `src/vaultspec_rag/search/_outcomes.py:95`
- `src/vaultspec_rag/cli/_search.py:128`
- `src/vaultspec_rag/mcp/_tools.py:137`
- `src/vaultspec_rag/serviceclient/_search_transport.py:138`
- `.vault/adr/2026-06-11-search-freshness-and-empty-results-adr.md:18`
- `.vault/adr/2026-06-11-server-bound-search-production-readiness-adr.md:19`
- `.vault/adr/2026-07-21-search-index-availability-adr.md:18`
- https://github.com/nevenincs/vaultspec-rag/issues/471
