---
tags:
  - '#audit'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:59312dc8ea9f36c61732d77749127c2924d747564cf3a80f360c86a7c8360bce'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-adr]]"
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
  - "[[2026-09-08-qdrant-collection-sprawl-research]]"
---

# `qdrant-collection-sprawl` audit: `retention discrimination and its prerequisites`

Verdict: **accept with changes**. Two high findings must be closed before merge. No
critical safety violation was found, and that conclusion rests on tracing each
invariant through the code rather than on the guard tests asserting they hold.

Scope: all 32 commits on the feature branch since the merge base, 3604 insertions
across 62 files, audited against the accepted decision record, its parent contract, the
32-step plan and the 32 execution records. The storage, survey, reclamation, manifest,
supervisor, route and renderer modules were read in full, along with every added test.
The storage and supervisor unit suites were executed, 131 tests.

None of this has been exercised against a live store: the managed server was down for
the duration of the campaign.

## Findings

## Scope

All 32 commits on the feature branch since the merge base, 3604 insertions across 62
files, audited against the accepted decision record, its parent contract, the 32-step
plan and the 32 execution records. The storage, survey, reclamation, manifest,
supervisor, route and renderer modules were read in full, along with every added test.
The storage and supervisor unit suites were executed, 131 tests.

A second round re-reviewed the ten remediation commits, and a third closed what that
round found. Nothing in any round has been exercised against a live store: the managed
server was down throughout.

## Findings

### The cycle still unwinds on a slow server - high

## What was checked and found sound

Recorded so it is not re-investigated. Archive-before-destroy holds: a failed archive
returns before the drop is reached, and the archive verifier raises on a missing
snapshot name, a missing or empty artifact, an unreadable or malformed manifest, and
any point movement between archive and verification. An unverifiable count is never
read as a number anywhere. An unverified namespace is forced to the protective tier and
in fact returns pending before the tier is consulted at all, which is stronger than the
decision record claims. The distinction between an absent count and an attempted one
that failed is preserved at every consumer. The never-observed sentinel genuinely
closes the hole it was written for: a partial sum can never become the baseline a later
complete count agrees with. Unknown and unverifiable namespaces are unreachable by both
tiers, and the drop path independently re-checks manifest membership and the canonical
prefix shape. The liveness probe now defers under its own distinct reason. The
per-cycle cap is unchanged and shared, not widened.

The reporting surface authorises nothing: the new totals are computed in one payload
shaper, read only by the renderer, and reach no window, tier, cap or gate. The deferred
option really is deferred.

One predicate, one tier rule, one window-selection site; no shim, no re-export, no
test-only symbol left alive. The two claims that a cycle continues past a failure are
real - both assert a positive outcome for the namespace queued behind the failure, with
ordering pinned so the failing one is provably reached first. The readiness wait cannot
wedge or spin: its ceiling is computed once at entry and checked every iteration, and
the progress counter is single-writer and monotonic. No development metadata reached
source, tests, configuration or user-facing documentation.

## Actions

## Recommendations

All findings above were remediated and re-reviewed. The first round closed three of
four: the readiness deadline, the zero-length window and the post-archive reason. It
left the transport class partially closed and introduced one new high finding of its
own, both caught on re-review and since closed.

The transport class was too narrow for the class it named. It covered a server that
could not answer and not one that answered with an error, so a non-2xx status on the
drop loop reproduced the original finding through a different exception type. It now
catches the client's own hierarchy while a programming error still escapes, and a guard
test faults the drop at that ambiguous member rather than only at the unambiguous one.

The new finding was subtler and mattered more. The retry the first round designed as
the answer to a partial drop rebuilt the snapshot manifest from the surviving
collections alone, orphaning the artifact taken of the half already destroyed - so the
archive held the data and the restore could not find it, reporting a partial recovery
as complete. A re-archive now merges into the manifest already on disk, a restore
refuses an archive directory holding artifacts its manifest does not name, and the
archive leaves the directory holding exactly what its manifest names. Remediating that
pair introduced a third defect - an archive raising after moving one snapshot left an
otherwise complete archive unrestorable - which was found and closed in the same round.

A partial drop now narrows the namespace's recorded collections to what survived and
carries the destroyed names onto its outcome, so the manifest stops claiming what is
gone and an operator learns which half to intervene on.

Two gates this campaign broke in its own earlier steps were also closed: two status
renderers with identical bodies, merged behind one implementation rather than exempted,
and a generated CLI reference left stale by a help-text change, regenerated from the
live command tree. Both were missed because the step that introduced them ran a gate
set that did not include the check that catches them.

Still open by decision rather than oversight: the orphan window measures elapsed time
rather than confirming observations, which belongs to a follow-on record; the survey's
own collection listing is the last unguarded call on the cycle, fail-closed; and the
reconciliation path still catches broadly where a narrower shared class now exists.

Run the reclaim evaluation read-only against the real backend before the first live
cycle and confirm every temp-rooted orphan reports the ephemeral window; the first cycle
after landing is a burst by design.
