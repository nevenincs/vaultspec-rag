---
tags:
  - '#adr'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:77945ce7787b04d757599b5a21030463e43d159a287e5e35bfbf708a5b52d18f'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-research]]"
  - "[[2026-07-14-storage-autoprune-safety-adr]]"
  - "[[2026-07-14-storage-namespace-hygiene-adr]]"
---

# `qdrant-collection-sprawl` adr: `retention discrimination for the ephemeral namespace class, and the prerequisites that let it execute` | (**status:** `accepted`)

## Problem Statement

## Problem Statement

The managed qdrant store has reached a namespace population it was never calibrated
for, at a resource cost documented in `2026-09-08-qdrant-collection-sprawl-research`.
The reclamation contract from `2026-07-14-storage-autoprune-safety-adr` is not
failing - the research establishes that essentially every orphan is legitimately
inside its window and that the observed backlog is what that contract's own arithmetic
predicts. What changed is the population. A steady stream of throwaway harness
sandboxes now enters the shared backend, each a full repository index, and each is
held for seven days because the only retention input is whether a namespace holds
points.

A decision is needed now because the situation is no longer merely expensive. The
research's readiness finding records the store failing to come up at this collection
count and staying down, and the maintenance cycle has exactly one caller inside the
daemon that needs it. The population that causes the start to fail is therefore the
population only the reaper can reduce, and that loop is open at the time of writing
rather than closed - the reaper has not run since the store went down. Two further
defects, an exception clause that lets one slow snapshot unwind a whole cycle and an
archive that turns over wholesale under a drain, mean that changing a retention window
on its own would not drain the backlog even once the store is serving. This record
decides the retention change and the conditions under which it can actually run.

## Considerations

- Retention is keyed on point count alone, so a throwaway sandbox and a real
  repository are indistinguishable to the policy once both hold points; ephemerality
  is already derived and already trusted for destruction on the live side, and is
  discarded at the moment it becomes best-evidenced
  (`2026-09-08-qdrant-collection-sprawl-research`).
- A namespace that was always temporary *and* whose root is provably gone carries
  strictly stronger evidence of death than either signal alone. That asymmetry, not a
  desire for throughput, is what licenses a shorter window.
- The reaper runs only inside a started daemon, and the daemon can fail to start at
  this collection count; retention changes are inert until that holds
  (same grounding).
- The parent contract already requires that any failing gate skips the prefix and
  reports why. The code does not deliver that for transport timeouts, so a cycle
  aborts where the contract says it should defer one namespace (same grounding).
- Archive-before-destroy for point-bearing data is a standing invariant of this
  codebase and is not reopened here. Its value is conditional on the archive still
  existing when someone looks, which the research shows a drain would destroy.
- The parent's wording requires a *recoverable* archive, and in-place restore is
  unsupported on Windows; archives stay portable to a non-Windows server
  (same grounding).
- Nothing at any layer bounds total collection count, so a future harness that outruns
  the window reproduces this identically.
- The dominant producer is a foreign project's harness reaching our shared backend, so
  the durable fix must be consumer-side retention rather than producer-side
  discipline. Our own test residue is the exception and is in scope.
- The ephemeral-registration affordance deferred by
  `2026-07-14-storage-namespace-hygiene-adr` pending confirmed need now has that
  confirmation.

## Considered options

- **O1 - carry ephemerality into the orphan decision (chosen).** Adds `is_temp_rooted`
  as an input to the orphan window alongside point count, giving the ephemeral class a
  dedicated short window. Small, local, reuses the existing predicate and every
  existing safety gate. Cannot help a sandbox rooted outside the OS temp directory.
- **O2 - shorten `grace_hours_data` globally.** Rejected: it buys the same drain rate
  by weakening protection for real repositories, which is the one class the long window
  exists for. The problem is discrimination, not duration.
- **O3 - skip the archive for ephemeral namespaces.** Rejected: archive-before-destroy
  for point-bearing data is a standing invariant, and trading it for throughput would
  make the fastest path also the least recoverable.
- **O4 - a progress-aware readiness budget (chosen, prerequisite).** Replaces a fixed
  wall-clock deadline with one that tolerates a child still making measurable recovery
  progress, bounded by a hard ceiling so a genuinely wedged child is still caught.
  Sequenced ahead of O1 because O1 does not execute without it.
- **O5 - raise `qdrant_ready_timeout_seconds` to a larger fixed value.** Rejected as
  the primary: it trades one arbitrary constant for another and silently re-breaks at
  a higher collection count, which is precisely how the present value stopped being
  adequate. Acceptable only as a stopgap inside O4's ceiling.
- **O6 - raise the archive cap for the drain (chosen, prerequisite).** Takes
  `storage_autoprune_archive_max_gb` from 20.0 to 64.0, roughly the 2.5x the research
  derives as cover for a full ephemeral drain plus the non-temp orphans behind it, so
  the archive does not evict the evidence it is writing. The cost is real and awkward:
  it adds up to 44GB of disk on the host whose defining complaint is that this
  subsystem is already its largest resource consumer. The alternative is an archive
  that satisfies the letter of archive-before-destroy while retaining roughly one
  cycle of it.
- **O7 - rate-limit the ephemeral drain so archive turnover stays bounded.** Rejected
  in favour of O6: it protects the archive by prolonging exactly the resource pressure
  this record exists to relieve, and the per-cycle cap already bounds burst size.
- **O8 - a hard cap on collection count that triggers destruction.** Rejected: a count
  threshold is not evidence about any particular namespace, and letting a population
  statistic authorise a drop is the failure the grace contract exists to prevent.
- **O9 - report collection count on the status surface (chosen).** Pure observability:
  surfaces the count and the ephemeral backlog so unbounded growth is visible before it
  is expensive. Authorises nothing and changes no gate.
- **O10 - let a count ceiling widen the per-cycle reclaim cap.** Deferred, not
  rejected. The parent enumerates `max_per_cycle` among its safety gates, so this
  reclassifies a gate into a throughput control. That may well be right, but it is a
  separate decision and is not needed to drain the present backlog.
- **O11 - payload partitioning instead of collection-per-repo.** The
  upstream-recommended shape; it would remove the class outright rather than managing
  it. Rejected for this record: a storage-schema migration of every collection is
  disproportionate to the defect and would block the fix behind a large migration.
  Named so a future record can size it deliberately.
- **O12 - producer-side teardown only.** Rejected as the primary fix: the dominant
  producer is outside this codebase. Kept as a narrow secondary for this project's own
  tests, whose isolation is worth tightening on its own merits rather than because any
  particular residue was traced to them.

## Constraints

- No frontier risk; every primitive is in-tree and mature. `is_temp_rooted`, the tiered
  decision function, the archive gate, the pre-drop re-count, the active-job liveness
  probe, and the persisted grace ledger all exist and are exercised.
- The parent contract `2026-07-14-storage-autoprune-safety-adr` is `accepted` and
  shipped. O1 extends its tiering and reverses none of its gates. O10, which would
  have reclassified the per-cycle cap gate, is deferred out of this record precisely so
  that claim holds without qualification.
- Server mode only, matching the parent: the local store has one namespace and no
  manifest.
- Bounded by qdrant `1.19.0` behaviour: eager sequential collection recovery has no
  configuration or version remedy, so reducing the collection count is the only lever
  on recovery time, and O4 must accommodate rather than eliminate it.
- Recoverability is platform-limited: on Windows the archive cannot be restored in
  place. O6 preserves the evidence but does not make it locally restorable, and this
  record accepts that gap rather than asserting it away.
- First-cycle burst: every ephemeral orphan stamp is already older than any window this
  record would set, so the entire ephemeral backlog becomes eligible on the first cycle
  after landing. The per-cycle cap, not the window, governs that burst.
- Test isolation: any test exercising these paths must point the qdrant storage-dir
  environment variable at a temp path, or it writes into the operator's real managed
  directory. The temp-rooted residue on the audited host was NOT traced to this
  project's tests and its origin is undetermined, so this constraint stands on the rule
  rather than on that evidence.

## Implementation

## Implementation

The work is ordered by dependency, because the retention change is inert until the
cycle can both start and survive.

First, readiness becomes progress-aware. The supervisor currently compares elapsed
wall time against a fixed budget and stops a child that exceeds it regardless of
whether that child is still recovering collections. It will instead treat observable
recovery progress as liveness, resetting its patience while progress continues and
falling back to a hard ceiling so a wedged child is still caught. The existing fixed
budget becomes that ceiling rather than the primary test. The ceiling is sized against
the slowest observed contended start rather than the fastest cold one, because the
research could not establish what drives the start-time variance and the cold-cache
explanation is contradicted by its own data.

Second, the cycle's failure isolation is brought up to what the parent contract already
specifies. The guards around the archive call, the pre-drop re-count, and the
active-job probe catch a type set that a transport timeout does not belong to, so a
timeout unwinds the cycle instead of deferring one namespace. Widening those guards to
the client's transport failures restores the specified skip-and-report behaviour. This
is remediation of an unimplemented clause, not a new capability.

Third, retention gains its third input. The orphan decision reads point count to pick
between an empty and a data window; it will additionally read ephemerality, already
available on the survey record, and select a new
`storage_autoprune_grace_hours_ephemeral` window when the root was temporary, defaulting
to 24 hours. Point count continues to select the tier *within* that choice, so an
ephemeral point-bearing namespace still archives before it drops; only the waiting
period changes. The live idle tier is untouched, leaving the two ephemeral paths
symmetric.

Fourth, `storage_autoprune_archive_max_gb` rises from 20.0 to 64.0 - roughly the 2.5x
the research derives as the cover for a full ephemeral drain plus the non-temp orphans
that follow it - so the reclamation does not evict the evidence it is writing. The
operator-facing archive surface additionally states that in-place restore is
unavailable on Windows and names the portable path.

Fifth, collection count and ephemeral backlog become reported quantities on the status
surface, so the growth this record is correcting is visible next time without a manual
audit.

Finally, the stale generation-suffix residue is disposed of through the existing
unreferenced-generation reclamation and the grace ledger is pruned of entries naming
collections that no longer exist, and the tests that reach the shared backend are
isolated to a temp storage directory so they stop seeding that residue.

## Rationale

## Rationale

The decisive fact is arithmetic rather than architectural: the research shows arrival
rate times window predicts the observed population to within the noise of a bursty
producer, so this is a steady state, not an accumulation of leaks. That rules out
every option framed as repairing the reaper and reduces the retention choice to which
term of the product to change. Lowering the window globally (O2) is rejected because
the seven days protect real repositories, which is the case the parent was written for
and which has not changed.

That leaves discriminating by class, and the evidence for the ephemeral class is
unusually strong: the root was created under the OS temp directory and is now provably
absent. The existing policy already trusts the weaker half of that pair -
temp-rootedness alone, with the directory still present - to authorise destruction
after 72 hours. Refusing to trust the stronger pair for seven days is an inversion, and
correcting it makes the two ephemeral paths consistent rather than introducing a new
licence to delete.

The window length is settled by effect size, not by symmetry. Symmetry alone would
argue for 72 hours, matching the live idle tier; the research's projection shows that
leaves roughly 114 collections against today's 138, a reduction too small to justify
the change. 48 hours reaches roughly 96. Only 24 hours, at roughly 79, materially
alters the situation, and it is chosen for that reason. It is not chosen because a day
absorbs a transient mount or share failure: that case never arises here, because an
absent root on an unreachable anchor classifies `unverifiable` rather than `orphaned`
and so never reaches this decision at all, and every measured temp root is anchored on
the system drive.

One consequence of the short window is accepted deliberately. At 168 hours the
distinction between elapsed time and continuous observation is immaterial; at 24 hours,
against an hourly cycle and a daemon that demonstrably spends real time down, a window
can be satisfied on relatively few confirming observations - and the namespaces
destroyed hold full repository indexes. The grace stamp persisting across restarts is
what makes this sound rather than reckless, since downtime can only ever extend the
elapsed window and never shorten it, but the reduced observation density is a real
change in the evidentiary basis and is owned here rather than left implicit.

The prerequisites are included because O1 alone would have changed nothing observable.
A retention window cannot drain a backlog if the daemon that evaluates it cannot start,
and cannot survive a cycle that unwinds on the first slow snapshot. Both were found
only on re-examination, and both are failures against contracts already accepted rather
than new ground.

The two rejections that matter most share a principle. O3 and O8 are the two ways to
make the backlog drain faster by giving up a safety property - one abandons
recoverability, the other lets a population statistic authorise a drop. Throughput here
is bought with headroom, isolation, and reporting, never by lowering the bar for
destruction. O10 is deferred on plainer grounds: at 16 reclaims per cycle and 24 cycles
a day, existing capacity exceeds both the arrival rate and the one-time backlog by more
than an order of magnitude, so it would buy nothing the current cap does not already
deliver - and deferring it is what lets this record's claim to reverse no gate stand
unqualified.

## Consequences

The ephemeral class constitutes the large majority of orphaned collections, so the
steady-state population falls substantially - but only partially. The research derives
a steady state near 79 collections rather than the 34 live ones, because deleted git
worktrees are not ephemeral and keep the long window. That is a material reduction in
handle pressure and recovery time, not an elimination of the problem, and the honest
framing is that this record buys headroom rather than solving collection sprawl.

The first cycle after landing is a burst, not a trickle: the whole ephemeral backlog
becomes eligible at once and drains at the per-cycle cap over several cycles. That is
intended, and the archive headroom exists to keep it from destroying its own evidence
while it happens. That headroom is bought with disk on a host already under storage
pressure, and it is a transitional cost: once the backlog clears, steady-state archive
turnover falls back to the arrival rate and the raised cap is mostly unused headroom.

A real risk is accepted knowingly. Any namespace whose legitimate root lives under the
OS temp directory now gets a materially shorter window. Every gate still applies and
the archive still precedes any point-bearing drop, so the outcome for a misclassified
namespace is an archive rather than loss - but on Windows that archive is not
restorable in place, which weakens the mitigation on the very host that surfaced this.
Ephemerality also remains inferred from a path convention, which is a heuristic; the
registration affordance deferred by `2026-07-14-storage-namespace-hygiene-adr` remains
the principled successor and this record strengthens its case.

The readiness change carries its own hazard in the opposite direction: a child that
fails slowly rather than wedging outright will now be tolerated longer before being
stopped, which is why the hard ceiling remains.

Nothing here changes the collection-per-repo shape, so the upstream-recommended
payload-partitioning migration (O11) stays open and stays necessary if the store is
ever expected to hold many hundreds of roots. This record buys the headroom to make
that decision deliberately instead of under resource pressure.
