---
tags:
  - '#plan'
  - '#non-destructive-index-publication'
date: '2026-07-25'
modified: '2026-07-25'
tier: L2
related:
  - '[[2026-07-25-non-destructive-index-publication-adr]]'
  - '[[2026-07-25-non-destructive-index-publication-research]]'
  - '[[2026-07-25-index-completeness-guard-adr]]'
---

# `non-destructive-index-publication` plan

## Description

Executes `2026-07-25-non-destructive-index-publication-adr`, grounded in
`2026-07-25-non-destructive-index-publication-research`. One ADR governs every
Phase.

A rebuild currently destroys the index it is replacing before it has a
replacement, and an unattended incremental escalates itself into that rebuild.
`P01` stops the unattended destruction immediately, accepting a named degraded
regime. `P02` through `P04` build the decided design - generation-scoped
collections behind one resolved pointer, admitted by headroom and reclaimed by
maintenance - and `P05` removes the `P01` compromise once that design serves its
purpose.

The interim mitigation in `P01` is a mitigation with a stated defect, not a
fallback. Landing `P01` without `P05` leaves the tree in a knowingly-degraded
state, so the plan is not complete at any point before `P05` closes.

## Steps

### Phase `P01` - stop unattended runs destroying served data

Close the production window first. The two escalation gates reachable from a watcher-driven incremental stop calling the destructive rebuild and take failure-safe reconciliation instead, with the superseded-regime condition made visible rather than silent. This ships a knowingly-degraded retrieval regime whose defect the decision names; it is removed by the later phases, not retained as a fallback.

- [x] `P01.S01` - Route the embed-format and config-drift escalation gates to failure-safe reconciliation so no watcher-driven run reaches a destructive rebuild; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `P01.S02` - Record the superseded-regime condition when a gate escalates non-destructively, and carry it on the code search path beside the existing breadth shortfall; `src/vaultspec_rag/_index_breadth.py, src/vaultspec_rag/_search_state.py, src/vaultspec_rag/api.py`.
- [ ] `P01.S03` - Render the superseded-regime warning on the command-line search surface and carry the same fact in the search summary so an adapter without a renderer reports it; `src/vaultspec_rag/cli/_search.py, src/vaultspec_rag/server/_routes.py`.
- [x] `P01.S04` - Prove by real-storage test that an unattended incremental over a drifted config leaves the served point count intact, and that the same run under an explicit operator rebuild still drops the collection; `src/vaultspec_rag/tests/integration/test_index_job_control.py`.

### Phase `P02` - resolve served identity through one pointer

Readers stop deriving the served collection name from the root and resolve it through a single per-root pointer instead. Introduced while the pointer still resolves to today's name, so the indirection lands and is proven under the existing suite before any generation-scoped write depends on it.

- [ ] `P02.S05` - Introduce a per-root served-collection pointer in the store, persisted alongside the existing per-root identity, defaulting to today's derived name where absent; `src/vaultspec_rag/store.py`.
- [ ] `P02.S06` - Resolve every read path's collection name through the pointer rather than deriving it from the root, leaving write paths on the derived name for now; `src/vaultspec_rag/store.py, src/vaultspec_rag/_store_search.py`.
- [ ] `P02.S07` - Route the survey and storage-operation surfaces at the pointer so no caller outside the store derives a collection name for itself; `src/vaultspec_rag/cli/_service_storage.py, src/vaultspec_rag/server/_routes_storage.py`.
- [ ] `P02.S08` - Prove by real-storage test that a root whose pointer is absent resolves to the derived name unchanged, and that a root whose pointer names another collection is read from that collection; `src/vaultspec_rag/tests/integration/test_store_integration.py`.

### Phase `P03` - build a generation into its own collection and swap

A rebuild writes into a collection named for its generation and never reuses a name, so the served collection is untouched until the new one reconciles and records its breadth. Publication moves the pointer once. A failed or interrupted build leaves an unreferenced collection rather than a truncated served one.

- [ ] `P03.S09` - Name each rebuild generation's collection so a name is never reused, defeating the local-mode directory-survival behaviour on create; `src/vaultspec_rag/store.py`.
- [ ] `P03.S10` - Write a clean rebuild into its generation collection, leaving the served collection untouched for the duration of the build; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `P03.S11` - Move the pointer to the new generation only after its breadth is recorded, so a reader never resolves a collection that has not reconciled; `src/vaultspec_rag/store.py, src/vaultspec_rag/indexer/_run_checkpoint.py`.
- [ ] `P03.S12` - Prove by real-storage test that a rebuild interrupted mid-build leaves the previously served point count fully readable, and that the pointer still names the old collection; `src/vaultspec_rag/tests/integration/test_index_job_control.py`.

### Phase `P04` - admit by headroom and reclaim the superseded collection

Bound the peak-storage cost the swap introduces. A root that cannot afford the duplicate is refused visibly rather than silently rebuilding in place, and the superseded collection is dropped by ordinary read-and-drop maintenance once no reader holds it.

- [ ] `P04.S13` - Estimate the duplicate a generation build needs and refuse the build with a stated reason when headroom cannot cover it, never falling back to rebuilding in place; `src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/store.py`.
- [ ] `P04.S14` - Drop a superseded generation collection from read-and-drop maintenance once the pointer no longer names it and no reader holds it; `src/vaultspec_rag/storage_ops.py`.
- [ ] `P04.S15` - Prove by real-storage test that a refused build leaves the served index intact and reports the refusal, and that maintenance drops only collections the pointer does not name; `src/vaultspec_rag/tests/integration/test_storage_survey_service.py`.

### Phase `P05` - retire the interim mitigation

Remove the degraded-regime mitigation from Phase P01 once generation-scoped publication serves its purpose, and prove by test that an unattended gate now reaches the non-destructive publication path rather than either the old destructive rebuild or the interim compromise.

- [ ] `P05.S16` - Remove the interim superseded-regime mitigation and its reporting now that an unattended gate publishes non-destructively; `src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/cli/_search.py`.
- [ ] `P05.S17` - Prove by real-storage test that an unattended gate now reaches generation-scoped publication, reaching neither the destructive rebuild nor the interim compromise; `src/vaultspec_rag/tests/integration/test_index_job_control.py`.

## Parallelization

`P01` is independent of everything after it and lands first, because it is the
only Phase that changes production behaviour today. Its four Steps are ordered:
`P01.S01` changes the escalation, `P01.S02` records the condition it creates,
`P01.S03` renders it, `P01.S04` proves it.

`P02` through `P04` carry hard ordering and cannot be parallelized against each
other. A generation-scoped write (`P03`) is meaningless until served identity is
resolved through the pointer (`P02`), and reclamation (`P04`) cannot decide what
is unreferenced until the pointer is what confers reference. Within `P02`,
`S05` precedes `S06` and `S07`; within `P03`, `S09` precedes `S10` and `S11`.

`P05` closes the plan and depends on `P03` landing. It must not be deferred:
the plan is incomplete while the `P01` compromise remains in the tree.

The whole plan sequences behind the indexer seam in
`2026-07-25-index-resume-drift-race-adr`. `P01.S01`, `P03.S10`, and `P05.S16`
touch the class that decision is decomposing, so they land on the seamed
structure rather than beside it.

## Verification

- Every Step closed (`- [x]`), `P05` included.
- A real-storage test proves an unattended incremental over drifted config
  leaves the served point count intact, and that an explicit operator rebuild
  still drops the collection.
- A real-storage test proves an interrupted generation build leaves the
  previously served points fully readable and the pointer naming the old
  collection.
- A real-storage test proves a refused build leaves the served index intact and
  reports the refusal, and that maintenance drops only collections the pointer
  does not name.
- No caller outside the store derives a collection name for itself.
- Every guard test added by this plan is shown able to fail: the guard broken,
  the test observed failing on the assertion it names, restored, observed
  passing, both directions recorded where the next reader will find them.
- No test substitutes production behaviour. No fake, stub, mock, patch, or
  monkeypatch stands in for the path under test.
- Lint, format, and type gates green on every file the plan touches.
