---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S59'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Reconcile the rollback-then-retry test with the checkpoint-resume contract so it asserts the retry converges rather than that a failed attempt leaves an empty store

## Scope

- `src/vaultspec_rag/tests/integration/test_codebase_integration.py`

## Description

- Replace the mid-attempt rollback assertion that expected an empty store with
  the resume-contract assertion: the failed attempt's own storage-confirmed
  points are retained, the file that never chunked has none
  (`src/vaultspec_rag/tests/integration/test_codebase_integration.py:709`).
- Keep the metadata-unchanged assertion, since a failed attempt never reaches
  finalization, and the retry-convergence assertions unchanged as the
  load-bearing check.
- Cite the mechanism at the assertion so the contract is legible to the next
  reader.

## Outcome

The test now guards the resume model instead of contradicting it. It was red
not because the code regressed but because it encoded a contract the code had
deliberately left behind.

The stale assertion was that after a failed incremental attempt the store holds
no points for the attempted paths - the pre-checkpoint rollback contract, where
a failure erased everything the attempt touched. The checkpoint-resume model
replaced that: a storage-confirmed point is durable evidence that survives the
attempt's failure so a retry resumes rather than re-encodes. In the scenario the
test builds, one file is fully processed and checkpointed before the
preprocessor aborts the run on a second file, so that first file's points are
retained by design. The assertion was authored before that model landed and was
never reconciled with it, so it was asserting the absence of exactly the durable
progress the model exists to keep.

The rewrite states the real contract. The retained points are asserted to be
exactly the processed file's own storage-confirmed set, computed by chunking it
the same way the indexer does; the aborted file, which never reached chunking,
is asserted to have none. The mechanism is cited in place: the rollback protects
the current attempt's own commits because their ledger units still describe
them, so deleting the store points would strand those units, while
carried-forward points from a prior generation are protected separately by the
pre-attempt id set. The never-retried case - durable points left in the store
by an attempt nobody resumes - is not a leak this assertion should catch,
because generation retirement and reconcile/invalidation are the mechanisms that
reclaim it, both built by this same plan.

What was deliberately kept matters as much as what changed. The metadata sidecar
is asserted unchanged after the failure, which is correct and stays: metadata
publishes only at finalization, which a failed attempt never reaches. And the
second half of the test - fix the failing file, retry, and assert every final
value converges - was already correct and is the load-bearing assertion. It
proves the retained points do not corrupt the eventual result: the retry
completes, both files end indexed at their true hashes, and the delete-and-
publish phases run. A test that only checked the mid-attempt store state would
have proven nothing about whether resume actually works.

## Notes

This test guards the resume model, so it was confirmed to fail when resume
genuinely breaks rather than only when the assertion is wrong. Removing the
rollback's protection of the current attempt's commits - so a failure deletes
the processed file's store points while its ledger units persist, the exact
store/ledger inconsistency the protection prevents - turns the rewritten test
red on the retained-points assertion. The probe was reverted and the protection
confirmed back in place.

No rollback code was changed, which was the explicit decision. The alternative -
making rollback delete the attempt's points too - was rejected because the
rollback removes only store points and not their ledger units, so it would leave
units pointing at deleted points and break resume. The contract that a failed
attempt retains its durable progress was confirmed, not assumed, before the test
was rewritten to it.

The root cause and pinning for this regression are recorded in the diagnosis
handed to the coordinator: the mechanism dates to the commit that introduced the
checkpoint-resume protection, and the assertion predates it. That the fix is a
test change rather than a code change is the whole finding - the code was right
and the test was stale, the same pattern seen elsewhere this cycle.
