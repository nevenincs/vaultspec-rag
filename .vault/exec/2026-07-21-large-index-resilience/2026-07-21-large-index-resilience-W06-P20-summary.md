---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:2b02c09d5438f93bed399a44eefe99177e9c4d070773aaffc49f2f13f315363b'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `large-index-resilience` `W06.P20` summary

## Description

Two residual defects the ledger-concurrency review surfaced but did not own.

The first was recorded as an order-dependent test failure and was not one. The two GPU tiers were sharing a card: the resident tiers hold their models for the length of a lane while each subprocess test spawns a service that loads its own, and the combined footprint exceeds the device. The symptom is not an out-of-memory error but a spawned service that never becomes healthy, so it surfaced as a health-poll timeout in an unrelated test, late in a long run, naming nothing about memory. The constraint had been written beside the marker and enforced nowhere, so the project's own runner selected both tiers in one expression. The runner now runs two sequential selections, and a gate refuses any selection holding both.

That gate judges the collected selection rather than the marker expression, after a first attempt proved the expression cannot answer the question in either direction. Most subprocess tests inherit a module default naming a resident tier, so probing one tier at a time reports the subprocess tier unreachable for exactly the selection that wedges; probing every combination that could exist reports a hazard for a tier holding no subprocess test, which would refuse a legitimate lane. Reading the items is exact, needs no model, and lets a path-scoped run be judged on what it collected instead of exempted.

The second was a type gate reporting five findings on every run that suppressed nothing, alongside two real errors this branch introduced. Both cleared.

Verification: the subprocess tier run alone on a quiet machine passed 67 of 67, with the previously failing test completing in 14.6 seconds against the 90-second timeout it hit when co-scheduled. Every guard was proven to fail on its named assertion and restored in the same sequence. Lint, format, and type are clean across the branch.

Left open deliberately: sixty-seven tests still declare a resident tier they inherit from a module default alongside their own subprocess mark, across sixteen modules. The gate makes that harmless rather than correct, and untangling it was not folded into this work.

- Modified: `justfile`
- Modified: `conftest.py`
- Modified: `src/vaultspec_rag/tests/_tier_gate.py`
- Modified: `src/vaultspec_rag/tests/test_marker_discipline.py`
- Modified: `src/vaultspec_rag/tests/test_adr_regression.py`
- Modified: `src/vaultspec_rag/tests/test_gpu_borrow_lease.py`
- Modified: `src/vaultspec_rag/indexer/_resolved_policy.py`
- Modified: `src/vaultspec_rag/commands/_models.py`

The declarations were untangled after the gate landed, closing the half left open above. Sixty-seven tests declared the subprocess tier and a resident one at once, almost none of them by hand: the second came from a module default, a class decorator, or a class-level default, and pytest adds those to a test's own decorator rather than letting the decorator override. Each module was repointed by shape, and declaring both is now a collection-time violation so it cannot drift back. The runtime selection gate stays, because a selection can hold both tiers without any test declaring both.

Verified by comparing every collected test's effective markers before and after, taken from the collector rather than re-derived: the same node ids, exactly 67 changed, all losing the resident tier and gaining nothing, none left declaring both or untiered.

- Modified: `src/vaultspec_rag/tests/integration/` (sixteen modules)
