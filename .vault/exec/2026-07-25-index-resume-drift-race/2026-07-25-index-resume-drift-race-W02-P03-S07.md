---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S07'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

# Give the indexed-path upsert collision its own exception type so a racing path is distinguishable from a genuine invariant breach

## Scope

- `src/vaultspec_rag/indexer/_run_ledger.py`

## Description

- Add a dedicated exception type for the indexed-path upsert collision,
  subclassing the general ledger state error so existing handlers are
  unaffected.
- Carry the generation id, the path, and both digests on the exception, and
  derive a drift predicate from the digest comparison.
- Raise the dedicated type at the collision site.
- Cover the type, the carried data, both digest cases, and the base-class
  catchability.
- Prove the guard test can fail, then restore.

## Outcome

The collision is now distinguishable at the type level. A caller can separate a
repairable condition - a file edited while the run that indexed it was still
going - from a genuinely broken generation invariant, which the undifferentiated
state error could not express. Scope was held to the signal: no remedy, retry,
or supersede logic was added, and those remain later Steps.

The type carries more than the path. Both the indexed digest and the incoming
unit digest are attached, and a drift predicate compares them. That distinction
turned out to matter more than anticipated: differing digests mean the file
changed and the path is repairable, while equal digests mean the caller
re-submitted content the generation already committed, which is a caller defect
rather than drift. A remedy that treated the two alike would silently re-publish
identical content on every duplicate submission.

Backward compatibility is preserved by construction rather than by convention,
since the new type subclasses the existing state error and every handler written
against the base class keeps intercepting it unchanged.

Gates: lint clean, citation gate clean, type check reports zero errors, warnings
and notes, complexity gates pass, and the ledger and checkpoint suites pass at 25
tests.

**Guard proof, both directions.** The raise site was mutated to emit the
undifferentiated base error and the guard test was run alone. It failed, and the
failure landed on the intended condition rather than on an import or collection
error: the base error escaped the context manager asserting the dedicated type,
reported as `RunLedgerStateError: cannot add upsert commit units after a path is indexed`. The file was then restored from an in-memory copy of the original,
verified byte-identical, and the test re-run green. The mutation was never
committed and did not outlive the sequence.

The test asserts the exact type rather than an instance check, deliberately. An
`isinstance` assertion would pass against the base class and would therefore not
notice the dedicated type being removed, which is precisely the regression the
test exists to catch. A comment at the assertion says so, so a later reader does
not relax it as over-specific.

## Notes

The executing agent completed the work but signalled idle without delivering its
report, so the searches it was required to run as dedup grounding, and its own
account of the guard proof, were not received. Rather than accept the change on
the strength of a readable diff, the gates, the test suite, and the bidirectional
guard proof were re-run independently and are what this record attests to. The
report was requested separately.

An assertion guards the non-null unit digest at the raise site. This matches the
surrounding convention in the same function, which already asserts a non-null
sibling row, and is a precondition rather than input validation.
