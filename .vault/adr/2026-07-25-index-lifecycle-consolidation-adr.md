---
tags:
  - '#adr'
  - '#index-lifecycle-consolidation'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:4382a8186670ebc444a53fe28ad2432e3221efaff25c257ae09ecc519f6d8258'
related:
  - "[[2026-07-25-document-index-drift-parity-adr]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
  - "[[2026-07-21-managed-log-contract-adr]]"
  - '[[2026-07-25-index-lifecycle-consolidation-research]]'
---

# `index-lifecycle-consolidation` adr: `one shared run lifecycle for every index entry point` | (**status:** `accepted`)

## Problem Statement

Accepting an index run, stamping the persisted activity clock around it, and
emitting the started / failed / completed event triple is one decision that
existed as four hand-copied implementations, with a fifth copy of the
surrounding shape - the document path - that had neither the stamp nor the
events. The gap has to be closed, and the decision has to settle whether it is
closed by adding the missing calls or by removing the ability to have them
missing.

The question is live now rather than later because the document path is the
copy that proves the copies do not converge. The stamp was added to four sites
in one change; the fifth was not in that change's field of view and has been
silent ever since, and nothing in the suite noticed.

## Considerations

- The destructive exposure is real but confined to temp-rooted namespaces in
  server mode, and cannot reach a conventional project root
  (`2026-07-25-index-lifecycle-consolidation-research`).
- The observability loss is unconditional and applies to every root in both
  backends, which makes it the cheaper half to price and the harder half to
  defend leaving open.
- All three collections of one root share a single activity clock, so mixed
  workloads mask the defect and only a document-only workload exposes it.
- A prior record declined to generalise the resume drift mechanism across the
  two indexes because the shared abstraction would have been drawn from one
  real caller and one hypothetical one
  (`2026-07-25-document-index-drift-parity-adr`). That same record states the
  converse test this decision meets: parity is a reason to align behaviour
  where behaviour differs without justification.
- The lifecycle has five real callers across six entry points today, so an
  abstraction drawn from them is shaped by what exists rather than by what
  might.
- The document index owns its own routing and checkpoint machinery
  (`2026-07-21-code-document-index-boundary-adr`); a shared lifecycle must not
  reach past the run boundary into that ownership.

## Considered options

- **Patch the three missing calls into the document indexer.** Rejected: it
  closes the symptom while leaving four copies of the decision, and therefore
  leaves the next divergence available on exactly the terms that produced this
  one.
- **Give the document indexer its own lifecycle helper.** Rejected: two helpers
  is the same failure at a smaller scale, and the divergence would be harder to
  see because both sides would look deliberate.
- **Extract one lifecycle wrapper, parameterised on the run body, and route
  every entry point through it.** Chosen.
- **Fold the lifecycle into a shared indexer base class.** Rejected: the three
  indexers differ in lock structure, preflight shape, and checkpoint ownership,
  so a base class would have to absorb those differences to host one shared
  concern, and the boundary record exists to keep them apart.

## Constraints

- The wrapper takes no lock and owns no lock ordering. The code and vault paths
  call it under their writer lock; the document path takes its writer lock
  inside the run body, because the checkpoint it opens and the pending
  finalization it may resume have to be reachable before any exclusive span.
  Moving the document lock outward is a separate decision with its own risk and
  is explicitly not taken here.
- Event field names, ordering, and the emitting logger's record name are a
  consumed contract (`2026-07-21-managed-log-contract-adr`) and must survive
  the extraction unchanged for the two kinds that already emit.
- An incremental run that discovers incompatible metadata delegates to the full
  path. Exactly one lifecycle must wrap that run, reported under the mode it
  actually ran, or one run produces two event pairs.
- The stamp is best-effort by construction and must remain unable to fail a
  run.

## Implementation

A single module owns the lifecycle. It takes the store whose clock is stamped,
the calling module's logger, the run's source and mode, the workspace root,
the attempt control, the run body, and an optional derivation of the
per-kind completion counters. It emits the started event, stamps the clock,
calls the body exactly once, stamps again, and emits completion; on any
exception it emits the failure event and re-raises without translation. The
mode label for an incremental run is derived in the same module, so the scoped
and unscoped spellings cannot drift per kind.

All six public entry points across the three indexers delegate to it. The code
and vault paths keep their existing structure and simply hand their already
extracted locked implementation to the wrapper as the body. The document paths
gain the equivalent extraction they never had: each public entry point resolves
its preflight and its run inputs, then delegates the reconciliation itself as
the body, which brings the document indexer to the same shape as the other two
and gives it the stamp and the events by construction rather than by addition.

The stamp call and the event namespace are left with exactly one call site each
in the package, and a test asserts that, so a new copy cannot be grown beside
the shared one.

## Rationale

The knockout is that the alternative fixes the instance and not the class. The
missing stamp is not a missing line; it is the observable consequence of a
duplicated decision, and adding the line restores agreement between five copies
that still have no mechanism to stay in agreement. Extraction removes the
ability for the next entry point to be written wrong, which is the only
remedy proportionate to a defect whose cause is that nothing was comparing.

The objection that deferred the earlier shared component does not apply here
and its own criterion says so. That component would have been extracted to
serve one real caller and one hypothetical one, so the hypothetical would have
shaped the interface. This one is extracted from five real callers that already
agree on its shape, and the extraction is a consolidation of code that exists
rather than a design for code that might.

Choosing extraction over the interim patch is also what the severity picture
supports rather than contradicts. The destructive exposure is narrow enough
that speed is not the deciding force, and the observability loss is broad
enough that the fix should be structural rather than minimal.

## Consequences

The lifecycle now has one home, the document path gains an activity stamp and
operator-visible events it never had, and a new indexer or a new entry point
inherits both without anyone remembering to add them.

Honestly framed, the three indexers still differ underneath the wrapper. The
document path takes its writer lock inside the body while the other two hold it
across the wrapper, so the phrase "the same lifecycle" describes the
observability and clock contract, not the concurrency structure. A reader
comparing the lock scopes will find that asymmetry, and it is deliberate: the
run boundary was made uniform, the lock boundary was not touched.

The wrapper is also now on the failure path of every index run. It swallows
nothing and translates nothing, but a defect inside it would be a defect in all
three kinds at once - which is the cost that always accompanies removing
duplication, and the reason its own behaviour is tested directly rather than
only through its callers.
