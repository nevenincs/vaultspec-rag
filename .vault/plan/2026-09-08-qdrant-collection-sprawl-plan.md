---
tags:
  - '#plan'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
tier: L2
related:
  - '[[2026-09-08-qdrant-collection-sprawl-adr]]'
  - '[[2026-09-08-qdrant-collection-sprawl-research]]'
  - '[[2026-07-14-storage-autoprune-safety-adr]]'
modified: '2026-09-08'
body_schema: body-v2
body_hash: 'sha256:4660586e121c7e8bb90daa568fa13290aab4a54cf33d9a0f68ba5ce5af505c37'
---

# `qdrant-collection-sprawl` plan

## Description

## Description

Executes `2026-09-08-qdrant-collection-sprawl-adr`, grounded in
`2026-09-08-qdrant-collection-sprawl-research`, extending the reclamation contract of
`2026-07-14-storage-autoprune-safety-adr` without reversing any of its gates.

The work is ordered by dependency rather than by value, because the headline change is
inert on its own. Phase `P01` restores the maintenance cycle's ability to run at all:
the daemon can fail to start at the current collection count, and the reaper has only
one caller inside that daemon, so a readiness budget that tolerates a live, progressing
child is a precondition for everything after it. The same Phase closes the guard holes
that let one slow snapshot unwind an entire cycle, which the parent contract already
requires to be a per-namespace skip.

Phase `P02` is the decision itself: an orphaned temp-rooted namespace draws its own
short window rather than the full data window, so ephemerality survives teardown
instead of being discarded at the moment it becomes best-evidenced. Point count still
selects the tier within that choice, so an ephemeral point-bearing namespace continues
to archive before it drops. Its guard Steps exist because a shorter window is only safe
while every other gate holds, and each must be proven capable of failing.

Phase `P03` sizes the archive for the drain the retention change triggers, since the
whole ephemeral backlog becomes eligible on the first cycle and would otherwise evict
the recovery evidence it is writing; it also states the platform restore limitation
plainly and surfaces the collection count so this growth is visible next time without a
manual audit. Phase `P04` disposes of the superseded generation-name residue and stops
our own tests seeding namespaces into the operator's real backend.

## Steps

### Phase `P01` - restore the maintenance cycle's ability to run and survive

Delivers the two prerequisites without which no retention change executes: a readiness budget that tolerates a live, progressing qdrant child, and failure isolation so one slow snapshot defers a single namespace instead of unwinding the whole cycle.

- [x] `P01.S01` - Make the qdrant readiness wait treat observable recovery progress as liveness, keeping the existing fixed budget as a hard ceiling; `src/vaultspec_rag/qdrant_runtime/_supervise.py`.
- [x] `P01.S02` - Add a guard test proving a child still recovering collections survives past the old fixed budget; `src/vaultspec_rag/tests/test_qdrant_supervise.py`.
- [x] `P01.S03` - Add a guard test proving a wedged child making no progress is still stopped at the hard ceiling; `src/vaultspec_rag/tests/test_qdrant_supervise.py`.
- [x] `P01.S04` - Widen the archive-call guard to catch the qdrant client transport failures so a snapshot timeout marks one namespace failed; `src/vaultspec_rag/storage_reclamation.py`.
- [x] `P01.S05` - Widen the pre-drop re-count guard to catch the qdrant client transport failures so a timeout defers that namespace; `src/vaultspec_rag/storage_reclamation.py`.
- [x] `P01.S06` - Widen the active-index-job probe guard to catch the qdrant client transport failures; `src/vaultspec_rag/storage_reclamation.py`.
- [x] `P01.S07` - Add a guard test proving a snapshot read timeout marks that namespace failed and the cycle continues to the next candidate; `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`.
- [x] `P01.S08` - Add a guard test proving a re-count read timeout defers the namespace rather than aborting the cycle; `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`.
- [x] `P01.S27` - Widen the survey-time point-count guard so a transport timeout leaves that collection uncounted rather than unwinding the survey and the cycle with it; `src/vaultspec_rag/storage_survey_ops.py`.
- [x] `P01.S28` - Carry an uncountable collection through the survey as unverifiable rather than as zero points, so a failed count cannot mis-tier a data-bearing namespace as empty; `src/vaultspec_rag/storage_survey_ops.py`.
- [x] `P01.S29` - Guard the collection enumeration in the pre-drop re-count so a transport timeout yields an unverifiable count instead of escaping; `src/vaultspec_rag/storage_reclamation.py`.
- [x] `P01.S30` - Return an unverifiable result from the active-index-job probe so a registry read failure defers the namespace instead of reporting no job busy; `src/vaultspec_rag/storage_reclamation.py`.
- [x] `P01.S31` - Add a guard test proving a survey-time transport timeout leaves the maintenance cycle running and the namespace unreclaimed; `src/vaultspec_rag/tests/test_storage_survey.py`.
- [x] `P01.S32` - Add a guard test proving an unverifiable active-job probe defers the namespace rather than authorising the drop; `src/vaultspec_rag/tests/test_storage_safety.py`.

### Phase `P02` - discriminate retention by namespace class

Delivers the core decision: an orphaned temp-rooted namespace draws its own short window instead of the full data window, so ephemerality survives teardown.

- [x] `P02.S09` - Add the ephemeral-orphan grace window as a configuration default alongside the existing autoprune knobs; `src/vaultspec_rag/config/_settings.py`.
- [x] `P02.S10` - Add the ephemeral-orphan window field to the reclaim policy with its documented default; `src/vaultspec_rag/storage_reclamation.py`.
- [x] `P02.S11` - Select the ephemeral window in the orphan decision when the namespace root was temp-rooted, keeping point count as the tier selector; `src/vaultspec_rag/storage_reclamation.py`.
- [x] `P02.S12` - Thread the configured ephemeral window into the policy the maintenance tick constructs; `src/vaultspec_rag/server/_lifecycle.py`.
- [x] `P02.S13` - Add a test proving an orphaned temp-rooted point-bearing namespace draws the ephemeral window, not the data window; `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`.
- [x] `P02.S14` - Add a test proving an orphaned non-temp point-bearing namespace still draws the full data window; `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`.
- [x] `P02.S15` - Add a guard test proving the ephemeral window does not bypass the archive-before-destroy gate; `src/vaultspec_rag/tests/test_storage_safety.py`.
- [x] `P02.S16` - Add a guard test proving the ephemeral window does not bypass the pre-drop point re-count; `src/vaultspec_rag/tests/test_storage_safety.py`.
- [x] `P02.S17` - Add a guard test proving an unknown or unverifiable namespace is still never reached by the ephemeral path; `src/vaultspec_rag/tests/test_storage_safety.py`.

### Phase `P03` - size the archive for the drain and report the growth

Delivers the headroom that stops the drain evicting its own recovery evidence, states the platform restore limitation honestly, and surfaces collection count so this growth is visible without a manual audit.

- [ ] `P03.S18` - Raise the archive size cap default so a full ephemeral drain does not evict the evidence it writes; `src/vaultspec_rag/config/_settings.py`.
- [ ] `P03.S19` - State the unavailable in-place restore and name the portable recovery path on the operator-facing archive surface; `src/vaultspec_rag/cli/_service_storage.py`.
- [ ] `P03.S20` - Report total collection count and the ephemeral backlog size on the storage status route; `src/vaultspec_rag/server/_routes_storage.py`.
- [ ] `P03.S21` - Render the reported collection count and ephemeral backlog in the status output; `src/vaultspec_rag/cli/_status_render.py`.
- [ ] `P03.S22` - Add a test covering the reported collection count and ephemeral backlog fields; `src/vaultspec_rag/tests/integration/test_storage_survey_service.py`.

### Phase `P04` - dispose of residue and stop seeding it

Delivers cleanup of the superseded generation names and stale ledger entries, and isolates the tests that were writing namespaces into the operator's real backend.

- [ ] `P04.S23` - Drop grace-ledger entries naming collections that no longer exist when the ledger is next written; `src/vaultspec_rag/generation_stamps.py`.
- [ ] `P04.S24` - Add a test proving ledger entries for absent collections are pruned and live entries are preserved; `src/vaultspec_rag/tests/test_generation_survey.py`.
- [ ] `P04.S25` - Point the qdrant storage-dir at a temp path in the storage-ops tests that reach the managed backend; `src/vaultspec_rag/tests/test_storage_ops.py`.
- [ ] `P04.S26` - Point the qdrant storage-dir at a temp path in the storage-survey tests that reach the managed backend; `src/vaultspec_rag/tests/test_storage_survey.py`.

## Parallelization

## Parallelization

Phase `P01` is a hard serialization point and runs alone. Its readiness Step gates
every later Step's ability to be exercised against a running service, and its three
guard-widening Steps all edit one module, so they run in sequence rather than
concurrently.

Within `P02`, the configuration default and the policy field can proceed together, but
the decision-function change depends on both, and the four test Steps depend on the
decision function. `P03` is independent of `P02` once `P01` has landed - the archive
cap, the operator wording, and the status reporting touch disjoint modules and may run
in parallel with each other. `P04` is independent of everything except `P01` and may
run alongside `P03`.

The two Steps that must never overlap are the archive cap raise and any Step that
triggers a drain, because sizing the archive after the drain begins defeats its
purpose.

## Verification

## Verification

Each guard Step is verified by the discipline the guard tests demand: break the guard,
run that test alone, watch it fail on the assertion it names, restore, watch it pass -
one uninterrupted sequence, with no mutation left on disk. That applies to the
readiness ceiling test, the two transport-timeout isolation tests, and the three
`P02` gate tests, which are the Steps where a passing test would otherwise prove only
that nothing crashed.

Beyond the test suite, the retention change is verified against the live store rather
than asserted. Before landing, the reclaim evaluation is run read-only and its
per-namespace decisions inspected: every temp-rooted orphan should report the ephemeral
window and every non-temp orphan the unchanged data window. After landing, the first
maintenance cycles are checked for the predicted shape - a burst bounded by the
per-cycle cap, archives written before each point-bearing drop, and a declining
collection count - and the count is confirmed to settle near the derived steady state
rather than at the live-worktree count, which would indicate the non-temp orphans were
wrongly swept.

The readiness change is verified by a cold start at the current collection count
completing without a truncated attempt, and the isolation change by confirming a cycle
that encounters a slow snapshot reports one failed namespace and a nonzero count of
others processed.

Lint, format, type-check, and the tests covering each touched module run before every
commit, with each gate's exit code captured on its own.
