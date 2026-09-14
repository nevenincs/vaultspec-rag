---
tags:
  - '#audit'
  - '#search-readiness-contract'
date: '2026-09-14'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:f358e27892a659d3edbbfee8a4e4d60c43a4d29f2feac1aa5118e185ddea9d89'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# `search-readiness-contract` audit: `final closeout`

## Scope

The accepted decision, complete readiness implementation, closeout commits, prior audit,
focused evidence, repository gates, and benchmark record were reviewed independently. The
review covered service ownership, cancellation cleanup, retry truth, GPU lock scope, storage
attribution, result compatibility, and the three prior findings.

## Findings

### incomplete-gates | high | Required comparison integration and repository gates are not green

The CPU control is accepted, but the baseline has no same-host resident-service latency,
throughput, limiter, or GPU-queue measurements. The resident-service integration lane exited
before collection because no compatible machine-pointer service was available. Repository format,
type, vault, and full-test gates also failed on pre-existing release, store, embeddings, pin, and
legacy-vault findings outside this lane. `S52`, `S55`, and `S56` were reopened through the owning
plan verb.

### compatibility-proof | medium | Result transport coverage is narrower than the Step contract

`TestResultShape.test_service_serialization_preserves_rank_order_and_exact_shape` proves that the
service transport keeps its input ordering, scores, public fields, and private rerank exclusion.
It does not drive retrieval, reranking, route wrapping, and combined aggregation as one baseline.
`S54` was reopened pending that proof.

### readiness-isolation-proof | low | Registry isolation does not prove every search lock boundary

`test_bounded_wait_releases_registry_lock_for_parallel_work` proves a pending waiter releases the
registry lock. Existing diagnostics prove independent GPU locks, but the new guard has no direct
mutation demonstration covering the broader global-search and GPU wording. `S53` was reopened.

### prior-lifecycle-outcome | low | The lifecycle ambiguity is resolved

The interrupted-restart lifecycle test now requires exactly `503`, `index_unverifiable`, and no
results. It no longer accepts materially different readiness outcomes.

### prior-refusal-mutation-proof | medium | The refusal guard set remains partially proven

Some explicit-rebuild guards carry mutation notes, but the full audit set has no recorded
uninterrupted red and restored-green evidence. No closeout commit closes that complete finding.

### prior-watcher-side-effects | medium | Watcher refusal lacks unchanged-publication evidence

The surviving restart refusal test proves durable refusal and absence of a replacement job, but it
does not compare served payload or generation before and after refusal.

## Recommendations

1. Capture same-host resident-GPU comparison output and execute the resident-service scenario
   matrix on a compatible service.
1. Resolve the branch-wide required gates in their owning release, typing, and vault lanes, then
   rerun them from this branch.
1. Add end-to-end retrieval, ranking, route, combined, and public-result-shape comparison evidence.
1. Mutation-prove the readiness isolation and outstanding explicit-rebuild refusal guards.
1. Assert the watcher refusal preserves the previously served payload and generation.
