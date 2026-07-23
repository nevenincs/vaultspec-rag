---
tags:
  - '#plan'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
tier: L2
related:
  - '[[2026-07-23-document-chunk-bounding-adr]]'
  - '[[2026-07-23-document-chunk-bounding-research]]'
---

# `document-chunk-bounding` plan

Bound hook-emitted document units through the shared splitter with
collision-free fragment identity, and stop failing index jobs on retained
allocator pool.

## Description

Executes `2026-07-23-document-chunk-bounding-adr`, grounded in
`2026-07-23-document-chunk-bounding-research`. Two composing defects are
addressed: preprocess-hook-emitted document units are the only chunk class the
pipeline never size-bounds, and the CUDA ceiling guard enforces the caching
allocator's retained pool against the same ceiling as live demand.

`P01` closes the bounding gap at both the schema boundary and the chunking
path. `P02` makes fragment point identity unique and versioned, which is a hard
prerequisite for `P01` shipping: the failing corpus emits page locators, and
document identity ignores the unit ordinal whenever a locator is present, so
splitting without `P02` would give every fragment of one page the same id and
reproduce the duplicate-id abort. `P03` removes the reserved comparison from
ceiling enforcement. `P04` folds the new bound into the content epoch and
discharges the obligation that every guard test be observed failing for its
intended reason.

One condition outside this plan's scope bounded its execution: the resident
service runs a build predating these changes, so behavioural checks against the
running daemon rather than the test suite would mislead, and the completion
criteria are therefore drawn from the suite alone. An import break in the store
retry helper's rename also blocked the tree at authoring time and was resolved
independently before execution began.

## Steps

### Phase `P01` - bound the unit contract and split unit text

Close the gap that lets a hook-emitted unit reach the encoder unbounded, so every document chunk is size-bounded regardless of which field the hook populated.

- [x] `P01.S01` - add an explicit maximum length to the unit text field so the schema stops advertising an unbounded payload; `src/vaultspec_rag/indexer/_preprocess_schema.py`.
- [x] `P01.S02` - derive the character split budget from the dense model sequence window by a declared chars-per-token ratio instead of a literal; `src/vaultspec_rag/config.py`.
- [x] `P01.S03` - route hook-emitted unit text through the shared bounded splitter in the units branch; `src/vaultspec_rag/indexer/_chunk_worker.py`.
- [x] `P01.S04` - carry title, section, anchor, locator, and unit metadata onto every fragment produced from one unit; `src/vaultspec_rag/indexer/_chunk_worker.py`.
- [x] `P01.S05` - give the document splitter configuration a non-zero overlap so a fragment boundary does not sever context; `src/vaultspec_rag/indexer/_chunk_worker.py`.

### Phase `P02` - make fragment point identity unique and versioned

Extend the location component of document point identity so fragments of one locator-bearing unit cannot collide, and version the derivation change.

- [x] `P02.S06` - add a fragment discriminator to the location component so it applies to both the locator and unit-ordinal identity branches; `src/vaultspec_rag/indexer/_document_identity.py`.
- [x] `P02.S07` - bump the document identity version because the derivation changes for units that split; `src/vaultspec_rag/indexer/_document_identity.py`.
- [x] `P02.S08` - pass the fragment discriminator from chunk construction into point identity derivation; `src/vaultspec_rag/indexer/_chunk_worker.py`.
- [x] `P02.S09` - add a guard test driving a multi-page locator-bearing unit through the splitter and asserting every fragment id is distinct; `src/vaultspec_rag/tests/test_chunk_worker_parity.py`.
- [x] `P02.S10` - add a test asserting fragment ids are stable across a repeated run of an unchanged unit so ledger replay stays idempotent; `src/vaultspec_rag/tests/test_chunk_worker_parity.py`.

### Phase `P03` - stop enforcing retained allocator pool against the ceiling

Remove the reserved comparison from ceiling enforcement, keep reserved as a reported diagnostic, and make the per-job peak reset describe the job rather than the process history.

- [x] `P03.S11` - remove the reserved high-water comparison from ceiling enforcement leaving the allocated comparison as the sole gate; `src/vaultspec_rag/memory_probe.py`.
- [x] `P03.S12` - keep sampling and reporting reserved on job resilience records and metrics as a diagnostic; `src/vaultspec_rag/memory_probe.py`.
- [x] `P03.S13` - release the allocator cache immediately before rebasing peak counters so a job's peaks describe that job; `src/vaultspec_rag/memory_probe.py`.
- [x] `P03.S14` - update the budget class contract prose to state that allocated alone gates and reserved is reported; `src/vaultspec_rag/memory_probe.py`.

### Phase `P04` - epoch the bound and prove the guards fail

Join the new bound to the document content epoch so a bound change rebuilds, and demonstrate each guard test failing for its intended reason before trusting it.

- [x] `P04.S15` - fold the unit text bound and the splitting parameters into the document content epoch so a bound change triggers rebuild; `src/vaultspec_rag/indexer/_config_epoch.py`.
- [x] `P04.S16` - prove the fragment-id uniqueness guard fails against the pre-fix identity construction and record both directions; `src/vaultspec_rag/tests/test_chunk_worker_parity.py`.
- [x] `P04.S17` - prove the unit text maximum-length rejection fails when the bound is removed and record both directions; `src/vaultspec_rag/tests/test_preprocess_schema.py`.
- [x] `P04.S18` - add a test asserting a unit above the token window yields multiple fragments rather than one truncated chunk; `src/vaultspec_rag/tests/test_chunk_worker_parity.py`.
- [x] `P04.S19` - add a test asserting a reserved high-water above the ceiling no longer fails a job while an allocated high-water above it still does; `src/vaultspec_rag/tests/test_job_resilience.py`.
- [x] `P04.S20` - run the full unit suite and the citation-gate lint over every changed file; `src/vaultspec_rag/tests`.

## Parallelization

`P03` is fully independent of `P01`, `P02`, and `P04` - it touches only the
memory budget and shares no file with them - and may run in parallel with the
whole chunking line.

`P01` and `P02` carry hard ordering against each other but not in the obvious
direction: `P02.S06` and `P02.S07` must land before `P01.S03` is exercised,
because splitting a locator-bearing unit without a fragment discriminator emits
colliding ids. The safe sequence is to land the identity change first, then the
splitting. `P01.S01` and `P01.S02` are independent of that ordering and may run
at any time.

`P04.S15` and `P01.S02` are coupled and were landed together: the bound must be
covered by the document-kind policy fingerprint before it is allowed to change,
or a bound change re-fragments every hook-backed corpus with no rebuild trigger
and strands points written under the previous bound.

`P04.S16` through `P04.S19` each depend on the step whose guard they prove and
must not be started before it. `P04.S20` is last by construction.

## Verification

The plan is complete when every Step is closed and each criterion below holds.

- A hook-emitted unit whose text exceeds the derived bound yields more than one
  fragment, and the concatenated fragment text preserves the unit's content -
  demonstrating the silent-truncation defect is gone rather than relabelled.
- Every fragment of one locator-bearing unit carries a distinct point id, and a
  commit unit built from them is accepted by the ledger.
- Re-running an unchanged hook-backed file produces byte-identical fragment ids,
  so incremental replay stays idempotent.
- The unit schema rejects text above its declared maximum, and that rejection is
  observed failing when the bound is removed.
- A simulated reserved high-water above the ceiling no longer fails a job, while
  a simulated allocated high-water above it still does.
- Each guard test in `P04` has been observed failing for its intended reason and
  then passing, with both directions recorded in the Step Record.
- The full unit suite passes and the citation-gate lint reports no development
  record named in any changed source file.

One criterion is deliberately excluded. Confirming the resident service stops
emitting `cuda_memory_ceiling` is not a completion condition, because the
running daemon predates these changes; that observation belongs to a separate
redeploy and reconciliation, not to this plan.
