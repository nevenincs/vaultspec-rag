---
tags:
  - '#adr'
  - '#worktree-dedup'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
body_hash: 'sha256:73f9cc92c7e6d9c7d28323adb802a68990459f2584859eb77ca2744527b8260f'
related:
  - "[[2026-07-28-worktree-dedup-research]]"
---

# `worktree-dedup` adr: `no storage-level dedup; the deferred tenant option stays closed` | (**status:** `rejected`)

## Problem Statement

The accepted encode-seam reuse decision took the compute half of duplicate
worktree corpora and left one option explicitly open: payload-partitioned shared
collections with the root as a payload tenant, decoupled at the time to "a
separate future ADR about storage dedup", with its consequences section stating
that per-root storage duplication remains
(`2026-07-24-worktree-index-reuse-adr`). That forward pointer has been open
since, and an open pointer in an accepted record is read by the next author as
work that is owed. This record closes it. It decides whether storage-level
deduplication across worktree corpora is opened now, and what would reopen it -
nothing else. The compute half is not revisited and reclamation of dead
namespaces is not redesigned; both already have owners.

The decision is needed now because the premise the pointer rests on is
measurable and has been measured, and because a decision that is deferred
without a reopen condition is indistinguishable from one that was forgotten.

## Considerations

- The duplication the pointer anticipates is largely not occurring: six live
  worktrees of this repository, one stored namespace
  (`2026-07-28-worktree-dedup-research`).
- The one cross-worktree duplicate namespace on this machine is an orphan, and
  orphan reclamation is complete and gated, not missing.
- Two footprint terms above the duplicate term - superseded generations and
  fixed preallocation - already have accepted owners, the second measured at
  roughly 84% of a backend by `2026-07-21-storage-prealloc-reclaim-adr`.
- The 1:1 prefix-to-root relation is not a naming convenience; classification,
  the persisted grace clock, archive-before-destroy, and every destructive verb
  read it as their subject.
- Storage-side dedup was priced once already and nothing measured since reduces
  its cost.
- Aggregate machine pressure from duplicate corpora is real but is attributed to
  the demand side, where the encode-seam decision already acts
  (`2026-07-28-pressure-management-research`).

## Considered options

- **Payload-partitioned shared collections, root as tenant.** True storage
  dedup. Rejected: it falsifies the 1:1 prefix-to-root invariant, converts grace
  from continuous root absence into membership refcounting, degrades local mode,
  and re-concentrates writes. Its benefit ceiling on measured state is one
  orphaned namespace already scheduled for destruction by machinery that exists.
- **A dedup-triggered reclamation path that destroys a namespace whose content
  duplicates another root's.** Rejected: the trigger is the corpus-level
  similarity judgment the encode-seam record rejected on correctness grounds,
  and it would have to bypass or re-implement the classification, persisted
  grace, liveness, re-count, and archive gates rather than reuse them.
- **Alias sibling worktrees onto one shared namespace.** Rejected: same
  invariant loss as the tenant option, and for nested agent worktrees it
  achieves only what traversal exclusion already achieves.
- **Amend the encode-seam record in place to say storage dedup is settled.**
  Rejected: that record deliberately decoupled the two decisions; folding the
  answer back in re-couples what it separated and makes an accepted record
  narrate a conclusion it did not reach.
- **Delete this record and leave the pointer open.** Rejected: it discards the
  measurement and leaves the next reader the same unanswered question at a
  higher price.
- **Chosen: reject storage-level dedup, close the deferred slot, and bind
  reopening to named observable conditions.**

## Constraints

This record adds no dependency and no implementation surface, so it carries no
maturity or frontier risk. Its constraints are what any future reopening
inherits, all of them live and load-bearing today:

- One prefix names one root, and every destructive verb reads that relation as
  its subject. A design that breaks it must first replace the whole
  classification and grace surface, not adapt it.
- Automatic destruction requires classification plus a persisted continuous
  grace window; a `live` or `unverifiable` observation resets the clock, so
  races can only extend protection.
- An unknown or unverifiable namespace is reported and never auto-touched.
- A point-bearing namespace is archived successfully before it is destroyed, and
  a snapshot torn by a concurrent write defers the delete.
- Maintenance stays read-and-drop and never reaches a lifecycle helper.
- No store-wide mutex across collections; server mode takes no point-operation
  locks.

Parent-feature stability: this record depends on the encode-seam decision being
accepted and shipped, which it is, and on the reclamation lifecycle being
complete, which the grounding verifies at locator level. Neither is in flight.

## Implementation

None. No code, configuration, or schema changes follow from this record.

What it changes is ownership clarity. Duplicate-content compute cost stays owned
by the encode-seam decision. Reclamation of a dead worktree's corpus stays owned
by the orphan tiers of the storage lifecycle. Intra-root superseded generations
stay owned by the generation reclaim path. Backend footprint stays owned by
geometry reconcile. The deferred tenant option is closed, not pending.

Reopening requires one of three observable conditions, each measurable with
read-only inspection and none of them true today:

- Two or more roots sharing a git common dir hold live namespaces
  simultaneously and sustainedly, so cross-worktree duplication is a standing
  state rather than an orphan awaiting its grace window.
- The cross-root duplicate term exceeds the fixed-preallocation term after
  geometry reconcile has converged, inverting which term is worth attacking.
- Backend footprint pressure persists that geometry reconcile, generation
  reclaim, and the ephemeral idle tier together cannot hold.

A reopening record supersedes this one and restates its own measurement; it does
not inherit these figures.

## Rationale

Storage dedup loses on benefit, not on difficulty. Its entire addressable term
on measured state is one namespace, 18% of the backend, and that namespace is an
orphan whose destruction is already designed, gated, and archived - so the
option's payoff is to reclaim faster something that is already scheduled to be
reclaimed, at the price of the invariant every other destructive gate is built
on. Two larger terms sit above it with accepted owners. Attacking the smaller
term by breaking the safety surface that governs the larger ones is the wrong
trade in a way that does not depend on threshold choices.

The premise is also weaker than assumed. Nested agent worktrees never enter a
corpus - traversal excludes them and the domain classifier demotes them - so the
observed duplication factor for this repository is 1.0 across six worktrees.
A decision built to solve N-way duplication would be solving a condition this
machine does not exhibit.

A rejected record beats deletion here because the encode-seam record left an
explicit forward pointer to a future storage-dedup ADR. Deleting the scaffolds
would leave that pointer dangling and the measurement unrecorded, and the next
author would re-derive it. Amending the encode-seam record instead would
re-couple two decisions it deliberately separated. Writing the answer where the
pointer expects to find it is the only option that closes the question without
distorting the record that raised it.

## Consequences

- The deferred storage-dedup slot is closed with a stated answer and named
  reopen triggers, so a reader of the encode-seam record no longer sees owed
  work.
- Every safety invariant the lifecycle rests on survives untouched: one prefix
  per root, classification plus persisted continuous grace, archive before
  destroy, no auto-touching of unknown or unverifiable namespaces.
- Worse: per-root storage duplication remains, permanently and by decision. A
  machine that does begin indexing many sibling worktrees as roots pays full
  storage per root, and nothing in this record bounds that. The reopen triggers
  are how that becomes visible, but they are conditions someone must look for,
  not alarms.
- Worse: the 18% duplicate residue on this machine persists until its orphan
  grace completes, and its grace stamp is currently unset, so that is not on a
  known timeline. This record does not fix that, and the cause was not
  established.
- Worse: anyone who later hits a genuine N-way case has a rejection rather than
  a design to lean on, and must reopen with fresh measurement. That is the cost
  of deciding on one machine's evidence, accepted deliberately over deciding on
  none.
- The measurement itself is durable: the footprint decomposition in the
  grounding gives the next storage question a baseline it would otherwise have
  to re-derive.
