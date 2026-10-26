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
  - '[[2026-07-16-mcp-stdio-lifetime-adr]]'
  - '[[2026-07-17-stdio-watchdog-convergence-adr]]'
  - '[[2026-07-28-stdio-orphan-rearm-adr]]'
  - '[[2026-10-05-qdrant-provisioning-trust-adr]]'
modified: '2026-10-26'
body_schema: body-v2
body_hash: 'sha256:9f498a9a6624d6206053677b427fa52a8b94c4cd90ca8b4da892e2ebd07691f0'
---

<!-- RETIRED: S07 -->

# `stale-search-hits` plan

Expose delivered-hit freshness and converge confirmed drift without automatic rebuilds.

## Description

Approved 2026-10-26

The user authorized implementation of stale-hit detection, bounded automatic audit and incremental reconciliation, and explicitly required full-rebuild needs to bubble to the operator. This plan persists that authorization for one cohesive revision and handoff. The user subsequently authorized the complete test matrix, live and integration execution, separate Luna Max supervision of local health checks and dead-code audits, and principal triage followed by bounded Sol 6.1 Medium remediation assignments.

`2026-10-26-stale-search-hits-adr` governs hit verification and the bounded managed-service exception. `2026-09-07-explicit-reindex-authority-adr` governs incremental refusal and explicit rebuild authority; `2026-09-08-search-readiness-contract-adr` governs service-owned readiness and adapters. `2026-10-12-destructive-rebuild-lifecycle-adr` is reused unchanged for reset-first explicit rebuild and useful partial search. `2026-09-08-incremental-publication-cost-adr` governs canonical proof, proportional publication and the scoped confirmed-hit audit exception. All govern S01. Evidence is inherited through these decisions. S02 extends verification under the same feature authority. S03 reuses the accepted MCP stdio lifetime, watchdog convergence and orphan re-arm decisions unchanged; it is a behavior-preserving health correction discovered by full validation, with no new costly decision. S04-S06 correct tests and canonical identity use within the existing accepted search/publication contracts; stored identities, schemas and public path shape remain unchanged. S08 reuses the accepted Qdrant provisioning trust decision unchanged for routine matching-minor pin maintenance, with outgoing digest reproduction before new digest derivation. S01 was reopened after the real-checkpoint vault defect and remains open until the consolidated S05 and final integrated verification resolve that finding. The originally separate S07 was retired into S05 because real-checkpoint tests and the production identity correction are one inseparable green commit; its identifier is not reused.

## Steps

- [ ] `S01` - Implement bounded final-hit freshness and supervised incremental reconciliation across search surfaces, preserving results and surfacing explicit rebuild remediation; `src/vaultspec_rag and docs/search-and-index.md`.
- [ ] `S02` - Run the complete local test matrix including live integration lanes and independent health audits; triage findings and preserve reproducible evidence; `src/vaultspec_rag/tests, dev, tools, local test artifacts and feature verification records`.
- [x] `S03` - Reduce the existing Windows stdio target discovery complexity without changing process-anchor ownership or lifetime behavior; verify Windows layered-anchor coverage; `src/vaultspec_rag/server/_stdio_lifetime.py and src/vaultspec_rag/tests/test_stdio_lifetime.py`.
- [ ] `S04` - Update exact search-result serialization contract coverage for the authorized freshness fields while preserving rank order and private-content exclusion; `src/vaultspec_rag/tests/integration/test_search_result_shape.py`.
- [ ] `S05` - Replace undeclared stale-hit substitutions with real components and correct canonical vault evidence identity, preserving live incremental repair and delivery ordering; `src/vaultspec_rag/_search_freshness.py, indexer/_vault_identity.py, _vault_incremental.py, _vault_prep.py, freshness/drift tests and focused live integration coverage`.
- [ ] `S06` - Make the malformed optional-null audit fixture persist the intended invalid payload through the real backend, retaining exact audit rejection and mutation proof; `src/vaultspec_rag/tests/test_vault_audit_validation.py`.
- [x] `S08` - Align reviewed Qdrant server pins with the existing locked 1.20 client using outgoing-digest reproduction and canonical asset derivation, without changing the user dependency update; `src/vaultspec_rag/qdrant_runtime/_constants.py, user-authorized staged uv.lock update and pin validation evidence`.

## Parallelization

S01 is one cohesive implementation and verification commit. The principal agent owns all source and test changes, integrated verification, review, ledger, Step closure and commit. The dispatched records worker owns only development records and `docs/search-and-index.md`; it may prepare those in parallel with source work. Writes are disjoint, shared vault metadata is serialized by the records worker, and the principal agent reviews the final stable contract before closure. The records worker does not log, close or commit the Step.

For S02, Luna Max agents supervise read-only check work: one owner serializes every stateful/live/GPU test lane, one owns full Ruff and structural health, one owns full ty and strict typing, and a separate dead-code audit runs when a slot opens. They write only logs and artifacts and return findings; they do not change source or commit. The principal owns triage, shared records, formal review and checkpointing. Confirmed fixes receive separately appended Steps with disjoint source ownership delegated to Sol 6.1 Medium agents; agents never revert others and shared metadata/commits remain serialized. Performance measurements run after the concurrent health checks finish. S03 is assigned to a Sol 6.1 Medium worker in the isolated `stale-validation-stdio` worktree, owning only `server/_stdio_lifetime.py` and necessary `tests/test_stdio_lifetime.py` coverage. It may prepare and verify its patch concurrently with S02 baseline testing, but the principal integrates it only after the relevant baseline is stable. The worker does not mutate the main checkout or shared records and does not commit; principal integration, review and commit remain serialized. S04 owns only the exact result-shape test; S05 owns real-component freshness/drift, focused live delivery coverage and canonical vault identity mapping with affected producer callers; S06 owns the optional-null audit fixture; S08 owns reviewed Qdrant pin constants and the user-authorized existing staged uv.lock update. These Sol 6.1 Medium assignments use disjoint permanent file ownership in the validation worktree. Temporary guard mutations are announced, serialized against shared-fork validation and exactly restored before handoff. Original source integration waits for the accelerated baseline to release its import hold. The user explicitly approved including the existing staged lockfile update with the matching server pin change; pre-existing generated reference edits remain outside scope. Supported source-checkout monitor generation/install is authorized as prerequisite test preparation, with generated artifacts kept separate from authored source changes.

## Verification

- Focused tests exercise code, vault, document and final combined pages; unchanged, edited and deleted files; source-specific fingerprints including non-indexed vault stamp changes; bounded deduplicated reads; safe paths; unreadable, missing, changing and incompatible evidence; indexed snippets and ranking preserved.
- Service tests demonstrate bounded coalescing, nonblocking search, existing incremental admission, audit/job rebuild refusal and executable source-scoped remediation. CLI and MCP preserve structured fields and render warnings/remediation consistently; local adapters do not enqueue service work and embedded raw Python result models may default to unverifiable. Verify the new identity-only bounded ledger read avoids materializing point lists.
- Negative and architectural guards are mutation-proven with the intended failure assertion and restored passing run recorded. No mutation survives handoff.
- Run applicable lint, format, type checks, covering tests, vault validation and plan validation explicitly, recording each exit code. Reuse covering evidence across integrated review; investigate concrete gaps without repeating unchanged checks.
- Complete the integrated review against these decisions before closing S01 and the plan. The principal agent owns execution logging and commit with explicit paths.
