---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:adde09e5a7e9736868ac71d66e10d0d97bc59ea1e8feba34ab7c3a7ad1eed5b0'
step_id: 'S13'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

# Prove the upsert guard bidirectionally: permit the forbidden write, watch the test fail on its own assertion, restore, watch it pass, and record both directions

## Scope

- `src/vaultspec_rag/tests/`

## Description

- Break each guard in turn, run its test alone, watch it fail on the assertion
  it names, restore, watch it pass.
- Sharpen the non-drift rejection test after its first proof failed on the
  wrong assertion.
- Record both directions here, and comment each mutation at the assertion that
  catches it.

## Outcome

Four proofs, each one uninterrupted, each mutation restored before the next.

The reported failure. Reducing the recording helper to the bare ledger call -
the behaviour before this work - failed the reproduction test with
`RunLedgerIndexedPathCollisionError: cannot add upsert commit units after a path is indexed: 'src/moving.py'`, which is the reported error verbatim.
Restored, the test passes.

The non-drift rejection. Removing the re-raise for equal digests failed the
test with `DID NOT RAISE RunLedgerIndexedPathCollisionError`. This one needed a
second attempt to be worth anything. The first version placed the replayed
unit at segment ordinal one, so the mutated code repaired the path and then
died on contiguous-ordinal validation: the test failed, but on an unrelated
ledger complaint rather than on the guard it exists to protect. Moving the
replay to ordinal zero makes a wrongly-permitted repair succeed, so the only
way the test can fail is the absence of the rejection. A comment at the
segment says so.

The retry bound. Making the budget predicate always report unspent failed the
deferral test on `deferred_paths == frozenset({'src/moving.py'})`, the exact
assertion the bound exists to satisfy.

The protected identities. Dropping the exclusion of the incoming mutation's
own point identities failed the preservation test on the remaining stored
identities, which came back empty against the expected single identity - the
remedy having deleted the content it was making room for.

After the last restore, the drift, checkpoint and ledger suites pass together
at 36 tests, which is the evidence no mutation outlived its proof.

## Notes

Every assertion proved here names a specific condition rather than a message.
The collision guard shares one message across its branches, so a message match
would pass whichever branch fired and would have proved nothing.

The remaining verification this Phase scopes - a live service against a
genuinely moving tree - was not run and is not attested here. It needs the GPU
and a running service, both of which are shared with other work.
