---
tags:
  - '#audit'
  - '#incremental-publication-cost'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:e95fe21314c1a6ce71503541273209e6acc751cecd4d7cfc0bb756ed42019a78'
related:
  - "[[2026-09-08-incremental-publication-cost-adr]]"
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# `incremental-publication-cost` audit: `S62 authority lifecycle`

## Scope

Reviewed the S62 test-only changes against the accepted explicit-reindex and
incremental-publication-cost decisions, the current plan, and the production authority
chain. The review covered the exact `RunAuthority` vocabulary, `JobSpec` serialization,
durable job and idempotency codecs, active-work identity, retry and restart behavior,
generic service admission, execution admission, CLI publication and audit routing, and
the prohibition on default, fallback, alias, inferred, migration, shim, and legacy
authority paths.

## Findings

No findings. **Verdict: APPROVED.** The closed enum is required at construction and
decoded without normalization; its exact value is retained in persisted job and
idempotency records, active-work identity, retry copies, restored snapshots, service
requests, attempt admission, and CLI transport selection. The tests distinguish
publication and rebuild authority through deduplication, retry, and restart, exercise
all three enum values through the exact codec, reject missing, empty, non-text, unknown,
and mismatched persisted authority, and reject audit-publication and
publication-rebuild admission before execution or transport.

The recorded mutation probes demonstrate failure when codec decoding collapses values,
active-work identity drops authority, retry changes authority, persistence supplies an
authority fallback, generic admission defaults or bypasses forbidden combinations, or
CLI mapping and audit-conflict validation are weakened. After restoration, the complete
three-file scoped suite passed with 175 tests; the scoped formatting, lint, and strict
type gates were also reported green. The final diff remains confined to the three test
files named by S62.

## Recommendations

No blocking recommendations. Retain the required closed enum and exact persisted copy
semantics as later publication-proof work extends the job result and telemetry surfaces.
