---
tags:
  - '#audit'
  - '#incremental-publication-cost'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:7ce08e39176f1bc742ea228f7424c659b6f5a974f36339cc806a734e6b276da2'
related:
  - "[[2026-09-08-incremental-publication-cost-adr]]"
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# `incremental-publication-cost` audit: `S38 execution admission review`

## Scope

Reviewed the complete S38 change against the accepted publication-cost and explicit
reindex-authority decisions. The audit covered generic route admission, durable manager
admission, dispatch binding, both concrete source runner branches, attempt-context
authority capture, all `_AttemptDispatch` constructors, and the focused guard tests.

## Findings

No findings. APPROVED.

Authority is required without a default, captured independently in the immutable job
specification, attempt context, and dispatch contract, and checked for exact agreement
before cancellation, preflight, leases, or indexing. Publication authority cannot select
full execution, audit-verification authority cannot enter a publication runner, and rebuild
authority paired with incremental mode still selects the incremental method. The complete
constructor census found no omitted `_AttemptDispatch` or `JobAttemptContext` call sites.

The guard proof is credible: making `_admit_attempt_mode` permissive caused the three
negative cases to fail with `DID NOT RAISE` and caused the concrete runner probe to reach
its cancellation checkpoint; restoring the guard made the focused matrix pass. The full
scoped route/dispatch file and manager admission suite also passed. The two unchanged
document integration regressions were refused before collection by the GPU-discipline
gate, but their S38-only edits add the required positional mode and authority constructor
arguments; strict type and static gates plus the executed CPU boundary coverage are
adequate for this step.

## Recommendations

No blocking recommendation. Run the two unchanged document integration regression nodes
when the GPU lease is available as an additional environment-dependent confirmation.
