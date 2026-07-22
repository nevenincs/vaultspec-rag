---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S55'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Cover the cascade end to end: fail an incremental attempt, edit a file it had already indexed, and assert the next attempt succeeds

## Scope

- `src/vaultspec_rag/tests/integration/test_index_job_control.py`

## Description

- Add an end-to-end recovery test that fails an incremental attempt after a
  path is indexed, edits that indexed path, and asserts the next attempt
  succeeds - parametrized over both incremental entry points
  (`src/vaultspec_rag/tests/integration/test_codebase_integration.py:742`).
- Assert the re-opened path's stored identities exactly equal a fresh chunking
  of its new content, so replacement is distinguished from duplication.
- Add a ledger test asserting the supersede removes only the superseded
  digest's upsert units, leaves a deletion unit and a sibling path untouched,
  restores the refused write, and replays to zero
  (`src/vaultspec_rag/tests/test_index_run_ledger.py:598`).
- Add a ledger test asserting re-opening is refused once finalization begins
  (`src/vaultspec_rag/tests/test_index_run_ledger.py:700`).

## Outcome

The cascade now has a test that fails when the fix is absent, which is the only
property that matters here. Nothing previously exercised the repair at all: a
search of the whole test tree for the four new symbols returned nothing, so the
hundred and fifty passing tests around it established that the existing contract
was intact and said nothing about whether the repair worked.

The integration test reproduces the incident rather than the invariant. An
attempt indexes one file and then aborts on a second, the already-indexed file
is edited, and the attempt runs again. That edit is the entire point and is what
separates this from the rollback test beside it, which edits the file that
caused the failure and therefore never drifts the digest of anything already
indexed. A test asserting only that the ledger refuses a mismatched unit would
have passed every day of the outage.

Both parametrizations pass, and the run log shows the repair firing once in
each, so neither passes vacuously. The mutation was then confirmed directly
rather than argued: with the re-open neutered to a no-op, the second attempt
fails with the exact incident error, and the ledger test's count assertion drops
to zero. The probe was reverted immediately and its absence verified.

Two properties beyond success are asserted because they are the ones that would
regress silently. The first is that the re-opened path's stored identities
exactly equal a fresh chunking of its new content, by set and by count. Chunk
identity embeds the line span and a content hash, so a future change that
cleared the ledger evidence without dropping the published points would leave
both generations of points present and every other assertion would still pass;
this is the one that would catch it. The second is that the supersede is
surgical - only the superseded digest's upsert units are removed, while a
deletion unit for the same path and a sibling path's evidence survive
untouched.

One assertion was reframed rather than written as requested. The crash-safety
invariant was described as deletion units surviving while superseded upserts do
not, and that is true of the shipped code and is asserted. But the re-open does
not itself record a deletion unit, because a point identity may belong to only
one commit unit and the superseded upsert still claims those points at that
moment. The test therefore seeds a deletion unit and asserts it survives, which
is the real invariant; asserting that the re-open creates one would have
asserted a design that cannot exist.

No mock, stub, patch, or fake appears in either test. The failure is induced by
a real preprocessor that exits non-zero on a sentinel string, against a real
ledger, a real store, and real chunking.

## Notes

The mutation check is the evidence this record rests on, so its method is stated
plainly. The re-open was temporarily replaced with a no-op in the working tree,
the two tests were run and observed to fail - the integration test with the
original incident message, the ledger test on its unit count - and the edit was
reverted and its removal verified before anything else ran. This was a
throwaway probe in a shared tree over a window of about a minute, which is a
risk worth naming even though it was contained.

Four unrelated integration failures already present in the same module were not
addressed and are not caused by this work. The new test passes alongside them.

The ledger tests carry the load for the surgical assertions because a successful
run publishes and compacts its generation, so the unit rows are gone by the time
an integration test could inspect them. Splitting the coverage that way keeps
each assertion where it can actually observe what it claims.

Coverage is code-only, matching the fix. The document domain shares the resume
model and is very likely reachable by the same cascade; neither the repair nor
this coverage extends there, and that remains an open follow-up rather than an
oversight.
