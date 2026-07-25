---
tags:
  - '#plan'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
tier: L3
related:
  - '[[2026-07-25-index-resume-drift-race-adr]]'
  - '[[2026-07-25-index-drift-circuit-accounting-adr]]'
  - '[[2026-07-25-document-index-drift-parity-adr]]'
  - '[[2026-07-25-index-resume-drift-race-research]]'
  - '[[2026-07-21-large-index-resilience-adr]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

# `index-resume-drift-race` plan

## Wave `W01` - Seam the codebase indexer

Extract the responsibility clusters that one 3601-line class currently holds, behaviour-preserving, with the existing suite as the only oracle. Extraction runs ahead of the fix so the drift owner has somewhere to live that is not a seventh concern in the monolith.

### Phase `W01.P01` - Establish the extraction baseline

Fix the behavioural oracle and prove the seams are not carrying duplicate implementations across.

- [x] `W01.P01.S01` - Capture the behavioural baseline: run the full suite and record the passing count and the per-module test inventory that the extractions must preserve; `src/vaultspec_rag/tests/`.
- [x] `W01.P01.S02` - Sweep the indexer for duplicate behaviour with vaultspec-rag semantic search before any extraction, recording each duplicate pair so extraction collapses it rather than carrying both across the seam; `src/vaultspec_rag/indexer/`.
- [x] `W01.P01.S15` - Cover the drift-detection predicate with direct tests before it moves across a seam, since it currently has no test of its own and only its remedy is exercised; `src/vaultspec_rag/indexer/_run_checkpoint.py`.
- [x] `W01.P01.S16` - Repair the test construction pattern that bypasses the indexer constructor, so a collaborator can be held as constructor state instead of rebuilt per access; `src/vaultspec_rag/tests/test_indexer_unit.py`.

### Phase `W01.P02` - Extract the collaborators

One extraction per responsibility cluster, each landing green before the next begins.

- [x] `W01.P02.S03` - Extract discovery and admission into its own collaborator, grounding first with vaultspec-rag semantic search and citing what it returned; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W01.P02.S04` - Extract chunk production and submission into its own collaborator, grounding first with vaultspec-rag semantic search and citing what it returned; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W01.P02.S05` - Extract generation and ledger lifecycle into its own collaborator, grounding first with vaultspec-rag semantic search and citing what it returned; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `W01.P02.S06` - Extract drift ownership into its own collaborator that holds the drop-points-then-remove-units ordering as a property of the type; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `W01.P02.S17` - Collapse the duplicated stat-failure classification so an admitted file is stat-ed once per scan rather than twice, treating it as the behaviour change it is; `src/vaultspec_rag/indexer/_content_discovery.py`.

## Wave `W02` - Give drift a single owner and close the window

Turn the ledger collision into a distinguishable signal and let the drift owner supersede and re-record the racing path, so detection and remedy reason over the same evidence at the same instant.

### Phase `W02.P03` - Make the collision legible

Distinguish a racing path from a genuine invariant breach at the type level.

- [x] `W02.P03.S07` - Give the indexed-path upsert collision its own exception type so a racing path is distinguishable from a genuine invariant breach; `src/vaultspec_rag/indexer/_run_ledger.py`.
- [x] `W02.P03.S08` - Add the cheap pre-record drift re-check that keeps the common case off the signal path entirely; `src/vaultspec_rag/indexer/_run_checkpoint.py`.

### Phase `W02.P04` - Supersede and re-record

Remedy the drift through its owner, bounded, with deferral as the visible fallback.

- [x] `W02.P04.S09` - Route the drift signal to the drift owner so it supersedes the racing path and the run re-records it instead of aborting; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `W02.P04.S10` - Bound the per-path retry and defer on exhaustion, emitting a warning that names the path and the exhausted budget; `src/vaultspec_rag/indexer/_codebase_indexer.py`.

## Wave `W03` - Accounting, gate, and verification

Stop the breaker reacting to edit rate, restart the module-length ratchet the tooling already documents, and verify the whole change against a live service.

### Phase `W03.P05` - Circuit accounting and the ratchet

Count faults only, and turn the advisory length gate into a failing one.

- [x] `W03.P05.S11` - Count faults only in the circuit breaker and record drift outcomes in their own counter reported alongside job state; `src/vaultspec_rag/indexer/_run_policy.py`.
- [ ] `W03.P05.S12` - Turn the module-length gate from advisory to failing at a threshold the post-seam tree actually meets, and record the full offender census in the same change so the remaining ratchet is visible rather than implied; `tools/module_length.py`.

### Phase `W03.P06` - Verify against a live service

Prove the guard still fires, the remedy works on a genuinely moving tree, and the degraded state clears.

- [x] `W03.P06.S13` - Prove the upsert guard bidirectionally: permit the forbidden write, watch the test fail on its own assertion, restore, watch it pass, and record both directions; `src/vaultspec_rag/tests/`.
- [x] `W03.P06.S14` - Verify on a live service against a genuinely moving tree that a racing path is superseded, the run completes, and the degraded state clears; `src/vaultspec_rag/tests/integration/`.

## Description

## Steps

## Parallelization

## Verification
