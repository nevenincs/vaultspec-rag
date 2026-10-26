---
tags:
  - '#plan'
  - '#stale-search-hits'
date: '2026-10-26'
tier: L1
related:
  - '[[2026-10-26-stale-search-hits-adr]]'
  - '[[2026-09-07-explicit-reindex-authority-adr]]'
  - '[[2026-09-08-search-readiness-contract-adr]]'
  - '[[2026-10-12-destructive-rebuild-lifecycle-adr]]'
  - '[[2026-09-08-incremental-publication-cost-adr]]'
modified: '2026-10-26'
body_schema: body-v2
body_hash: 'sha256:79024f91a504f04219de8001804dc564c52ac3b725b47032fa63c69b23c03858'
---

# `stale-search-hits` plan

Expose delivered-hit freshness and converge confirmed drift without automatic rebuilds.

## Description

Approved 2026-10-26

The user authorized implementation of stale-hit detection, bounded automatic audit and incremental reconciliation, and explicitly required full-rebuild needs to bubble to the operator. This plan persists that authorization for one cohesive revision and handoff.

`2026-10-26-stale-search-hits-adr` governs hit verification and the bounded managed-service exception. `2026-09-07-explicit-reindex-authority-adr` governs incremental refusal and explicit rebuild authority; `2026-09-08-search-readiness-contract-adr` governs service-owned readiness and adapters. `2026-10-12-destructive-rebuild-lifecycle-adr` is reused unchanged for reset-first explicit rebuild and useful partial search. `2026-09-08-incremental-publication-cost-adr` governs canonical proof, proportional publication and the scoped confirmed-hit audit exception. All govern S01. Evidence is inherited through these decisions.

## Steps

- [x] `S01` - Implement bounded final-hit freshness and supervised incremental reconciliation across search surfaces, preserving results and surfacing explicit rebuild remediation; `src/vaultspec_rag and docs/search-and-index.md`.

## Parallelization

S01 is one cohesive implementation and verification commit. The principal agent owns all source and test changes, integrated verification, review, ledger, Step closure and commit. The dispatched records worker owns only development records and `docs/search-and-index.md`; it may prepare those in parallel with source work. Writes are disjoint, shared vault metadata is serialized by the records worker, and the principal agent reviews the final stable contract before closure. The records worker does not log, close or commit the Step.

## Verification

- Focused tests exercise code, vault, document and final combined pages; unchanged, edited and deleted files; source-specific fingerprints including non-indexed vault stamp changes; bounded deduplicated reads; safe paths; unreadable, missing, changing and incompatible evidence; indexed snippets and ranking preserved.
- Service tests demonstrate bounded coalescing, nonblocking search, existing incremental admission, audit/job rebuild refusal and executable source-scoped remediation. CLI and MCP preserve structured fields and render warnings/remediation consistently; local adapters do not enqueue service work and embedded raw Python result models may default to unverifiable. Verify the new identity-only bounded ledger read avoids materializing point lists.
- Negative and architectural guards are mutation-proven with the intended failure assertion and restored passing run recorded. No mutation survives handoff.
- Run applicable lint, format, type checks, covering tests, vault validation and plan validation explicitly, recording each exit code. Reuse covering evidence across integrated review; investigate concrete gaps without repeating unchanged checks.
- Complete the integrated review against these decisions before closing S01 and the plan. The principal agent owns execution logging and commit with explicit paths.
