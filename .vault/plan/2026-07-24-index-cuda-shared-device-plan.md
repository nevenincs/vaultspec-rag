---
tags:
  - '#plan'
  - '#index-cuda-shared-device'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:241c8fb7219d06be7367cac4a8be6bd8d26fd6134e87c2b592f5fa3974190fc8'
tier: L2
related:
  - '[[2026-07-24-index-cuda-shared-device-adr]]'
  - '[[2026-07-24-index-cuda-shared-device-research]]'
---

# `index-cuda-shared-device` plan

Derive the indexing CUDA ceiling from free device memory as an absolute figure, and stop the code indexer rejecting a runtime peak as corpus size.

## Description

Executes `2026-07-24-index-cuda-shared-device-adr`, grounded in `2026-07-24-index-cuda-shared-device-research` and revised after an adversarial review that caught a double-count. Two fixes to the CUDA-ceiling memory model: the auto ceiling derives from free device memory made ABSOLUTE by re-adding the resident baseline (a bare free-minus-headroom would re-subtract the models the baseline-net enforcement already subtracts), sampled after the admission cache flush; and the code indexer stops rejecting a runtime CUDA peak as a corpus-sizing dimension, matching the document indexer.

`P01` is the delicate phase - the absolute-ceiling arithmetic and the sampling-order reconciliation across both budget builders. `P02` is the self-contained corpus-dimension removal. `P03` proves both guards and verifies.

## Steps

### Phase `P01` - free-memory absolute ceiling

Derive the auto ceiling from free device memory made absolute by re-adding the resident baseline, sampled after the admission cache flush, so it never double-subtracts the models and tracks real free memory on a shared GPU.

- [x] `P01.S01` - add a guarded cuda_free_memory_mb probe returning mem_get_info free in MiB or None off the GPU path; `src/vaultspec_rag/memory_probe.py`.
- [x] `P01.S02` - change resolve_index_cuda_ceiling_mb to derive the absolute auto ceiling as min(baseline + free - headroom, total - headroom) with the operator override and profile fallback unchanged; `src/vaultspec_rag/memory_probe.py`.
- [x] `P01.S03` - pass the resident baseline into the ceiling derivation and move it after the admission cache flush in the codebase indexer budget builder; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `P01.S04` - pass the resident baseline into the ceiling derivation and keep it after the admission cache flush in the document indexer budget builder; `src/vaultspec_rag/indexer/_document_indexer.py`.
- [x] `P01.S05` - carry the free-derived ceiling through the dispatch admission snapshot as a point-in-time diagnostic without changing enforcement; `src/vaultspec_rag/job_dispatch.py`.

### Phase `P02` - drop the code-path corpus CUDA rejection

Stop the code indexer rejecting a runtime CUDA peak as a corpus-sizing dimension, matching the document indexer's diagnostic-only treatment, keeping the measurement field and JSON.

- [x] `P02.S06` - remove cuda_bytes from the code indexer corpus-dimension rejection while keeping the measured field and its JSON reporting; `src/vaultspec_rag/indexer/_codebase_indexer.py`.

### Phase `P03` - prove the guards and verify

Prove the double-count and corpus-rejection guards fail for their intended reason, then run the full unit suite and lint.

- [x] `P03.S07` - prove the double-count guard fails when the ceiling reverts to bare free-minus-headroom and passes at baseline-plus-free-minus-headroom, both directions recorded; `src/vaultspec_rag/tests/test_config.py`.
- [x] `P03.S08` - prove the corpus-rejection guard fails when a runtime CUDA peak above the profile is re-admitted and rejects again if reinstated, both directions recorded; `src/vaultspec_rag/tests/test_job_resilience.py`.
- [x] `P03.S09` - run the full unit suite and the citation-gate lint over every changed file; `src/vaultspec_rag/tests`.

## Parallelization

`P01` and `P02` both touch `_codebase_indexer.py`, so they carry an ordering: land `P01` (baseline threading + derivation) first, then `P02`'s one-line rejection removal on top, to keep the diffs clean. Within `P01` the derivation change (`S02`) precedes the budget-builder wiring (`S03`/`S04`) that calls it. `P03` is last; each guard step depends on the phase it proves.

## Verification

The plan is complete when every step is closed and each holds.

- On a device with a large non-torch baseline, the derived ceiling is below total-minus-headroom and tracks free memory; on an idle device it recovers the prior total-minus-headroom value.
- The derived ceiling is absolute: a legitimate net forward (peak minus baseline) within free memory is admitted, and the double-count guard fails if the derivation reverts to a bare free-minus-headroom.
- Free is sampled after the admission cache flush at both budget builders.
- A code job whose runtime CUDA peak exceeds the profile's cuda_bytes is no longer rejected as corpus_limit_exceeded, and the guard fails if the rejection is reinstated.
- The full unit suite passes and the citation gate is clean on every changed file.
