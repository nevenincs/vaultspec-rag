---
tags:
  - "#adr"
  - "#search-readiness-contract"
date: '2026-09-08'
related:
  - "[[2026-09-08-search-readiness-contract-research]]"
  - "[[2026-09-08-search-readiness-contract-reference]]"
  - "[[2026-06-11-search-freshness-and-empty-results-adr]]"
  - "[[2026-07-21-search-index-availability-adr]]"
  - "[[2026-06-11-server-bound-search-production-readiness-adr]]"
supersedes:
  - '2026-06-11-search-freshness-and-empty-results-adr'
  - '2026-07-21-search-index-availability-adr'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:13395da9e038e8f38043709b3a3caf8ea86f5b1734c278c385737cca8b4fb106'
---

# `search-readiness-contract` adr: `canonical search readiness and bounded freshness waits` | (**status:** `accepted`)

## Problem Statement

Search availability, answer authority, index freshness, and capacity waits are currently
different implicit concepts joined only at selected response branches. A caller cannot choose a
bounded freshness wait, combined search loses constituent state, and adapters do not preserve the
same facts. A single service-domain contract is required before extending any surface. Grounding
and the cross-surface inventory are in `2026-09-08-search-readiness-contract-research` and
`2026-09-08-search-readiness-contract-reference`.

## Considerations

- A complete published generation can remain usable while a newer update runs; freshness and
  availability are separate axes.
- An empty result is authoritative only when every requested source can prove absence against the
  declared freshness target.
- Job terminality is not publication; generation/controller state is the convergence authority.
- Immediate return must remain the default and must retain normal-path performance.
- Every wait must be bounded, cancellable, observable, and attributed to its actual owner.
- The service owns classification; HTTP, CLI, and MCP only transport or render it.
- `Retry-After` is truthful only when derived from a canonical service deadline.

## Considered options

- **Typed per-source model plus revision-based waiter. Chosen.** One fact can drive all surfaces,
  combined aggregation, and exact bounded-wait tests without equating job completion to publish.
- **Extend the current job-snapshot guard and poll it. Rejected.** It is smaller but preserves the
  race between terminal work and generation publication and cannot express controller deferral.
- **Let adapters wait and diagnose. Rejected.** It duplicates matching and retry policy and cannot
  observe service capacity accurately.
- **Block every search behind current indexing. Rejected.** It discards a usable complete
  generation and changes immediate behavior into a global outage/serialization point.

## Constraints

- Reuse canonical job, generation, controller, integrity, and combined-outcome authorities; do not
  create another registry, generation verdict, or adapter classifier.
- Do not widen the GPU lock, add a compute consumer, change retrieval/ranking, or introduce a
  global search lock.
- Bound exposed job/controller evidence and timing histories.
- A disconnect or cancellation unregisters its waiter promptly; no wait outlives its request.
- The generation/accounting and explicit-reindex authorities are accepted and shipped. Adaptive
  watcher control and proportional publication may add inputs later but are not prerequisites;
  absent optional evidence must remain explicitly unknown, never guessed.
- The accepted server-readiness timing and fail-fast constraints remain in force.

## Implementation

### Canonical state

Each requested concrete source receives one immutable readiness fact with closed fields:

- `availability`: `usable`, `unavailable`, or `capacity_limited`;
- `freshness`: `current`, `updating`, `unverifiable`, or `rebuild_required`;
- `absence_authority`: `authoritative` or `non_authoritative`;
- served, observed, and desired generation/revision identities where canonical state supplies them;
- bounded matching job/controller projections, requested/effective mode, phase, controller state,
  integrity evidence, stable reason code, retryability, and remediation;
- a bounded list of named wait observations with cause, waited duration, configured bound, and
  remaining bound.

The wait-cause vocabulary is closed to `index_transition`, `controller_deferral`, `gpu_compute`,
`search_admission`, `project_lease`, `storage_backend`, and `other_service_capacity`. A producer
records only the cause it owns; unknown evidence stays unknown and is never relabelled as indexing.

### Caller policy and waiter

Every surface accepts `immediate` (default) or `bounded` freshness policy. A bounded request names
its condition as `published_at_least`, captured from the service's desired generation/controller
revision at request admission, plus a duration no greater than the service maximum. It succeeds
only when all requested sources have published at least that target or already satisfy it. The
service waits on canonical revision notifications under a monotonic deadline, then terminates as
success, `freshness_wait_timeout`, `request_cancelled`, or another typed failure. Completion of a
job alone never satisfies the condition. Immediate requests never enter the convergence waiter.

### Response and retry contract

Success always carries per-source readiness and an aggregate. A usable prior complete generation
remains HTTP 200 and is marked `updating`; nonempty results remain useful. Empty results are success
only when the aggregate absence authority is authoritative. Otherwise the service emits a typed
failure with no results field. Stable failures include `index_unavailable`,
`index_unverifiable`, `rebuild_required`, `freshness_wait_timeout`, `capacity_limited`, and
`backend_unavailable`, each with `retryable`, observed state, request identifier, wait facts,
bounded matching evidence, and remediation.

HTTP uses 503 for transient unavailable/backend/wait-timeout outcomes, 429 for an admission
refusal with an enforced capacity-reset deadline, and 409 for rebuild-required/refused state.
Cancellation follows transport cancellation rather than manufacturing a response. `Retry-After`
is emitted only as a conservative whole-second delay derived from a canonical future deadline and
never from progress, elapsed duration, or an inferred ETA.

### Combined and adapter behavior

Combined search classifies every concrete source. The aggregate is usable when any requested
source can serve useful results, but retains every degraded constituent. An empty aggregate is
authoritative only when every requested source is authoritative and none failed. A constituent
failure never disappears behind another source's success.

HTTP JSON, CLI JSON, CLI human output, and MCP receive the same service-owned fact. CLI human output
renders a concise state/wait line and bounded identifiers. MCP returns canonical structured content
for both success and recoverable failure while its text names the stable code and remediation; it
must not collapse the envelope into an opaque exception string. Adapters neither match jobs nor
derive freshness, retryability, wait cause, status, or headers.

### Observability and compatibility

Admission is recorded before waiting. Existing limiter, compute/GPU, project lease, transition,
and storage boundaries record their own queue and service durations into the request fact. The
default no-wait path performs bounded snapshot reads only and adds no polling, condition wait, or
new serialization. A cross-surface scenario matrix, virtual clock, cause-specific concurrency
tests, mutation-proven guards, and a load comparison enforce the contract.

On approval this ADR supersedes `2026-06-11-search-freshness-and-empty-results-adr` and
`2026-07-21-search-index-availability-adr`. It retains their useful-generation and truthful-header
direction while replacing their narrow response and MCP-error policies. It narrows, but does not
supersede, the search portions of `2026-06-11-server-bound-search-production-readiness-adr`.

## Rationale

Only a per-source service fact can preserve the distinction between usable, fresh, authoritative,
and waiting across combined search and every adapter. Revision-based convergence uses the durable
authority that actually satisfies freshness, while immediate mode preserves current performance.
The chosen layering follows the reusable seams identified in
`2026-09-08-search-readiness-contract-reference` and closes the ownership gaps established in
`2026-09-08-search-readiness-contract-research`.

## Consequences

Clients gain stable branching, truthful retry semantics, and visible successful-but-updating
answers. Combined search stops erasing degraded sources, and operator timing names actual waits.
The cost is a larger versioned envelope, revision notification plumbing, cancellation cleanup, and
a broad conformance matrix. Optional controller deadlines will often leave `Retry-After` absent;
that omission is intentional. Existing consumers that ignore added success fields continue to
work, while consumers relying on the old MCP exception text or empty-only 503 envelope must move
to the structured contract.
