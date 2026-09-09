---
tags:
  - '#audit'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:cb62877dfb292b534dc6a5538f4f107ca9444db6d835298c3ce2060a7d000549'
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

### The cycle still unwinds on a slow server - high

The transport-guard work widened five call sites and missed four more reached by the
same cycle over the same client, so the phase's stated prerequisite is delivered for
some paths and not the class.

`delete_prefix` catches only the builtin errors around its per-collection drop
(`src/vaultspec_rag/storage_survey_ops.py:419`), its own collection listing is unguarded
(`:403`), and the call into it from the apply path sits outside any guard
(`src/vaultspec_rag/storage_reclamation.py:815`). A transport timeout on the drop
therefore escapes the apply path, escapes the cycle, and is re-raised at the daemon's
maintenance tick. The namespace is left **partially deleted** with its manifest entry
intact and no outcome recorded, which is worse than a missed reclaim: it is destruction
without a record, on the one call that has already begun destroying by the time it
fails.

The generation pass carries the same hole twice
(`src/vaultspec_rag/storage_reclamation.py:1147` and `:1199`) and runs *before* the
orphan apply loop, so one slow generation call aborts the cycle before any orphan is
considered at all.

The reconciliation module already catches broadly at four sites, so the codebase was
inconsistent about this before the campaign; the campaign widened the guards it looked
at rather than the class of failure.

### The readiness change is invisible from the verb an operator types - high

The service start path hard-codes a 300 second readiness deadline
(`src/vaultspec_rag/cli/_service_start.py:142`), unrelated to the qdrant readiness knob
and never overridden at its only construction site. Before this campaign the two
numbers coincided. They no longer do: the daemon may now legitimately spend up to four
times the patience window inside the readiness wait alone, plus provisioning and model
load, while the command abandons at 300 seconds and reports a failure for a start that
then succeeds behind the operator.

The scenario that triggers it is exactly the one the campaign exists for - a large
store recovering slowly - and it means the plan's own verification clause, a cold start
completing without a truncated attempt, cannot be satisfied from the operator's entry
point.

### A zero ephemeral window authorises a same-cycle drop - medium

The new window is bound to a non-negative number, so zero is admissible, and at zero a
namespace becomes eligible in the cycle that first observes it - a single-scan
existence check authorising destruction, which the parent contract forbids by name.
The two older windows share the bound, but this is the class with the shortest fuse and
the largest population.

Compounding it, the adjacent live-tier knob *disables* its tier at zero while this one
makes its tier maximally aggressive. Two near-identically named knobs with opposite
meanings at the same value.

### The post-archive re-count reports the wrong reason - medium

After a successful archive the settle re-count is compared for inequality
(`src/vaultspec_rag/storage_reclamation.py:809`), so an unverifiable result defers under
a reason claiming the points changed. The outcome is safe and the reason is false. It
is the same conflation the campaign spent three steps and a dedicated guard test
removing elsewhere - the pre-drop gate argues at length that "a job is running" and
"nobody could check" are different facts - and this one site did not get the treatment.

### Further gaps, lower severity

The survey's own collection listing is unguarded while the count two lines below it is,
so the guard test's name claims more than the test proves; the failure is fail-closed.
A newly added supervisor ceiling test failed once under load and passed on nine
subsequent runs; both plausible mechanisms are the test's timing margins rather than
the code, and neither is a production risk at the shipped patience window. The reclaim
test suite writes the shared session manifest without per-test isolation, which is
cross-test bleed rather than operator exposure, the session fixture having already
redirected both directory knobs. The policy dataclass still carries the old archive cap
as its default while the shipped configuration carries the new one; only production
construction passes every field explicitly, so nothing is broken, but one default is
now stated twice. Four commits landed work outside the plan's steps - each defensible
in itself, none traceable to a step.

### The window measures elapsed time, not observations - medium

The orphan clock accrues wall-clock time, so daemon downtime counts toward the window.
At seven days that was immaterial. At twenty-four hours, with an hourly cadence, a
daemon down for most of a day can reclaim the whole ephemeral backlog on two
observations of full repository indexes.

The decision record owns the reduced observation density as an accepted risk, but its
stated mitigation argues the wrong way: the grace stamp persisting across restarts is
precisely what lets downtime count. The codebase already has the stronger primitive and
uses it for the sibling live tier, which requires agreement between consecutive
readings before it will act. The orphan ephemeral window does not.

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

Close both high findings before merge, and take the zero-window bound and the
post-archive reason in the same pass; both are small and both restate a principle the
campaign already established elsewhere. Run the reclaim evaluation read-only against
the real store before the first live cycle and confirm every temp-rooted orphan reports
the ephemeral window, because nothing here has met a live store and the first cycle
after landing is a burst by design. Whether the ephemeral orphan window should require
a minimum count of confirming observations rather than elapsed time is a decision for a
follow-on record.
