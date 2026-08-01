---
tags:
  - '#audit'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:f5356c22926b0e47c8409d36ae6c5480dc83c98493da54b4657480259d316b03'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
  - "[[2026-07-25-storage-conformance-adr]]"
---

# `storage-conformance` audit: `closing review`

## Scope

The delivered feature against its authorizing decision, decision by decision, and
against its own plan verification criteria. Read the eight implementation
decisions in the record and located each in the tree: the stamp site, the ensure
seam, the verdict evaluator, the manifest preserve, the copy carry, the health
author, the remediation registry, and the survey payload. Also re-ran the gate
set, because the earlier closing gate run reported a clean sweep the complexity
gate contradicts.

## Findings

### stamp-and-verify-seam | low | seven of the eight decisions are implemented where the record put them

Identity is stamped inside the collection create and nowhere else, from the width
the collection was actually built with rather than from live config. Verification
sits on the ensure path after the index reconcile, behind the same
once-per-collection marker, so the live geometry read never reaches the query
path. Three verdicts exist, with absent evidence reported as the unknown it is.
Geometry disagreement raises and model disagreement does not. Recording a root
preserves the stored generation and identity instead of overwriting them. The
copy now carries provenance. The health author owns the degraded reason and the
remediation registry pairs it with a rebuild command. Each was read, not
inferred.

### survey-reports-a-model-not-a-verdict | medium | the survey payload carries the stamped dense model, and neither the verdict nor the rest of the identity

The decision asks for the per-namespace verdict and stamped identity in the
storage survey payload. What shipped is a map of collection name to stamped dense
model. The verdict is absent, and so are the sparse model, width, distance,
vector names, and schema generation the record enumerates. This is the one plan
verification criterion not met, and the Step that owned it is closed, so it would
otherwise pass unremarked.

The gap is not an oversight to patch in place. A verdict needs the live geometry
read, and the record constrains that read to sit behind the ensure cache; the
survey classifies from collection names and the manifest and holds no store
instance, so computing a verdict there would mean a second live read on a path
the record deliberately kept free of one. The daemon already holds the cached
verdicts - the health rollup reads the nonconforming list from them - so the
join is available without a new probe. That join is a seam this feature did not
open.

### nonconforming-search-not-exercised | low | readability is proven by a successful open, not by a search returning results

The criterion states that a search against a nonconforming collection still
returns results. What is proven is that the store opens, the verdict is recorded,
and no exception is raised - which is the mechanism, and is the part a regression
would break first. No test issues a query against a collection carrying a
nonconforming verdict and asserts a non-empty result. The claim is very probably
true and is currently an inference.

### complexity-gate-was-red-from-the-first-commit | medium | a gate this feature broke was recorded as clean

Identity parsing was added inline to the manifest loader in this feature's first
implementation commit, pushing its cognitive complexity past the gate threshold.
The gate has failed on every commit since. The closing gate step recorded ruff,
type, and citation gates clean and did not run the complexity gate, so the
regression survived a step whose entire purpose was to catch it. The narrower
lesson is that a closeout enumerating gates by name will keep missing the one it
does not name.

Correction, on a later reading of the trunk: this review first recorded the fix
as its own. It is not. The same extraction had already landed on the trunk,
diagnosed identically down to the 24-against-20 figure, and better factored -
four named field decoders with the loop body reduced to the drop-or-keep
decision, against the two helpers written here. The duplicate has been collapsed
onto the trunk's version and this branch now carries none of it; what remains
true is the finding, not the credit. The trunk's author is not identified here:
every worker commits under one name, so authorship does not disambiguate, and
naming a guess would be worse than naming nobody.

### duplicate-written-against-a-stale-trunk | medium | the fix was already public on the trunk twenty-five minutes before the duplicate was committed

The timestamps settle what this first looked like and what it actually was. The
branch point is 08:59. The trunk's extraction landed at 09:57. The duplicate was
committed here at 10:22. This was therefore not two workers invisible to each
other, which is what the first version of this finding claimed: the work being
duplicated was public, on the trunk, for twenty-five minutes beforehand, and one
log of the file about to be edited would have surfaced it.

The process failure is narrow and worth naming precisely. The trunk was read once
at the start of the session, to rebase off a stale branch, and then never read
again before code was added. On a trunk moving at this rate that snapshot was an
hour stale by the time it was relied on. Searching before writing is the standing
obligation, and it was honoured against the wrong revision, which is
indistinguishable from not honouring it at all.

The general case is worse than the cost here, which was one mechanical collapse.
A duplicate found at the merge presents as a content conflict in a file both sides
touched for unrelated reasons, and the side that merges cleanly wins - a question
with nothing to do with which implementation is better. This one surfaced only
because a concurrent worker was asked directly what they had built, and then only
because they denied authorship and the timestamps were checked.

### reclamation-criterion-would-be-a-defect-if-honoured | medium | a verification criterion asks for behaviour that would leak disk without bound

The plan requires that a namespace stamped before this feature existed is never
treated as a reclamation candidate. Every namespace on every host is unverifiable
on first upgrade, and an orphaned namespace's root is by definition gone, so it
can never be rebuilt into a stamp. Honouring the criterion literally would exempt
the entire pre-upgrade population from reclamation permanently. The authorizing
decision makes only the weaker claim - that an unverifiable verdict never
authorises destruction - which is satisfied, because reclamation is authorised by
reachability and a persisted grace window and reads no verdict at all. Two
classifications share the word and mean different things; the invariant that only
reachability is an input is now stated at the evaluator and guarded in both
directions. Recorded as a divergence from the plan rather than resolved silently.

### guard-obligation-discharged | low | every guard added by this phase has a recorded failure proof

Ten mutations across nine guards, each observed failing on the assertion its own
docstring names, restored, and re-run green. Two were rejected on first pass
because the failure arrived as a lookup error rather than an assertion, and the
tests were tightened rather than accepted. The fixtures name models no running
configuration produces, so a mutation that substitutes current values cannot
accidentally satisfy them.

### timing-sensitive-integration-under-load | medium | the second closeout in a row settled a load-induced integration failure

An unwaited-reconcile test failed twice with an HTTP read timeout when its whole
file ran on a machine saturated by concurrent work, and passed alone in four
seconds and as its own six-test group in a minute. Its code path reads no
manifest, and the test predates this branch, so nothing in this phase's diff is
reachable from it. Settled as load-induced.

The finding is not that test. It is that this is the second consecutive closeout
of this feature to spend effort distinguishing a load-induced integration failure
from a regression, on a different test each time. The suite spawns a real server
per integration test, and several assertions are about timing rather than about
values, so the failure mode is structural and will recur. Each occurrence costs a
full investigation, and the cheap wrong answer - calling it a flake without
evidence - is how a real intermittent defect eventually gets buried.

### debris-prune-would-destroy-a-quarantine-dir | medium | one caller passing the storage root turns an archive-free delete loose on quarantined data

Surfaced by a concurrent worker and verified here. The debris survey takes a
directory argument and reports every child directory the live server does not
list; the debris prune then removes each with a recursive filesystem delete and no
archive, reasoning in its own docstring that unloadable debris cannot be
snapshotted. Both are correct for the collections directory, which is what all
four production callers pass today.

They are wrong for the storage root. A quarantine directory sits at the root, has
no collection config, and is never listed by the server, so it satisfies the
debris predicate exactly. A caller passing the root - a plausible mistake, because
the parameter is named for the storage directory and typed only as a path - would
hand an archive-free recursive delete to the one directory whose entire purpose is
to hold data set aside for an operator to inspect. That is a direct
archive-before-destroy violation, against data the system deliberately preserved.

Not reachable today: every production caller funnels through the collections-dir
accessor, and the survey's own child filter skips files, which is what keeps the
adjacent store-format stamp invisible to it. The hazard is that nothing in the
signature or the tests holds that invariant, and concurrent work is making
quarantine directories both more common and more visible.

## Recommendations

Join the daemon's cached conformance verdicts into the storage survey payload,
and widen the reported identity from the dense model to the whole stamped record.
This is architecturally significant and needs its own decision: the question is
which component owns the join between a per-store-instance verdict cache and a
manifest-derived survey, and what a survey should report for a namespace no store
instance in this process has ever ensured. Until that lands, the survey's
provenance column should be read as "what produced this" and never as "whether
this may be trusted".

Add one test that searches a collection carrying a nonconforming verdict and
asserts a non-empty result, so the availability half of the geometry-refuses
model-degrades split is asserted rather than inferred.

Make the closeout gate step run the project's gate set rather than an enumerated
subset, so a gate absent from the list cannot be reported clean by omission.

Give a red shared gate a single owner before anyone fixes it. A gate failing on
every commit is visible to every concurrent worker at once and reads to each as
theirs to clear, which is one half of what produced a fix twice here. The cheap
form is a claim recorded where the other workers will see it; where that is
belongs to whoever owns the concurrency model, not to this feature.

Re-read the trunk immediately before adding code to a file, not once at the start
of a session. That is the other half, and it is the half that was in this
feature's control: the duplicate was avoidable by one log of one file. A
session-start rebase establishes a base to work from, not a licence to treat that
revision as current for the session's duration.

Constrain the debris survey so the storage root cannot be passed to it - either
narrow the parameter to a collections directory the caller must obtain from the
existing accessor, or have the survey refuse a directory containing a quarantine
entry. Prefer whichever the module's current owner is not mid-refactor on. A name
based skip of `quarantine` alone would be the cheapest change and the weakest,
because it protects one known directory rather than the invariant that the
argument is a collections directory. Deliberately not implemented here: the module
is under concurrent edit, the path is unreachable today, and choosing between
those two shapes is a decision about that function's contract rather than a fix
belonging to this feature.

Reconcile the plan's reclamation verification criterion with the decision it
implements, so the plan stops asking for behaviour the decision does not
authorise and a later reader does not implement the criterion as written.

Give the timing-sensitive integration assertions a tolerance that holds under
concurrent load, or mark them so they run on a quiet machine, so the next
closeout does not spend a third investigation on the same structural failure
mode. This needs its own decision: whether the project treats a saturated
developer machine as a supported test environment, and if so which assertions are
allowed to be about timing at all.
