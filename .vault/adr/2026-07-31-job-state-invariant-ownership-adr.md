---
tags:
  - '#adr'
  - '#job-state-invariant-ownership'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:4fc87872ae1bd02d09f13f360ccc544f43670b5b20cfb468f8fb4662a3da062c'
related:
  - "[[2026-07-31-job-state-durability-adr]]"
  - "[[2026-07-31-job-state-durability-reference]]"
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-large-index-resilience-adr]]"
  - "[[2026-06-11-service-jobs-operability-adr]]"
  - "[[2026-07-24-service-quiesce-adr]]"
---

# `job-state-invariant-ownership` adr: `generation-level invariants: one implementation at the persisted-generation boundary` | (**status:** `proposed`)

## Problem Statement

The job-state durability decision (`2026-07-31-job-state-durability-adr`) closed the
per-record half of one asymmetry: every persisted model now validates at construction, so
a value the loader would refuse fails in the producing traceback instead of on the next
start. Its residual-gaps clause names what it left open: **generation-level invariants
remain loader-only**. Idempotency-key length and uniqueness, job-id uniqueness, and the
relational rules of `_validate_persisted_generation` and `_validate_persisted_job` -
cross-field timestamp ordering, observed-versus-desired agreement, idle-state resource
holds, active-work uniqueness, binding-to-job reference and spec equivalence - are
enforced only on read (`src/vaultspec_rag/job_persistence.py:326`), never on write.

Verifying the claim against the code sharpens it. The current manager does not, in fact,
write a too-long or duplicate key: key length is refused at admission with a structured
outcome (`src/vaultspec_rag/job_manager/_records.py:411`), and key and job-id uniqueness
are structural, because the manager's registries are maps keyed on exactly those values
and serialization reads from them (`src/vaultspec_rag/job_manager/_persistence.py:506`).
The genuine gap is one level up: the writer-side guarantee rests on manager internals -
a data-structure choice here, an admission check there, transition discipline under one
lock for the lifecycle and timestamp rules - while the persisted contract itself,
`PersistedManagerState` (`src/vaultspec_rag/job_persistence.py:119`), validates nothing
at construction. `save_persisted_state` will durably publish any generation a caller
assembles. Nothing ties the scattered producer-side enforcement to the loader's rules,
so the two ends can drift apart silently - which is the exact defect shape the parent
record exists to close, and the loader has already been the wrong end once (the
paused/running pair its D1 corrected).

The tension to resolve: several of these are properties of a collection, not of any
record, so they cannot live on a frozen per-record dataclass at all. One prior position
put standing enforcement at the manager's mutation points under the lock; another argued
for `PersistedManagerState.__post_init__` so one implementation serves both ends - at
the cost of changing loader error ordering, and against the campaign's precedent of
loosening the reader rather than tightening the writer. This record is grounded in the
implementation catalogued by `2026-07-31-job-state-durability-reference`; the decision
is not yet implemented.

## Considerations

- The parent record's rationale is placement, not duplication: the same rule enforced at
  both ends must not be two spellings, which is why it shares requirement strings
  (`src/vaultspec_rag/job_persistence.py:96`) and why progress publication constructs
  the canonical record instead of mirroring its rules.
- The codebase rule on canonical code forbids mirroring logic that lives elsewhere; a
  second copy of the generation validator at the manager's mutation points would be
  exactly the drifting duplicate that rule names.
- Both ends already construct the same type: the parser builds `PersistedManagerState`
  as its last act (`src/vaultspec_rag/job_persistence.py:365`), and the persistence
  funnel builds one per write (`src/vaultspec_rag/job_manager/_persistence.py:506`,
  `src/vaultspec_rag/job_manager/_persistence.py:524`). A constructor-owned validator is
  therefore traversed by writer and reader alike without either importing the other.
- The loader already carries dead re-checks of rules the models now own: the attempt
  lineage branches (`src/vaultspec_rag/job_persistence.py:542`) restate
  `JobAttempt.__post_init__` (`src/vaultspec_rag/job_models.py:373`), and the progress
  bound (`src/vaultspec_rag/job_persistence.py:467`) restates
  `JobProgress.__post_init__` (`src/vaultspec_rag/job_models.py:436`); both are
  unreachable on the load path because the models are constructed first.
- Every persist failure already has a survivable shape: the funnel reports the error,
  the mutation rolls back to its captured backup, and the verb returns a structured
  failure (`src/vaultspec_rag/job_manager/_records.py:270`). A refusal to persist an
  invalid generation lands in that path, not in a new one.
- The wrongly-strict-rule hazard is real and precedented: the loader once refused the
  paused-observed/running-desired pair that quiesce parking deliberately writes
  (`2026-07-24-service-quiesce-adr`). Where such a defect surfaces is a failure-geometry
  choice: loader-only means the next start, another process, history quarantined;
  boundary-owned means the producing transition fails loudly and rolls back.
- Construction-time validation of a whole snapshot is the pre-existing standard this
  generalizes: the resilience snapshot validates its own fields at construction
  (`src/vaultspec_rag/job_models.py:548`, per `2026-07-21-large-index-resilience-adr`),
  and admission and idempotency semantics are owned by
  `2026-07-21-service-job-control-adr`, which this record does not alter.
- Per-record persisted rules do not belong on `JobSnapshot.__post_init__`: the snapshot
  is also the live served view (`2026-06-11-service-jobs-operability-adr`), and
  "constructible in memory" and "persistable as durable history" are distinct
  predicates - the quiesce correction proves lifecycle coherence is subtle enough that
  multiplying the surfaces that assert it multiplies the ways one can be wrong.
- Serialization is already O(generation) per persist; a validator walking the same
  records adds comparisons, not a new asymptotic cost.

## Considered options

- **Standing enforcement at the manager's mutation points under the lock.** Rejected as
  the contract's home. It is a second implementation of rules the loader also states,
  scattered across verbs, and it protects only this manager: any other producer of
  `PersistedManagerState` - a test, a future repair verb, a second writer - bypasses it
  entirely. Admission-time pre-screens stay, as verb preconditions with friendly
  structured outcomes, but they are not the contract.
- **Loader-only, status quo.** Rejected. It is the asymmetry the parent record's D1
  closed per-record, left open one level up: a producer defect surfaces in another
  process after the write is long gone, and costs the whole history via quarantine.
- **One implementation in `PersistedManagerState.__post_init__`.** Chosen. Both ends
  construct the type, so one validator serves writer and reader without a mirror; the
  canonical-code rule is satisfied by construction rather than by discipline.
- **Defence in depth with two synchronized copies.** Rejected. Two copies of a
  relational validator drift; the campaign's own mechanism for "one rule, two ends" is
  a single spelling both ends traverse, and that mechanism is available here.

## Constraints

- The read path's acceptance set is unchanged: the same generations load, the same
  generations are refused. Only the internal placement of the refusal - and therefore
  which defect a multi-defect file names first - moves. The campaign's
  loosen-the-reader precedent is not touched, because nothing the reader accepts or
  refuses changes.
- All-or-nothing restore, quarantine disposition, and the recoverable-versus-fatal
  boundary of the parent record stay exactly as decided there; every constructor
  refusal is a `ValueError`/`TypeError` the existing dispositions already classify.
- The admission bound remains admission-only (`2026-07-21-service-job-control-adr`,
  parent D6): the boundary validator must not enforce capacity, binding counts, or any
  bound that is a policy of the current configuration rather than a validity property
  of recorded state.
- The legacy start-paused normalization runs before construction, as it does before
  validation today (`src/vaultspec_rag/job_persistence.py:405`).
- Parent features are accepted and stable: the job lifecycle and persistence funnel,
  the durability contract, and the quiesce semantics. This decision moves validation
  ownership; it changes no lifecycle semantics, no file layout, and no version.

## Implementation

**D1 - The persisted-generation boundary owns generation-level invariants.**
`PersistedManagerState` gains a `__post_init__` that runs the generation validator:
job-id uniqueness (`src/vaultspec_rag/job_persistence.py:334`), idempotency-key length
and uniqueness (`src/vaultspec_rag/job_persistence.py:344`), and the relational rules
of `_validate_persisted_generation` and its per-job helpers
(`src/vaultspec_rag/job_persistence.py:430`). The parser's inline copies of those
checks fold into it; the parser's job becomes shape - decode, narrow, normalize,
construct - and the constructor's job becomes coherence. The helpers stay private to
the same module, invoked only from the constructor: one implementation, one home.

**D2 - Both ends traverse the one implementation.** The loader inherits the validator
because parsing ends in construction; the writer inherits it because every persist
serializes a freshly constructed generation
(`src/vaultspec_rag/job_manager/_persistence.py:506`). A manager defect that assembles
an incoherent generation now fails inside the funnel, in the producing process, at the
transition that introduced it. The funnel translates a construction refusal into its
existing persistence-error vocabulary so the mutation rolls back and the verb reports a
structured failure, exactly as a failed write does today
(`src/vaultspec_rag/job_manager/_persistence.py:524`,
`src/vaultspec_rag/job_manager/_records.py:270`).

**D3 - Producer-side pre-screens remain verb preconditions, not a second contract.**
Admission keeps refusing an over-long key with its structured outcome
(`src/vaultspec_rag/job_manager/_records.py:411`), importing the shared constant
(`src/vaultspec_rag/job_persistence.py:77`); the registries stay maps; adoption keeps
deduplicating equivalent active work (`src/vaultspec_rag/job_manager/_records.py:321`).
These are how the manager establishes the invariants and how a caller gets a friendly
answer; the boundary is what makes them a contract. A shared constant is one fact with
one home, not a mirror.

**D4 - Dead mirrors collapse.** The loader's attempt-lineage and progress re-checks,
unreachable since the models validate at construction, are deleted; the parent
self-reference check (`src/vaultspec_rag/job_persistence.py:555`) survives inside the
generation validator, because it needs the job's own id and is not model-local.

**D5 - Cross-record clock ordering is decided as a non-invariant.** Ratified, not
omitted: neither end orders records against each other, by design. Per-record flooring
(parent D7, `src/vaultspec_rag/job_manager/_persistence.py:638`) keeps each record
self-consistent, and a cross-record disagreement after a backwards clock step is the
only surviving evidence of the step. A reader rule would refuse truthful histories; a
writer rule would fabricate a chronology to hide the fault. Neither end gets one, and
the boundary validator must never grow one.

**D6 - A live job's replay binding is never evicted by the budget.** The
replay-binding ceiling currently floors at the live job count, and its own docstring
records the residual: a job adopted repeatedly under distinct keys pushes the map past
a floor that counts jobs while the map holds bindings, evicting a live binding at
normal capacity (`src/vaultspec_rag/job_manager/_records.py:378`). Decided: the floor
counts the union of the per-job key sets - the number of bindings referencing retained
jobs, already tracked per job - so the invariant the parent's D6 stated for lowered
bounds becomes exact under multi-key adoption. Memory stays bounded: keys are
length-capped, jobs are bounded by both retention bounds, and the map falls back to the
configured ceiling as work drains. No reader change: the loader enforces no binding
count, correctly, since capacity is not a validity property of recorded state.

## Rationale

One implementation at the persisted-generation boundary wins because this codebase has
a place both ends already pass through, which dissolves the usual trade rather than
picking a side of it. Defence in depth and single-implementation are only in tension
when depth means copies; here the depth is real - the writer proves every generation
before publishing it, the reader proves every generation after decoding it - and the
implementation count is still one, because the proof lives in the constructor of the
type that both acts produce. Drift between producer and loader becomes structurally
impossible instead of procedurally discouraged, which is the same move the parent
record made with shared requirement strings, completed at the level where the rules
are relational.

The mutation-point alternative fails on exactly the ground the canonical-code rule
predicts: it is a second, scattered spelling of the loader's rules, and it guards one
producer instead of the contract. It also protects nothing at the seam that matters -
`save_persisted_state` - where a caller other than this manager can still publish an
incoherent generation the next start must quarantine.

The precedent objection - the campaign loosened readers, it did not tighten writers -
does not apply, because nothing here tightens what any end accepts. The acceptance set
of the reader is unchanged; the writer gains no new rule, only an earlier occurrence of
the refusal the loader would have issued one process later. Failure geometry is the
whole change, and it moves in the direction the parent record argued: a wrongly-strict
rule - the quiesce class of defect - today costs the operator their history at the next
start via quarantine; under this decision it fails the producing verb loudly, rolls
back, and names the rule in a traceback where the fix is one process away. The new
failure surface on the write path is accepted deliberately, for the same reason the
parent accepted construction-time failures: the alternative failure is deferred,
anonymous, and more destructive.

The two folded items resolve on the same axis. Cross-record ordering has no producer
gap because it has no reader rule; making the deliberate absence a recorded decision
stops it resurfacing as an audit finding. The binding-eviction fix is not new policy
but the exact form of an invariant the parent's D6 already stated and approximated;
counting bindings instead of jobs is the correction that makes the stated property
true.

## Consequences

A producer bug that assembles an incoherent generation now surfaces at the transition
that introduced it: the verb fails with a structured persistence outcome, the mutation
rolls back, and the file on disk keeps its last valid generation - instead of a clean
write today and a quarantined history at the next start. Files from other builds,
other processes, and hand edits are refused exactly as before.

Loader error ordering changes, and that is the honest cost: today a duplicate job id
is refused before bindings are parsed and a bad key during binding parsing; after the
move, shape errors surface first and every relational refusal follows construction, so
a multi-defect file may name a different first defect. Every such refusal remains a
`ValueError`/`TypeError` with an unchanged message and the same quarantine
disposition, so no operator-visible behaviour changes; tests pinned to refusal order
or to the seam they exercise must follow. Reader-strictness tests must drive raw bytes
through the loader rather than constructing the state object, or the constructor will
refuse the fixture before the read path is exercised and the guard proves nothing.

Every persist pays the generation validator - comparisons on records the funnel
already serializes, no new asymptotic cost. The replay-binding map may now exceed the
configured ceiling while live jobs hold multiple keys, bounded by key length and both
retention bounds, in exchange for the replay answer staying truthful under repeated
adoption.

Implied implementation, concretely: the constructor and validator consolidation in
`src/vaultspec_rag/job_persistence.py` (fold the parser's inline uniqueness and length
checks into `__post_init__`, delete the dead lineage and progress mirrors, keep the
helpers module-private); the funnel's translation of a construction refusal into the
existing rollback-and-report path in
`src/vaultspec_rag/job_manager/_persistence.py:524`, covering the deferred progress
flush as well (`src/vaultspec_rag/job_manager/_persistence.py:557`); the budget floor
change and docstring update at `src/vaultspec_rag/job_manager/_records.py:378` with a
guard test proving a live binding survives multi-key adoption at normal capacity, shown
to fail against the old floor; and the test split between boundary refusals
(constructed) and reader refusals (raw bytes). Nothing changes in file layout, version,
or lifecycle semantics; no served surface changes shape.
