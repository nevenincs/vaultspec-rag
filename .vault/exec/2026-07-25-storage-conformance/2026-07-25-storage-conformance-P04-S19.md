---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S19'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Keep an unverifiable namespace out of automated reclamation candidacy

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

Verify the exclusion against the reclamation evaluator, state the invariant where
a later reader would otherwise wire the verdict in, and lock both directions with
a guard.

## Outcome

**The behaviour this Step asks for already holds, and no code change was needed
to make it hold.** The reclamation evaluator considers `orphaned` survey entries
only; `unknown`, `unverifiable`, and `live` never reach its output, and a test
predating this feature already asserts exactly that. The manual prune filters the
same way, and the ephemeral idle tier admits only `live`. Evidence is the filter
itself plus that existing assertion, not a claim about intent.

**The plan's own verification criterion is stronger than this, and implementing
it literally would be a defect.** That criterion reads a namespace with no
stamped identity as never a reclamation candidate. Every namespace on every host
is unverifiable on first upgrade, and an orphan's root is already gone - it can
never be rebuilt into a stamp - so honouring it literally would exempt the entire
pre-upgrade population from reclamation permanently and turn a safety rule into an
unbounded disk leak. The authorizing decision says only that an unverifiable
verdict never *authorises* destruction, which is the weaker and correct claim: it
is not grounds to destroy, not a veto over grounds that already exist.

Two classifications share the word `unverifiable` and mean different things - a
root that could not be confirmed absent, and a collection whose producer was
never recorded. The evaluator's docstring now states that only the first is an
input, and why letting the second either authorise or block would break
something. A guard asserts both directions: an aged orphan with no stamped model
is still reclaimable, and a fully-stamped namespace whose root could not be
confirmed absent is still not.

The protection the criterion was reaching for is real and is delivered elsewhere
in this Phase: a data-bearing namespace is archived before it is dropped, and that
archive now carries its identity, so what gets reclaimed stays judgeable after the
fact.

## Notes

Deliberately not implemented as written. The divergence from the plan's
verification criterion is stated above with its reasoning rather than silently
resolved either way, and is carried into the closing review.
