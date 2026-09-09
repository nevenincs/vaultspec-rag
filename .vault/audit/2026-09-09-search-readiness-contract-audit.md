---
tags:
  - '#audit'
  - '#search-readiness-contract'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:d91141da1be78de5949940d28989ff6c7b9fd01e9e137a29d0847d0d12c6f099'
related: []
---

# `search-readiness-contract` audit: `post-merge integration alignment`

## Scope

The accepted readiness decision, implementation plan, feature branch relative to `main`, merge
commit, and the complete post-merge working-tree test diff were reviewed for service-owned
classification, explicit rebuild authority, lossless adapter envelopes, removal of displaced
helpers, race resistance, and guard-test validity. The review was read-only outside this audit
body. The removed MCP diagnostics helper, obsolete code-payload polling helper, renamed empty-code
collection helper, and displaced MCP exception helper have no remaining callers.

## Findings

### lifecycle-search-outcome | low | A lifecycle test accepts two materially different readiness outcomes

`test_service_lifecycle_runtime.py` now accepts either HTTP 200 or 503 after the interrupted clean
rebuild and restart. The 503 branch checks `index_unverifiable`, but the 200 branch does not assert
the canonical success envelope or authoritative state. This removes flakiness from a lifecycle
test at the cost of allowing a readiness regression to pass nondeterministically. The test should
either wait for one justified terminal readiness fact or isolate its store-reopen assertion from
search classification.

### refusal-mutation-proof | medium | New explicit-rebuild refusal guards lack recorded red and restored-green proof

The post-merge alignment adds or materially rewrites exact negative guards for embed-schema drift,
failed document publication, vanished collections, ignore-membership drift, old vault point
layout, and watcher scope loss. Most assert `FULL_REINDEX_REQUIRED`, but unlike the repository's
established guards they do not record the production mutation, named failing assertion, and
restored green result beside the test. A passing negative test alone does not prove the forbidden
incremental or destructive branch reached the assertion. These guards therefore cannot yet count
as mutation-proven evidence for the explicit-reindex boundary.

### watcher-refusal-side-effects | medium | Watcher scope-loss tests do not prove refusal is mutation-free

Four watcher tests were correctly changed from automatic convergence to durable typed refusal and
assert the persisted circuit remains open with convergence pending. They no longer inspect the
served payload or job publication after the triggering edit. A watcher that wrongly indexed the
changed content and then persisted `full_reindex_required` would satisfy every new assertion. The
tests need a negative storage/publication assertion that the pre-refusal served generation remains
unchanged, followed by mutation proof of that assertion.

## Recommendations

1. Replace the lifecycle test's `{200, 503}` allowance with a bounded wait for the contractually
   justified outcome, or test store reopening without using search as an ambiguous proxy.
2. Mutation-prove every newly introduced or rewritten refusal guard in one uninterrupted
   break/red/restore/green sequence and record the exact mutation and assertion at the test.
3. Extend each watcher scope-loss refusal test with a direct assertion that no changed payload or
   replacement generation was published before explicit full-reindex authority was supplied.
