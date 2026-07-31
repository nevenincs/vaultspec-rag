---
tags:
  - '#adr'
  - '#job-state-version-suffix'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:0c65197ad07fcf5029a8d4112145c1a055295c2386ea64f9067c2b0792f6d47b'
related:
  - "[[2026-07-31-job-state-durability-adr]]"
  - "[[2026-07-31-job-state-durability-reference]]"
  - "[[2026-07-25-service-release-compatibility-adr]]"
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-06-30-qdrant-store-resilience-adr]]"
  - "[[2026-07-21-machine-discovery-recovery-adr]]"
  - "[[2026-07-14-storage-autoprune-safety-adr]]"
---

# `job-state-version-suffix` adr: `single canonical job-state path retained; version-suffixed state files rejected` | (**status:** `accepted`)

## Problem Statement

The durability record (`2026-07-31-job-state-durability-adr`) closed every restore
disposition but one, which it deliberately left open: whether the daemon's job-state
file should move from its single canonical path to a version-suffixed path per layout.
Today a build that meets a state file declaring a version above what it reads preserves
the file aside under a provenance-stating name and starts history-less, and that
disposition is forced rather than chosen - every lifecycle transition rewrites the
state file unconditionally through one funnel
(`src/vaultspec_rag/job_manager/_persistence.py:524`), so an older build that left a
newer file in place would atomically replace it on its first job action. A per-layout
filename would remove that contention at the root: an older build would never open the
newer build's path, so there would be nothing to refuse, nothing to move, and no
diagnosis needed.

The open question carried two sub-questions the hardening work surfaced: which build
reaps superseded suffixed files, since nothing today can - the temporary reclaimer's
positive identification requires both a leading dot and a `.tmp` suffix, which
preserved and suffixed names lack by construction
(`src/vaultspec_rag/job_persistence.py:213`,
`src/vaultspec_rag/job_manager/_persistence.py:713`) - and whether a downgraded build
should read an older-suffixed sibling rather than start empty, which would turn the
minimum-readable floor from a refusal threshold into a file-selection input. This
record decides the question and both sub-questions.

## Considerations

- The state file lives in the machine-scoped managed status directory
  (`src/vaultspec_rag/job_manager/state.py:47`,
  `src/vaultspec_rag/job_manager/manager.py:70`), and the daemon is a machine-global
  singleton behind a machine lock (`src/vaultspec_rag/_machine_lock.py`;
  `2026-07-25-service-release-compatibility-adr`). Two builds never write the
  directory concurrently; the only way a build meets another build's file is
  sequentially, across a restart.
- The layout version has never moved: the newest emitted and the minimum readable
  version are both 1 (`src/vaultspec_rag/job_persistence.py:82`,
  `src/vaultspec_rag/job_persistence.py:87`), and the declared format policy says
  additive growth never moves it - the version moves only for a re-layout no additive
  read can absorb (`2026-07-31-job-state-durability-adr`).
- A restore generation is all-or-nothing by accepted constraint: it loads whole or not
  at all, because a partially applied generation would invent a history nobody
  recorded (`2026-07-31-job-state-durability-adr`).
- The file is job history - observability data - while the index lives in vector
  storage; losing it costs a record of past work, never availability or search
  results (`2026-07-31-job-state-durability-adr`).
- The preserve disposition already loses no bytes: the newer file is renamed
  unchanged to a collision-stepping provenance name with the move-back remediation in
  the outcome message (`src/vaultspec_rag/job_manager/_persistence.py:315`,
  `src/vaultspec_rag/job_manager/_persistence.py:713`), following the
  move-never-delete precedent (`2026-06-30-qdrant-store-resilience-adr`) and the
  typed-condition precedent that an uninterpretable-but-intact file is its own
  diagnosis, not damage (`2026-07-21-machine-discovery-recovery-adr`).
- Automated deletion in this project requires positive classification plus a
  persisted, continuously observed grace window; the human is replaced by time, never
  merely removed (`2026-07-14-storage-autoprune-safety-adr`). Any reaper for a new
  file family inherits that bar.
- The release-compatibility record rejected compatibility ranges until the project
  declares a policy a range could encode; encoding structure for a future format
  before that format exists is the same shape of guess
  (`2026-07-25-service-release-compatibility-adr`).
- Restored idempotency bindings satisfy repeated requests with recorded job ids, and
  restored nonterminal jobs are dispatched as live work
  (`2026-07-21-service-job-control-adr`), so restoring a stale generation does not
  merely display old history - it acts on it.

## Considered options

- **Version-suffixed state file per layout.** Rejected. Its promised
  downgrade-then-upgrade continuity dissolves under the persistence funnel: the
  downgraded build writes its own suffixed file on its first transition, so the
  re-upgraded build faces two diverged files - a fork - and the all-or-nothing
  generation constraint forbids merging them, while selecting either silently
  discards the other. Full argument under Rationale.
- **A `latest` pointer or a manifest naming the current file.** Rejected. Both
  recreate the single contended path one level up - every build must read and write
  the pointer, so the version contention returns at the pointer's own format - and
  add a crash-consistency obligation between pointer and file that the single path
  does not have. A manifest additionally needs its own version, which regresses.
- **A directory per version.** Rejected. Same fork problem as the suffix, a heavier
  migration, and it multiplies the reaping surface from files to trees.
- **Downgrade reads an older-suffixed sibling instead of starting empty.** Rejected
  outright, independent of the suffix decision. An older sibling is a snapshot frozen
  at the moment of the last upgrade: restoring it resurrects stale nonterminal jobs
  as dispatchable work and stale idempotency bindings as answers to fresh requests -
  invented presence, the very thing the all-or-nothing constraint exists to prevent.
  Starting empty is honest absence. The minimum-readable floor therefore stays a
  refusal threshold and never becomes a file-selection input, in this design and any
  future one.
- **Keep the single canonical path and the preserve-aside disposition.** Chosen. The
  single path guarantees a linear history with one authoritative present; the rare
  downgrade across a future re-layout costs a history-less start with the evidence
  preserved and the remediation named, which is proportionate to observability data.

## Constraints

- The parent features are accepted and stable: the restore dispositions and format
  policy (`2026-07-31-job-state-durability-adr`), the job lifecycle and persistence
  funnel (`2026-07-21-service-job-control-adr`), and the release-compatibility gate
  (`2026-07-25-service-release-compatibility-adr`). This record changes none of them;
  it closes the one question the durability record left open, and every other clause
  of those records stands.
- The decision holds while its premises hold. It must be re-read, though not
  necessarily reversed, by the release that first raises the emitted layout version
  (`src/vaultspec_rag/job_persistence.py:82`), because that release is the first with
  a concrete second layout in hand.
- Three trigger conditions would genuinely reopen it: job history being promoted from
  observability data to availability-bearing state whose loss costs correctness;
  evidence that downgrades across a re-layout are routine operator practice rather
  than an exceptional rollback; or relaxation of the machine-singleton guarantee such
  that two builds can hold the state directory concurrently.
- If a future record adopts per-version paths despite this one, it must ship three
  things in the same change, not as follow-ups: a migration that adopts the existing
  unsuffixed file exactly once; a reaper for superseded siblings meeting the
  automated-deletion bar - positive per-name identification in the structural style
  of the temporary reclaimer, a filesystem-observed grace window, and move-aside
  before any destruction (`2026-07-14-storage-autoprune-safety-adr`,
  `2026-06-30-qdrant-store-resilience-adr`); and an explicit fork policy stating
  which diverged sibling wins on re-upgrade and where the loser is preserved.

## Implementation

Nothing. The decision is that the shipped contract is the accepted one: one canonical
state filename (`src/vaultspec_rag/job_manager/state.py:47`), the preserve-aside
disposition for a newer-build file with its structured outcome and move-back
remediation (`src/vaultspec_rag/job_manager/_persistence.py:315`), the quarantine and
fatal-remainder dispositions unchanged, and the minimum-readable floor as a refusal
threshold only (`src/vaultspec_rag/job_persistence.py:87`). No code, no migration, no
new file family, no reaper. The reaping question is answered by construction - no
suffixed family is created, so there is nothing to reap - and the set-aside family's
growth is bounded per event, not per schedule: one file per downgrade or corruption
incident, collision-stepped, never rewritten.

## Rationale

Three arguments decide it, in descending order of weight.

First, the contention the suffix removes does not exist. Per-version paths earn their
cost when two writers of different versions can hold one directory at once; the
machine lock and the singleton daemon exclude that by architecture, and the
release-compatibility gate refuses even a mismatched client before it drives a
daemon. What remains is a strictly sequential handoff across a restart, and the
preserve-aside disposition already handles it without losing a byte.

Second, the continuity the suffix promises dissolves into a fork. The premise of
"the older build never touches the newer file, so history survives the downgrade" is
only half the story: the downgraded build starts writing its own suffixed file on its
first lifecycle transition, because the funnel writes unconditionally
(`src/vaultspec_rag/job_manager/_persistence.py:524`) and a running daemon
transitions constantly. On re-upgrade there are two diverged histories. Merging them
is forbidden - a merged generation is a history nobody recorded, exactly what the
all-or-nothing constraint exists to refuse - and selecting either one silently
discards the other. The single path makes the same discard explicit instead: logged
as a structured condition, evidence preserved on disk under a provenance name, and
reversible by the one hand move the outcome message states. A design that converts
an explicit, evidenced, reversible discard into a silent one is not an improvement,
and this is why no shape of the family - suffix, pointer, manifest, or directory -
escapes the objection: the fork is created by the downgraded build writing at all,
not by how files are named.

Third, the trigger has never fired. The version sits at 1, additive growth never
moves it by declared policy, and the preserved-newer-file event therefore requires a
future re-layout plus a downgrade across it. Designing the migration, the reaper, and
the fork policy now would encode guesses about a layout that does not exist - the
same reasoning under which the release-compatibility record refused ranges before a
policy existed to encode. The honest sequencing is the one under Constraints: the
release that first moves the version re-reads this record with its layout in hand.

## Consequences

The daemon keeps a linear job history with one authoritative file, and operators keep
one path to know about. A downgrade across a future re-layout keeps its current,
deliberate cost: a history-less start, a structured `job_state_from_newer_build`
outcome, and a hand move-back to resume the newer history under a build that reads it.
This record accepts that cost as proportionate to observability data and states it
rather than hiding it.

Both open sub-questions are closed. Reaping: no suffixed family exists to reap, and
the bar any future family must clear is recorded under Constraints. Downgrade-reads-
older-sibling: rejected permanently on the staleness argument, so the minimum-readable
floor's role as a refusal threshold is now decided, not incidental.

What this record deliberately does not solve: the set-aside family (quarantined and
newer-build preserved files) still accumulates without bound in principle. It grows
only when an incident occurs, each file is evidence an operator may still act on, and
automated deletion of sole-copy evidence carries obligations
(`2026-07-14-storage-autoprune-safety-adr`) far heavier than the gap. It stays open
knowingly, unchanged by this decision.

The residual risk of deciding "no" is that the first real re-layout arrives with
downgrade pressure this record underestimated. The mitigation is built in: the
constraint binding that release to re-read this record, the enumerated triggers, and
the requirement that any future adoption ship migration, reaper, and fork policy as
one change mean the reversal path is specified even though the reversal is not
expected.
