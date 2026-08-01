---
tags:
  - '#exec'
  - '#index-completeness-guard'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:012c656c6651d7e5354b2bdfda2bcec1126cfa2c1e9795d464338b40089b76a4'
step_id: 'S03'
related:
  - "[[2026-07-25-index-completeness-guard-plan]]"
---

# Prove the shortfall guard can fail by permitting a truncated collection to pass, observing the intended failure, restoring, and observing the pass

## Scope

- `src/vaultspec_rag/tests/test_indexer_unit.py`

## Description

- Add five tests pinning one branch of the predicate each, driving a real
  `VaultStore` with real upserted points and no stubbed count.
- Prove each can fail: mutate the single branch it pins, run that test alone,
  observe the named assertion fail, restore, observe it pass.
- Record both directions of every proof in the test class docstring, where the
  next reader will find them.

## Outcome

All five proven able to fail, each on the assertion it names rather than on an
import or collection error. Mutation applied, test run alone, restored, re-run:

| Test                                                 | Mutation                                                              | Failure observed                                       |
| ---------------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------ |
| short collection rejected though it exists           | relax comparison to `live >= 0`, the pre-fix existence-only behaviour | `assert False is True` on `_published_evidence_lost()` |
| sidecar without a published count is not a shortfall | return `True` for an absent count, reading "cannot tell" as loss      | `assert True is False`                                 |
| absent collection is still rejected                  | return `False` when the collection does not exist                     | `assert False is True`                                 |
| intact collection is trusted                         | tighten comparison to `live > claimed` so equality reads as a deficit | `assert True is False`                                 |
| empty sidecar is never a shortfall                   | return `True` for absent carried file evidence                        | `assert True is False`                                 |

Each mutation was applied and restored inside one guarded sequence, so none was
left on disk across a pause. Restoration was verified by byte comparison against
the original text, then again by grep after the fact.

Each test asserts the branch, not a log message: the shortfall and
absent-collection branches share a return value, so a message matcher would pass
on whichever fired.

The full file passes: 115 tests in `test_indexer_unit.py`, plus 46 across
`test_run_checkpoint.py`, `test_index_run_ledger.py`, and
`test_chunk_worker_parity.py`.

## Notes

The parity test's class docstring carried a proof claim that had not been run -
that giving the pooled chunk branch a different root than the serial branch
fails the test on the id comparison. Rather than commit an unverified claim, the
proof was executed: passing the project root's parent to the pool submission
fails `test_parallel_matches_serial` on
`assert [c.id for c in parallel] == [c.id for c in serial]`, and restoring the
root returns it to green. The claim is accurate as written.
