---
tags:
  - '#adr'
  - '#job-state-durability'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:5e77d0a88fc46eee1f07013ef7dc42047c4808dce68b9d76dfbaa63dec3027d9'
related:
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-25-service-release-compatibility-adr]]"
  - "[[2026-06-30-qdrant-store-resilience-adr]]"
  - "[[2026-07-21-machine-discovery-recovery-adr]]"
  - "[[2026-06-11-service-jobs-operability-adr]]"
  - "[[2026-07-21-managed-log-contract-adr]]"
  - '[[2026-07-31-job-state-durability-reference]]'
---

# `job-state-durability` adr: `durable job-state contract: writer-validated records, survivable restore` | (**status:** `accepted`)

## Problem Statement

A user's daemon became permanently unstartable. The canonical job-state file - the file
the daemon writes itself on every lifecycle transition - held JSON `null` where a float
was required, restore is all-or-nothing, and the restore failure was a fatal startup
abort. One bad field therefore bricked every subsequent start, and the only recovery was
an engineer locating the file and moving it aside by hand.

Behind the incident sits one recurring defect shape: **the loader enforced constraints no
producer enforced**. A value invalid on read was silently accepted on write, and nothing
failed until the next start - a different process, with the write long gone and no stack
trace naming the culprit. The shape appeared at three levels:

- **Scalar.** A `float`-declared resource reading accepted `None` at construction and
  serialized it as `null`.
- **Relational.** The loader's persisted-lifecycle map refused the `PAUSED` observed /
  `RUNNING` desired pair that service quiesce deliberately persists when parking work -
  here the *loader* was wrong, not the producer, and the manager could write a file its
  own loader rejected.
- **Whole-file.** A strict `version ==` equality check meant the first version bump would
  route every operator's intact file into the corrupt-file path on the first start of the
  new build, destroying history wholesale.

This record is retrospective: it captures the decisions taken in the completed hardening
of this contract and records the one decision deliberately left open. Its grounding is
the implementation itself, catalogued with the incident and the defect matrix in
`2026-07-31-job-state-durability-reference`, rather than a separate research document.

## Considerations

- The state file is job history - observability data. The index itself lives in vector
  storage, so refusing to start over this file destroys availability to protect a record
  of past work (`src/vaultspec_rag/job_manager/_persistence.py:270`).
- Every lifecycle transition rewrites the state file unconditionally through one funnel
  (`src/vaultspec_rag/job_manager/_persistence.py:524`), so a file "left in place" for a
  future build is a file about to be atomically replaced.
- All-or-nothing restore is an existing, correct property: a partially applied
  generation would invent a history nobody recorded.
- Stamps come from the wall clock, which is free to move backwards (NTP correction, VM
  restore, manual set), while the loader enforces a per-record total order over them.
- The configured nonterminal bound was decided as an *admission* limit on new work
  (`2026-07-21-service-job-control-adr`), and nonterminal records are non-evictable
  under that same record; neither property says a bound change may cost a start.
- Quarantine precedent exists: the store recovery decision moves a corrupt collection
  aside - never deletes - to a timestamped sibling, keeping recovery reversible
  (`2026-06-30-qdrant-store-resilience-adr`).
- Typed-condition precedent exists: discovery resolution refuses to collapse distinct
  degraded conditions into absence (`2026-07-21-machine-discovery-recovery-adr`), and
  the release-compatibility decision reports a schema pair a build does not implement as
  its own condition, distinct from both absence and damage
  (`2026-07-25-service-release-compatibility-adr`).
- The structured events the new dispositions emit travel through the managed log
  surface and its bounded operator views (`2026-07-21-managed-log-contract-adr`,
  `2026-06-11-service-jobs-operability-adr`).

## Considered options

- **Weaken the read path: coerce or default invalid values on load.** Rejected. A loader
  that repairs what it reads invents state, hides every producer bug permanently, and
  makes the file's contents unfalsifiable. The read path keeps its full strictness.
- **Keep the fatal abort and add an operator repair verb.** Rejected. It leaves
  availability hostage to observability data and still requires a human in the loop for
  a file the daemon wrote itself; the incident is exactly this path performed by hand.
- **Validate at the producer only and trust the file on read.** Rejected. Files arrive
  from other builds, other processes, and hand edits; symmetry needs both ends.
- **Writer/reader symmetry plus a survivable restore.** Chosen. Validate at
  construction, where the stack trace names the producer; keep the loader strict; turn
  an unreadable file from a fatal abort into a preserved, diagnosed set-aside.
- **A version-suffixed state file per layout.** Deliberately **not taken - open**, not
  rejected. It is the only design giving true downgrade-then-upgrade continuity, and it
  is recorded as an open decision under Consequences with the two questions it must
  answer.

## Constraints

- All-or-nothing restore is preserved: nothing is ever partially applied. A generation
  loads whole or not at all.
- The recoverable-versus-fatal boundary is fixed: "the bytes were read and they are
  wrong" is recoverable; "the bytes could not be read or could not be moved" stays
  fatal, because continuing would mask a state directory the next write cannot use
  either.
- The read path is not weakened: no coercion, no defaulting, no legacy tolerance beyond
  the one pre-existing, explicitly named legacy normalization.
- Capacity is an admission bound on new work, never a validity property of
  already-recorded state; restore must not enforce it.
- Additive growth never moves the file version; the version moves only for a re-layout
  no additive read can absorb, and the minimum-readable floor stays behind when it does.
- Parent features are accepted and stable: the job lifecycle and its persistence funnel
  (`2026-07-21-service-job-control-adr`), the release-compatibility gate
  (`2026-07-25-service-release-compatibility-adr`), and the managed log contract. This
  decision changes restore disposition and validation placement, not lifecycle
  semantics, transport, or ownership.

## Implementation

**D1 - Writer/reader symmetry.** Every persisted model validates at construction:
timestamps (`src/vaultspec_rag/job_models.py:393`), resource readings
(`src/vaultspec_rag/job_models.py:472`), snapshots and their scalar fields
(`src/vaultspec_rag/job_models.py:576`), progress, runtime identity, and the
idempotency binding's flag (`src/vaultspec_rag/job_persistence.py:108`). Shared
requirement strings keep the producer and reader spelling one rule once
(`src/vaultspec_rag/job_persistence.py:96`). The loader's one genuinely wrong
constraint is corrected rather than mirrored: paused work may persist running intent,
which is how resume distinguishes quiesce-parked work from an operator's deliberate
pause (`src/vaultspec_rag/job_persistence.py:526`).

**D2 - Survivable restore.** Invalid content is quarantined to a timestamped sibling
and startup proceeds with an empty registry
(`src/vaultspec_rag/job_manager/_persistence.py:270`), under a collision-stepping name
that never overwrites earlier evidence
(`src/vaultspec_rag/job_manager/_persistence.py:713`). The outcome is a structured
success (`job_state_quarantined`) stating that job history was lost and index data is
unaffected.

**D3 - The fatal remainder.** An unreadable path aborts startup as
`job_state_unreadable`, and a set-aside move that fails aborts as its own failure code
(`src/vaultspec_rag/job_manager/_persistence.py:230`,
`src/vaultspec_rag/job_manager/_persistence.py:369`): both are environment faults the
next persist would hit too.

**D4 - Version as a supported range.** The reader accepts everything from a
minimum-readable floor up to the newest layout it emits
(`src/vaultspec_rag/job_persistence.py:87`,
`src/vaultspec_rag/job_persistence.py:369`), each refusal naming the direction of the
mismatch and the range that would have been read. The format-change policy is stated at
the codec itself: additive growth is not a format change and never moves the version.

**D5 - Newer-build files are a diagnosis, not damage.** A version above the readable
range raises a dedicated error carrying both numbers
(`src/vaultspec_rag/job_persistence.py:135`) and the file is preserved unchanged under
a name stating provenance - written by a newer build - rather than asserting corruption
(`src/vaultspec_rag/job_manager/_persistence.py:315`), with the remediation (move it
back under a build that reads it) in the outcome message.

**D6 - Capacity never costs a start.** The restore-time capacity abort is removed; an
over-bound restore is kept whole and reported as a warning, with the overflow drained
by admission refusal on new work
(`src/vaultspec_rag/job_manager/_persistence.py:192`). The replay-binding ceiling
floors at the live job count so a lowered bound cannot evict a binding whose job is
still addressable (`src/vaultspec_rag/job_manager/_records.py:378`).

**D7 - Forward-only stamps.** A new stamp is floored at the record's own previous
state-change stamp, per record only, with a warning carrying the step magnitude
(`src/vaultspec_rag/job_manager/_persistence.py:638`); records are never reordered
against each other, so a backwards clock step remains visible across jobs.

**D8 - Closed telemetry value space.** Free-form run-telemetry blocks are constrained
at construction to JSON-native values the round trip returns intact
(`src/vaultspec_rag/job_models.py:259`), so a substituting encode (tuple to list,
non-string key to string) or an unencodable value fails in the producing traceback
instead of a later process.

**D9 - Durability mechanics.** The write path uses the shared atomic publisher with
serialization ahead of temp creation (`src/vaultspec_rag/job_persistence.py:177`), and
abandoned temporaries are reclaimed only under positive name identification plus a 24h
filesystem-observed grace window (`src/vaultspec_rag/job_persistence.py:213`).
Progress publication constructs the canonical record rather than mirroring its rules
(`src/vaultspec_rag/job_manager/_progress.py:434`).

## Rationale

Validating at the producer is the only placement that puts the failure in the same
process, same stack, and same moment as the defect; the loader can only ever report
that *someone* wrote a bad value, a process too late to say who. Keeping the read path
at full strength is what makes the symmetry a contract rather than a migration: the
same rule enforced at both ends cannot drift apart silently, and the round-trip suite
now drives real lifecycle sequences through the manager and back through the real
loader to prove it.

Quarantine-over-abort follows the proportionality argument the store recovery decision
already made: a defect scoped to a history file should not deny service entirely, and a
move - never a delete - keeps the evidence and keeps the action reversible. The fatal
remainder is the same boundary read from the other side: an environment fault is not
scoped to the file, so continuing would trade one loud failure for a masked one that
breaks every later persist.

The version range does not reopen what the release-compatibility record rejected.
That record refused compatibility *ranges between releases* because no declared policy
existed for one to encode; this file format now declares exactly such a policy -
additive growth never moves the version, the version moves only on re-layout, the
floor trails deliberately - so the range encodes a stated rule, not a guess. The
newer-build diagnosis applies that record's own precedent (a schema pair this build
does not implement is its own condition, distinct from absence) and the discovery
record's refusal to collapse distinct degraded states into one.

This record supersedes no prior record. It extends `2026-07-21-service-job-control-adr`
at two points that record left undecided or that implementation had over-applied: the
disposition of a restore failure (never decided there; now quarantine-and-continue with
a fatal environment remainder) and the reach of the admission bound (decided there as
admission-only; the restore-time abort was an implementation over-reach, now removed).
It also narrowly corrects the persisted-lifecycle map to match that record's own
quiesce-parking semantics. All other clauses of the parent records stand.

## Consequences

Operators gain a daemon that always starts over its own state file: corrupt history
costs the history, never the service, and every disposition is a structured, logged,
named condition with the evidence preserved on disk. Producer bugs now surface in the
producing traceback at construction time - which is also the honest cost: a defect that
previously wrote a bad file silently now raises where the value is made, a new failure
surface accepted deliberately because the alternative was deferred, anonymous, and
fatal.

Observable behaviour changes: startup no longer aborts on a corrupt state file
(quarantine, empty history, structured success); a lowered nonterminal bound no longer
aborts startup (warning plus admission refusal until drained); persisted stamps may be
floored forward across a backwards clock step, so an interval closed inside the step
reads as zero rather than negative - the ordering is recorded, the duration inside the
step is not; and the restore-failure code vocabulary is split (`job_state_invalid`
becomes `job_state_unreadable`, `job_state_quarantined`, `job_state_from_newer_build`,
and the two move-failure codes), so anything keyed on the old single code must follow.
The file's bytes also differ (ASCII-escaped, no trailing newline) with unchanged
semantics.

Residual gaps, held open knowingly: generation-level invariants (idempotency-key
length and uniqueness, job-id uniqueness) remain loader-only until their validation
moves to construction as one implementation; cross-record clock ordering is
deliberately untouched, since distorting it would hide the fault the per-record floor
reports.

**Open decision - a version-suffixed state file.** Downgrade-then-upgrade continuity is
not provided: a downgraded build preserves a newer file and starts history-less, and
only a hand move restores the history later. A per-layout suffixed filename is the only
design that gives true continuity, and it is deliberately not taken here. The current
disposition must remain move-aside because the persistence funnel writes the state file
unconditionally on every lifecycle transition
(`src/vaultspec_rag/job_manager/_persistence.py:524`): an older build leaving a newer
file in place would have its first job action atomically replace it, so "leave it for
the newer build" is the one option that destroys the data. Taking the suffix decision
requires answering two questions this work surfaced: which build reaps superseded
suffixed files - today nothing does, and the temporary reclaimer structurally cannot,
since its positive identification excludes every preserved name by construction
(`src/vaultspec_rag/job_persistence.py:213`,
`src/vaultspec_rag/job_manager/_persistence.py:713`) - and whether a downgrade should
*read* an older-suffixed sibling rather than start empty, which would turn the
minimum-readable floor from a refusal threshold into a file-selection input. That is a
format decision requiring its own record; this one stays honest by naming what it does
not provide.
