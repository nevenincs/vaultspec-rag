---
tags:
  - '#plan'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:ad98d24e1913835725e1c4f9f7aa0e865e68ce61de0f2d96cc9b27733a779488'
tier: L2
related:
  - '[[2026-07-24-index-cuda-ceiling-adr]]'
  - '[[2026-07-24-index-cuda-ceiling-research]]'
---

# `index-cuda-ceiling` plan

Size the indexing CUDA budget to real device headroom and charge each job only
its own forward demand, retiring the restart-fragile encode-batch workaround.

## Description

Executes `2026-07-24-index-cuda-ceiling-adr`, grounded in
`2026-07-24-index-cuda-ceiling-research` and revised after an adversarial review.
Four coupled changes to the indexing memory guard: give documents their own
encode sub-batch, derive the ceiling from device capacity with a bidirectional
override at all three enforcing sites, and capture each job's own forward peak
net of the resident-model baseline so concurrent jobs stop cross-charging one
process-global high-water.

`P01` is independent and ships the durable form of the env workaround already
running. `P02` fixes the unraisable ceiling. `P03` is the delicate core: the
baseline exclusion and the per-job capture are coupled, because a post-reset peak
is absolute and subtracting the baseline from only one side of the comparison
would double-count the models and tighten the ceiling into a regression. `P04`
proves the two guards both directions and verifies a live corpus rebuild.

## Steps

### Phase `P01` - give documents a dedicated encode sub-batch

Add embedding_document_encode_batch_size mirroring the code path, retiring the shared-knob runtime workaround that currently keeps the corpus indexing.

- [x] `P01.S01` - add embedding_document_encode_batch_size to config defaults and the env-var mapping with a window-appropriate default; `src/vaultspec_rag/config.py`.
- [x] `P01.S02` - have the document indexer read the document encode batch instead of falling through to embedding_encode_batch_size; `src/vaultspec_rag/indexer/_document_indexer.py`.
- [x] `P01.S03` - add a test asserting document embedding uses the document sub-batch and is independent of the vault and code sub-batches; `src/vaultspec_rag/tests/test_config.py`.

### Phase `P02` - derive the ceiling from device capacity and make the override bidirectional

Replace the hardcoded 12 GiB min-clamp with a device-capacity-minus-headroom derivation at every enforcing site, and let the config knob raise as well as lower.

- [x] `P02.S04` - add a GPU-gated device-capacity query that returns total CUDA memory and is unreachable from torch-free service-client and worker paths; `src/vaultspec_rag/_gpu.py`.
- [x] `P02.S05` - derive the effective ceiling as device-capacity minus a reserved headroom margin with the config value overriding in either direction; `src/vaultspec_rag/memory_probe.py`.
- [x] `P02.S06` - replace the one-way min-clamp at the dispatch admission site with the bidirectional derived ceiling; `src/vaultspec_rag/job_dispatch.py`.
- [x] `P02.S07` - replace the one-way min-clamp in the codebase indexer budget builder with the derived ceiling; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `P02.S08` - replace the one-way min-clamp in the document indexer budget builder with the derived ceiling; `src/vaultspec_rag/indexer/_document_indexer.py`.
- [x] `P02.S09` - add a test asserting the config override raises the ceiling above the profile floor and still lowers it below; `src/vaultspec_rag/tests/test_config.py`.

### Phase `P03` - capture each job's own forward peak, net of the resident baseline

Capture the allocation high-water inside the gpu_lock forward bracket and enforce every checkpoint against that job-local, baseline-net value instead of the process-global counter, without double-counting the resident models.

- [x] `P03.S10` - add a bare peak reset-and-read helper that resets peak stats without flushing the allocator cache; `src/vaultspec_rag/memory_probe.py`.
- [x] `P03.S11` - sample the resident-model baseline after every model including the lazily-loaded reranker is resident; `src/vaultspec_rag/service.py`.
- [x] `P03.S12` - capture the allocation high-water inside the gpu_lock forward bracket in the shared encode path; `src/vaultspec_rag/indexer/_streaming.py`.
- [x] `P03.S13` - thread the captured per-job forward peak into the memory budget as the maximum across the job's brackets; `src/vaultspec_rag/memory_probe.py`.
- [x] `P03.S14` - enforce every sample checkpoint against the captured baseline-net peak so no path reads max_memory_allocated directly; `src/vaultspec_rag/memory_probe.py`.
- [x] `P03.S15` - make the ceiling comparison baseline-consistent by subtracting the baseline from the captured peak and from the derived ceiling on the same side; `src/vaultspec_rag/memory_probe.py`.

### Phase `P04` - prove the guards and verify end to end

Demonstrate the cross-job-contamination and double-count guards failing for their intended reason before trusting them, then confirm a live corpus rebuild indexes with no spurious ceiling failures.

- [x] `P04.S16` - prove the cross-job contamination guard fails when enforcement reads the process-global counter and passes when it reads the captured peak, recording both directions; `src/vaultspec_rag/tests/test_job_resilience.py`.
- [x] `P04.S17` - prove the double-count guard fails when the baseline is subtracted from only one side of the ceiling comparison, recording both directions; `src/vaultspec_rag/tests/test_config.py`.
- [x] `P04.S18` - run the full unit suite and the citation-gate lint over every changed file; `src/vaultspec_rag/tests`.
- [x] `P04.S19` - restart the service on the built code and confirm a live feature-profile corpus rebuild completes with no spurious cuda_memory_ceiling failures under concurrency; `src/vaultspec_rag`.

## Parallelization

`P01` is fully independent - it touches the document encode batch and shares no
file with the ceiling work - and may land and ship on its own.

`P02` and `P03` both modify `memory_probe.py` and the two indexer budget builders,
so they carry hard ordering: `P02` (the derived ceiling) lands first because
`P03`'s baseline-consistent comparison is written against the derived ceiling, not
the old min-clamp. Within `P03` the steps are strictly ordered - the bare-reset
helper (`S10`) and the pinned baseline (`S11`) precede the capture (`S12`), which
precedes threading it into the budget (`S13`), enforcement (`S14`), and the
baseline-consistent comparison (`S15`) last, because enforcing before the
comparison is made baseline-consistent would trip the double-count regression the
review flagged.

`P04` is sequenced last. `S16` and `S17` each depend on the phase whose guard they
prove; `S18` and `S19` are the closing suite and live verification and run only
after every code step is complete. `S19` requires a service restart on the built
code and must not run against the currently-resident daemon.

## Verification

The plan is complete when every Step is closed and each criterion holds.

- Document embedding uses `embedding_document_encode_batch_size`, independent of
  the vault and code sub-batches, and the runtime env workaround is no longer
  needed for the failing corpus to index.
- The `index_cuda_ceiling_mb` override raises the effective ceiling above the
  profile floor as well as lowering it below, at all three enforcing sites.
- Two index jobs of different kinds running concurrently no longer report a
  byte-identical high-water; each enforces against its own captured forward peak.
- The cross-job-contamination guard has been observed failing when enforcement
  reads the process-global counter and passing when it reads the captured peak,
  both directions recorded in the Step Record.
- The double-count guard has been observed failing when the baseline is
  subtracted from only one side of the comparison, both directions recorded.
- No enforcement path reads `torch.cuda.max_memory_allocated()` directly.
- The full unit suite passes and the citation-gate lint reports no development
  record named in any changed source file.
- A live feature-profile corpus rebuild on the built code completes with no
  spurious `cuda_memory_ceiling` failure under concurrent index jobs.
