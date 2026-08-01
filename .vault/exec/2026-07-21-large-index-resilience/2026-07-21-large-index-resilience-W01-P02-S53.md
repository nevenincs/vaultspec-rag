---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:ec098a8e02b3f8632b85709f9b8d4b5c7aff4bfa4dfdff39767b6f46a908669e'
step_id: 'S53'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Decide and enforce whether a repeatedly failing generation retires instead of remaining resumable indefinitely

## Scope

- `src/vaultspec_rag/indexer/_run_ledger.py`

## Description

- Add a consecutive-failure counter to the generation record, advanced only by
  unsuccessful outcomes (`src/vaultspec_rag/indexer/_run_ledger.py:1427`).
- Retire a generation that reaches the bound by invalidating it, so the next
  attempt starts clean (`src/vaultspec_rag/indexer/_run_ledger.py:349`).
- Declare the bound as a named constant with its reasoning
  (`src/vaultspec_rag/indexer/_run_ledger.py:165`).
- Create the counter column on ledgers that predate it, without a
  schema-version bump (`src/vaultspec_rag/indexer/_run_ledger.py:1596`).
- Add guards that the bound retires at three and that success never advances it
  (`src/vaultspec_rag/tests/test_index_run_ledger.py:790`).

## Outcome

Resumption is now bounded, so a deterministic fault can no longer hold an index
down indefinitely.

The rule is explicit rather than emergent. Three consecutive failed attempts
against one signature retire the generation. Three rides out the transient
causes that genuinely deserve a retry - a momentary allocator failure, a disk
blip, a file caught mid-write - while bounding a deterministic fault to minutes
rather than hours. Measured against the outage that prompted this, the first
failure would still have been retried twice and the fourth attempt would have
started clean, turning an hour of continuous failure into roughly ten minutes.

Only unsuccessful outcomes advance the counter. A success retires the generation
by its own path, so the count never needs clearing, and a partially-progressing
attempt is deliberately not treated as a reset - an attempt that commits a
little and then fails the same way each time is exactly the case the bound
exists to stop.

Retirement invalidates rather than deletes. That keeps the evidence readable
until a later success compacts it, and it reuses the one mechanism already
proven to work here: invalidated is outside the resumable set, so the next
attempt creates a fresh generation without any new selection logic. The
alternative - deleting the row - would have destroyed the record of why an index
rebuilt itself at the moment an operator most wants to know.

What this replaces is worth stating plainly, because it was never designed. The
only recovery available before this was a full reindex, and that works by
accident: the operation is part of the generation signature, so a full run
computes a different fingerprint and invalidates whatever was poisoned as a side
effect of not matching it. Nothing in the system was choosing to retire
anything. A configuration edit escapes the same way, for the same incidental
reason. An operator who re-saved the file instead - the obvious thing to try -
reproduced the failure, because that is precisely the input that resumes the
poisoned generation.

The counter reaches existing ledgers. The schema is built only at creation, so a
declaration alone would never have reached a ledger already in service,
including any currently wedged. Bumping the schema version would reach them only
by rejecting them, since the compatibility check admits one exact version and
every current ledger would be declared unsupported and rebuilt from zero. The
column is therefore added on open when absent, with a default that reads every
existing generation as having failed zero times, which is the correct starting
point for a record that has never been counted.

## Notes

Both guards were confirmed to fail against the unfixed behaviour rather than
assumed to cover it. Raising the bound out of reach makes the retirement test
fail on the assertion that the replacement differs from the original, which is
the whole property. The probe was reverted and the constant re-read to confirm
it was back at three.

The bound counts attempts, not causes. A generation failing for three different
transient reasons retires exactly as one failing three times for the same
reason. That is deliberate - the ledger cannot tell them apart, and a caller
that could would be guessing - but it does mean an unlucky run of unrelated
transients can retire a generation that would have succeeded on the fourth try.
The cost of that is one fresh generation, which is the cheap direction to be
wrong in.

Retirement does not reach a generation that is currently running. It is
evaluated when the next attempt starts, so a wedged in-flight attempt is
unaffected until it terminates. That is the correct boundary for this Step -
interrupting live work is a control concern, not a ledger one - but it means the
bound bites on the attempt after the third failure rather than during it.

No schema version was changed, so no ledger is invalidated and no rebuild is
triggered.
