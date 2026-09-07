---
tags:
  - "#adr"
  - "#explicit-reindex-authority"
date: '2026-09-07'
related:
  - "[[2026-09-07-explicit-reindex-authority-research]]"
  - "[[2026-07-25-non-destructive-index-publication-adr]]"
  - "[[2026-07-21-large-index-resilience-adr]]"
supersedes:
  - '2026-07-25-index-completeness-guard-adr'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:d00dbd190dfc00d7f0cf6eb2ccdcb0f15f43ec22da017b9c6c9354eb25592837'
---
# `explicit-reindex-authority` adr: `Require explicit authority for full-corpus indexing` | (**status:** `accepted`)

## Problem Statement

Incremental indexing is admitted as bounded change reconciliation, but its implementation may silently execute a full-corpus operation. Watchers, search-time integrity repair, restart recovery, backend changes, and configuration drift can therefore spend hours rebuilding without an operator requesting that cost class. The 2026-09-07 incident proves this can degrade serving and repeat after timeout. `2026-09-07-explicit-reindex-authority-research` grounds the mechanism and the affected surfaces. A decision is required because detection of unsafe incremental evidence must not itself grant authority for unbounded repair.

## Considerations

- Completeness detection must remain fail-safe and visible; removing it would restore silent partial-index answers (`2026-09-07-explicit-reindex-authority-research`).
- Generation-scoped publication remains the stable mechanism for preserving served data during explicitly requested rebuilds (`2026-07-25-non-destructive-index-publication-adr`).
- Durable checkpoints and bounded resource policy remain stable parent features, but finalization must expose progress at its own durable boundaries (`2026-07-21-large-index-resilience-adr`).
- Request attribution alone is insufficient: authority must be carried to the indexer boundary that can change cost class (`2026-09-07-explicit-reindex-authority-research`).
- Automatic scoped watcher reconciliation remains useful and does not require full-corpus authority.

## Considered options

**Keep automatic self-heal and increase timeouts.** Rejected. It changes when the unauthorized work fails, not who authorized it, and cannot scale across corpus sizes.

**Bind sidecars to backend identity only.** Rejected as the complete remedy. It prevents foreign-backend evidence from being called loss but leaves compatibility, configuration drift, first-run, and scope-loss escalation.

**Permit full escalation for operator-originated incrementals but refuse watcher and integrity origins.** Rejected. An incremental request still does not communicate full-corpus cost, and direct/in-process callers would retain an ambiguous default.

**Make incremental entry points incapable of executing full-corpus work; return a typed requirement and reserve full entry points for explicit rebuild requests.** Chosen. Detection remains automatic, execution authority does not.

## Constraints

- No incremental method may call a full-index method or silently discard caller scope.
- A full-corpus operation requires an explicit rebuild operation in the admitted job specification or a direct full-index API call.
- Completeness and compatibility checks continue to run. When they require full reconciliation, they raise one typed `full_reindex_required` outcome carrying the reason and explicit remediation.
- Watcher and integrity paths never retry `full_reindex_required`; their convergence/status state remains visible until an operator acts.
- Search remains read-serving and may report shrinkage, but it does not enqueue mutation by default.
- Backend identity is part of published evidence. Foreign-backend evidence is unverifiable for the selected store, not proof that the selected store lost data.
- Explicit rebuild publication remains non-destructive and resumable.
- Route reconciliation must periodically record legitimate durable cleanup progress without allowing UI-only or queue motion to reset the deadline.
- Health must report degraded jobs before they become stalled, and job/status output must preserve typed refusal detail.
- Existing public response shapes may gain fields and error kinds additively; no consumer is required to infer the policy from free text.

## Implementation

Add `full_reindex_required` to the shared job-error taxonomy with remediation naming the explicit rebuild command. Replace every full-rebuild call inside code, document, and vault incremental implementations with that typed refusal. Configuration membership drift that requires global discovery follows the same rule instead of nulling an existing scope.

Carry a backend identity in code and document publication metadata and checkpoint signatures. Integrity evaluation treats a missing or mismatched identity as unverifiable. Disable search-triggered mutation by default while retaining the integrity verdict and degraded status; the configuration switch remains available only for explicitly opted-in legacy operation and still cannot bypass the incremental boundary.

Persist watcher dirty paths with retry authority so process recovery can replay known scope. If exact scope cannot be recovered, report `full_reindex_required` instead of manufacturing unscoped authority. Classify that outcome as terminal for automatic retry.

Add durable reconciliation progress after committed journal/delete batches and surface it in resilience telemetry. Include degraded job counts in `/health`, log compatibility reasons before conversion to typed refusal, and expose requested versus effective operation without allowing the latter to exceed the former.

Change managed-Qdrant startup remediation to describe local-only as a distinct empty backend unless it already has its own compatible publication. It must never imply that switching backends accesses or repairs the managed index.

## Rationale

The chosen boundary is the only option that covers every discovered trigger with one enforceable invariant. It separates permission from diagnosis: the system can know that a full rebuild is necessary without deciding that it may spend the resources. It also fails closed for new callers because the incremental API itself lacks the capability, rather than depending on each watcher, search, CLI, MCP, or future adapter to remember a policy flag (`2026-09-07-explicit-reindex-authority-research`).

Backend identity and progress instrumentation remain necessary but subordinate. Identity prevents false evidence; progress makes authorized work reliable. Neither substitutes for authority. Generation-safe publication remains untouched because it governs how an authorized rebuild publishes, not whether one may begin (`2026-07-25-non-destructive-index-publication-adr`).

## Consequences

Automatic watcher updates remain proportional to known changed paths. A first index, incompatible schema/configuration, genuine shrink, foreign backend, or lost watcher scope stops with an actionable degraded state until an operator explicitly requests a rebuild. This trades unattended convergence for bounded, explainable resource authority.

Search can no longer be the hidden initiator of hours-long work under the default configuration. Existing users who deliberately enabled integrity repair retain detection but will see a typed refusal when full work is required.

Publishing backend identity changes metadata compatibility. Older sidecars must be treated as unknown identity without automatically rebuilding; the next successful explicit publication stamps the identity.

Persisting watcher paths enlarges retry state and requires bounded validation against the canonical root. If recovery data is corrupt, oversized, or foreign, it is ignored as scope evidence and full work remains refused.

Explicit full reconciliation still consumes substantial resources, but it becomes observable, progress-aware, and attributable to an admitted rebuild request. Operators can choose when that cost is acceptable.
