---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:abca8fda5f00b5cc4f0ece4ac482a7a262a72b39b49cb7fc51eb05df5a7daafb'
step_id: 'S133'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Reconcile server-mode namespacing expectations with the document collection introduced by the boundary split

## Scope

- `src/vaultspec_rag/tests/test_store.py`

## Description

- Extend the server-mode namespacing expectation to the document collection's
  prefixed name and its per-root distinctness
  (`src/vaultspec_rag/tests/test_store.py:740`).
- Include the document collection in the point-lock key-set assertion and state
  the granularity contract the set is guarding.

## Outcome

The new lock is correct and the expectation was stale, but the expectation was
not merely widened - it now asserts the contract it had been silently
understating.

The store was read before the test was touched, because the governing rule makes
lock granularity contractual rather than incidental. The document collection
follows the established shape exactly: its name is a class-level constant
prefixed per root by the same derivation as the vault and code collections, and
its lock is its own reentrant lock in the same dictionary, keyed by the resolved
name. There is no new store-wide mutex, the point-lock accessor still returns a
no-op context in server mode so a remote server is not client-side serialized,
and the shutdown path still takes the lifecycle lock before acquiring every
collection lock in fixed order. The extra key was the correct consequence of a
third collection, not a regression.

The assertion was extended rather than relaxed. An exact key set is the only
form that catches the failure this rule cares about - a lock that is store-wide
rather than per-collection would show up here as a set that is too small, and
any form that merely checks membership would not. Two further assertions were
added while the expectation was open: that the document collection carries the
per-root prefix, and that it differs between roots. Without them the test
asserted per-root namespacing for two of the three collections and lock
granularity for all three, which is exactly the gap that let the document
collection arrive unnoticed.

## Notes

The namespacing class was run targeted by the author and passed. The full store
module was not run by the author.

The local-mode sibling test asserts the unprefixed constants and was left
untouched; it does not name the document collection, so it neither failed nor
needed to change for this Step. That it does not cover the document collection
at all is a smaller gap in the same module, noted rather than acted on because
it sits outside this Step's scope.
