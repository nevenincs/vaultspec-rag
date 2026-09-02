---
tags:
  - '#plan'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_hash: 'sha256:523a051cc025d6b7c7130672c7d59c3e39296ce7234111095439e428f8233012'
tier: L3
related:
  - '[[2026-08-28-platform-backend-selection-adr]]'
  - '[[2026-08-28-platform-backend-selection-research]]'
  - '[[2026-09-01-platform-backend-selection-reference]]'
---

<!-- RETIRED: S06, S07 -->

# `platform-backend-selection` plan

Add measured Apple silicon MPS support through one accelerator contract while preserving CUDA behavior and refusing CPU fallback.

## Description

This plan executes the accepted platform backend decision for issue #400. The first Wave establishes canonical accelerator resolution, backend-specific admission, and model placement. The second Wave adapts capability and operator surfaces after the compute contract is stable. The third Wave adds real-MPS acceptance and updates user guidance. Linux dependency topology, runner provisioning, and buildout lanes are outside scope.

## Steps

## Wave `W01` - establish the accelerator contract

Define one supported-accelerator contract and backend-specific admission before any production caller changes.

### Phase `W01.P03` - resolve and admit supported accelerators

Make CUDA-first MPS-second resolution, CPU refusal, and backend admission canonical.

- [x] `W01.P03.S01` - Implement the resolved accelerator context, fallback refusal, OOM classification, and cache release; `src/vaultspec_rag/_gpu.py`.
- [x] `W01.P03.S02` - Generalize load admission for CUDA memory policy and MPS capability policy under one load window; `src/vaultspec_rag/_gpu_admission.py`.
- [x] `W01.P03.S03` - Expose backend-neutral device readings while preserving CUDA allocator evidence; `src/vaultspec_rag/memory_probe.py`.
- [x] `W01.P03.S04` - Prove accelerator resolution order, CPU refusal, fallback refusal, and centralized torch loading; `src/vaultspec_rag/tests/test_torch_load_centralized.py`.
- [x] `W01.P03.S05` - Prove CUDA and MPS admission semantics including the shared load window; `src/vaultspec_rag/tests/test_gpu_admission.py`.
- [x] `W01.P03.S50` - Route production device-load evidence through the detected MPS backend.; `src/vaultspec_rag/_gpu_admission.py, src/vaultspec_rag/tests/test_gpu_admission.py`.

### Phase `W01.P04` - migrate resident model consumers

Route every dense, sparse, and reranker construction and recovery path through the resolved accelerator.

- [x] `W01.P04.S08` - Place dense and sparse models through the accelerator context and use backend-neutral recovery; `src/vaultspec_rag/embeddings.py`.
- [x] `W01.P04.S09` - Place the shared resident reranker through the accelerator context; `src/vaultspec_rag/service.py`.
- [x] `W01.P04.S10` - Place the lazy local reranker and retry path through the accelerator context; `src/vaultspec_rag/search/_searcher.py`.
- [x] `W01.P04.S11` - Release accelerator caches through the canonical backend operation; `src/vaultspec_rag/indexer/_streaming.py`.
- [x] `W01.P04.S12` - Exercise backend-neutral embedding retry and cache behavior; `src/vaultspec_rag/tests/test_encode_bucket_planner.py`.
- [x] `W01.P04.S13` - Exercise shared reranker construction on resolved accelerators; `src/vaultspec_rag/tests/test_service_registry.py`.
- [x] `W01.P04.S44` - Update resilience benchmarks to consume the canonical accelerator context.; `src/vaultspec_rag/tests/benchmarks/bench_large_index_resilience.py`.
- [x] `W01.P04.S46` - Adapt sparse conversion parity fixtures to the canonical accelerator context.; `src/vaultspec_rag/tests/test_encode_hygiene_unit.py`.
- [x] `W01.P04.S47` - Retarget bounded encode-recovery architecture guards to backend-neutral OOM classification.; `src/vaultspec_rag/tests/test_adr_regression.py`.

## Wave `W02` - make operator surfaces backend truthful

After all compute consumers use one context, project that same backend identity through diagnostics and lifecycle surfaces.

### Phase `W02.P05` - project capability and readiness

Replace CUDA-or-nothing reports with one honest accelerator capability shape.

- [x] `W02.P05.S14` - Report resolved backend identity and memory kind in the public capability snapshot; `src/vaultspec_rag/api.py`.
- [x] `W02.P05.S15` - Diagnose torch and accelerator readiness for CUDA, MPS, and unavailable hosts; `src/vaultspec_rag/_readiness.py`.
- [x] `W02.P05.S16` - Report resident accelerator memory without labeling unified memory as VRAM; `src/vaultspec_rag/server/_state.py`.
- [x] `W02.P05.S17` - Exercise backend-neutral readiness payloads and torch-free probing; `src/vaultspec_rag/tests/test_readiness.py`.
- [x] `W02.P05.S18` - Exercise capability and health payload compatibility for MPS; `src/vaultspec_rag/tests/test_api_clean_admission.py`.
- [x] `W02.P05.S48` - Correct benchmark capability reporting for MPS unified memory.; `src/vaultspec_rag/api.py, src/vaultspec_rag/tests/test_api_clean_admission.py`.

### Phase `W02.P06` - adapt CLI diagnosis and preflight

Give operators backend-specific remediation while preserving service-control torch freedom.

- [x] `W02.P06.S19` - Classify missing, CUDA, MPS, and CPU-only torch environments; `src/vaultspec_rag/cli/_gpu_errors.py`.
- [x] `W02.P06.S20` - Probe the service interpreter for any supported accelerator without importing torch into the caller; `src/vaultspec_rag/cli/_process.py`.
- [x] `W02.P06.S21` - Render accelerator backend and memory semantics in human status output; `src/vaultspec_rag/cli/_status.py`.
- [x] `W02.P06.S22` - Generalize torch configuration diagnosis beyond CUDA availability; `src/vaultspec_rag/torch_config/_diagnose.py`.
- [x] `W02.P06.S23` - Exercise supported-accelerator subprocess preflight and remediation; `src/vaultspec_rag/tests/test_service_env_preflight.py`.
- [x] `W02.P06.S36` - Invoke the canonical supported-accelerator subprocess probe during service startup; `src/vaultspec_rag/cli/_service_start.py`.
- [x] `W02.P06.S37` - Exercise CUDA, MPS, and unavailable torch configuration diagnosis; `src/vaultspec_rag/tests/test_torch_config.py`.
- [x] `W02.P06.S42` - Update installer accelerator diagnostics to use the canonical backend-neutral warning helper.; `src/vaultspec_rag/cli/_install.py`.
- [x] `W02.P06.S43` - Update service lifecycle preflight to call the canonical accelerator loader.; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `W02.P06.S45` - Verify CLI status renders and serializes truthful MPS unified-memory capability data.; `src/vaultspec_rag/tests/test_cli_status.py`.
- [x] `W02.P06.S49` - Correct CLI fallback diagnosis and unavailable accelerator wording.; `src/vaultspec_rag/cli/_gpu_errors.py, src/vaultspec_rag/cli/_status.py, src/vaultspec_rag/tests/test_cli_install.py, src/vaultspec_rag/tests/test_cli_status.py`.

## Wave `W03` - prove and document Apple silicon support

Close the feature with a real-model MPS guard, macOS CI routing, and accurate user guidance after production paths are backend-neutral.

### Phase `W03.P07` - add the real MPS acceptance guard

Prove the configured dense, sparse, and reranker models execute together on MPS with CPU fallback disabled.

- [x] `W03.P07.S24` - Add a real-model concurrent-residency MPS integration guard; `src/vaultspec_rag/tests/integration/test_mps_backend.py`.
- [x] `W03.P07.S25` - Declare and route the MPS test marker without changing CUDA lanes; `pyproject.toml`.
- [x] `W03.P07.S26` - Run the MPS guard only on the self-hosted Apple silicon job; `.github/workflows/ci.yml`.
- [x] `W03.P07.S38` - Route the MPS hardware tier independently from ordinary and CUDA test recipes; `justfile`.
- [x] `W03.P07.S39` - Declare MPS as a distinct hardware tier without CUDA lease assumptions; `src/vaultspec_rag/tests/_tier_gate.py`.
- [x] `W03.P07.S40` - Guard explicitly selected MPS tests on Apple silicon without CUDA coordination; `conftest.py`.
- [x] `W03.P07.S41` - Prove MPS marker selection and exclusion discipline can fail on drift; `src/vaultspec_rag/tests/test_marker_discipline.py`.
- [x] `W03.P07.S51` - Prove dense, sparse, and reranker parameter placement in the real MPS guard.; `src/vaultspec_rag/tests/integration/test_mps_backend.py, src/vaultspec_rag/tests/test_marker_discipline.py`.
- [x] `W03.P07.S52` - Run the required MPS support gate on main before publication.; `.github/workflows/ci.yml, src/vaultspec_rag/tests/test_marker_discipline.py`.

### Phase `W03.P08` - publish backend-accurate guidance

Replace CUDA-only and macOS-unsupported claims with the supported accelerator contract and honest memory terminology.

- [x] `W03.P08.S27` - State CUDA and Apple silicon requirements in the project overview; `README.md`.
- [x] `W03.P08.S28` - Describe accelerator selection and unified-memory behavior; `docs/architecture.md`.
- [x] `W03.P08.S29` - Make the tutorial prerequisites valid for CUDA and Apple silicon; `docs/getting-started.md`.
- [x] `W03.P08.S30` - Document macOS installation, MPS fallback refusal, and platform-specific provisioning; `docs/installation.md`.
- [x] `W03.P08.S31` - Describe dense, sparse, and reranker execution on the selected accelerator; `docs/indexing.md`.
- [x] `W03.P08.S32` - Document service startup and preflight for CUDA and MPS; `docs/service-mode.md`.
- [x] `W03.P08.S33` - Update readiness and model-download command contracts for supported accelerators; `docs/cli.md`.
- [x] `W03.P08.S34` - Define accelerator, CUDA, MPS, and unified-memory terms; `docs/glossary.md`.
- [x] `W03.P08.S35` - Review the complete implementation for safety, intent, and canonical ownership; `platform-backend-selection change set`.
- [x] `W03.P08.S53` - Clarify the managed torch prompt and inactive macOS source marker.; `README.md, docs/getting-started.md`.

## Parallelization

Waves execute in order. Test Steps may follow their production Step immediately; production files sharing the accelerator contract remain sequential to avoid parallel edits across one ownership seam.

## Verification

The plan succeeds when unit and integration tests prove CUDA precedence, functional MPS execution with fallback disabled, CPU refusal, truthful backend reporting, torch-free service-control imports, unchanged CUDA behavior, and updated documentation; lint, format, type checks, targeted tests, and formal code review must all pass.
