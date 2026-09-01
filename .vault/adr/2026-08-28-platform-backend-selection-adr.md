---
tags:
  - '#adr'
  - '#platform-backend-selection'
date: '2026-08-28'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:47a3ad352f3b6d462bb1b063ce88a17a533491a23a7046c434ff8d2bfb73cf61'
related:
  - '[[2026-08-28-platform-backend-selection-research]]'
  - '[[2026-09-01-platform-backend-selection-reference]]'
  - '[[2026-03-06-gpu-only-rag-stack-adr]]'
---
# `platform-backend-selection` adr: `admit measured accelerators and keep platform provisioning separate` | (**status:** `accepted`)

## Problem Statement

The project requires accelerator-only inference and currently substitutes CUDA for that requirement throughout admission, model placement, recovery, and diagnostics. That substitution rejects a measured Apple silicon backend and makes operator output describe unified-memory hardware as having no GPU. The packaging asymmetry tracked separately is related architecture but not part of issue #400's implementation lane.

This record decides which runtime accelerators are supported, how CPU fallback remains forbidden, and where backend-specific policy ends. Grounding lives in `2026-08-28-platform-backend-selection-research` and `2026-09-01-platform-backend-selection-reference`.

## Considerations

- Accelerator-only inference is the stable parent constraint; broadening from one accelerator vendor must not admit CPU (`2026-03-06-gpu-only-rag-stack-adr`).
- The exact production model stack now has concurrent-residency and forward-pass evidence on MPS with fallback disabled (`2026-09-01-platform-backend-selection-reference`).
- CUDA free-VRAM admission cannot be relabeled for unified memory (`2026-08-28-platform-backend-selection-research`).
- Compute paths must retain one function-local torch gate, while service clients and control surfaces remain torch-free (`2026-09-01-platform-backend-selection-reference`).
- Capability output must describe the resolved backend and its actual memory model rather than infer hardware absence from one vendor predicate (`2026-09-01-platform-backend-selection-reference`).
- Linux CUDA packaging and upgrade behavior remain a separate delivery lane even though they share upstream reasoning (`2026-08-28-platform-backend-selection-research`).

## Considered options

**Keep runtime CUDA-only and document macOS as unsupported.** Rejected because measured MPS satisfies the accelerator-only constraint and the current report makes a false hardware claim.

**Resolve CUDA, then MPS, then CPU.** Rejected because a CPU tail recreates the silent degradation the parent decision forbids.

**Resolve an explicit supported-accelerator set, CUDA before MPS, and refuse CPU (chosen).** This preserves the mandate, keeps selection deterministic, and requires evidence before another backend enters the set.

**Reuse CUDA admission and memory reporting for MPS.** Rejected because unified memory has neither discrete free VRAM nor a CUDA allocator namespace; copied semantics would be misleading.

**Require MPS to expose a device-wide free-memory reading before admission.** Rejected because no such signal exists and the smallest fleet host has direct full-stack evidence. Capability-based MPS admission is honest; inventing a free-memory figure is not.

## Constraints

- `PYTORCH_ENABLE_MPS_FALLBACK` must not be enabled for an admitted MPS process. Allowing unsupported operators to relocate to CPU violates accelerator-only inference even if the selected device still says MPS.
- CUDA retains its free-memory floor, unreadable-device streak, allocator credit, and cross-process load window. MPS retains the machine-global load window but uses capability-based admission because it has no equivalent device-wide free-memory observation.
- MPS memory output identifies unified memory and may expose process allocator or recommended-working-set diagnostics, but it never labels those figures VRAM and never reports missing VRAM as zero.
- Backend-specific OOM classification and cache release must sit behind the resolved device contract; call sites cannot branch directly on `torch.cuda` or `torch.mps`.
- The supported MPS claim covers functional compatibility and concurrent residency for the configured production models. It does not claim CUDA-equivalent throughput, sustained battery behavior, or thermal characteristics.
- Issue #400 does not modify Linux dependency topology, runner provisioning, or buildout lanes.

## Implementation

The centralized compute loader returns a resolved accelerator context containing torch, backend identity, placement string, display name, memory kind, and backend operations needed by callers. Resolution checks supported backends in declared order: CUDA, then MPS. If neither is available it raises one accelerator-required error; CPU is never a candidate. MPS resolution refuses an enabled CPU-fallback environment.

Device admission consumes the resolved backend. CUDA follows the existing discrete-memory verdict unchanged. MPS serializes the model-load window but admits on measured backend capability rather than a fabricated free-memory reading. The context owns OOM recognition and cache release so embedding and reranking retry paths use one implementation.

Dense, sparse, and reranker constructors consume the placement from that context. Capability, readiness, health, and status projections use one backend-neutral shape naming `cuda`, `mps`, or unavailable; memory fields carry their kind and remain absent when the backend cannot state them honestly. Read-only probes retain guarded function-local torch imports, and service-client/control call paths remain torch-free.

Tests exercise resolution order, CPU refusal, MPS fallback refusal, model placement, backend-specific recovery, truthful capability projection, and fresh-interpreter torch-free imports. A self-hosted macOS integration guard runs the real configured dense, sparse, and reranker forwards on MPS with CPU fallback disabled before support is advertised.

The Linux packaging decision remains recorded here as related architecture but executes in its own issue and plan, not in the issue #400 branch.

## Rationale

An explicit supported-accelerator set is the only option that satisfies both stable constraints: use available GPU hardware and never silently infer on CPU. The full-stack fleet measurement removes the former evidence blocker, while a deterministic CUDA-before-MPS order preserves existing behavior wherever CUDA is present (`2026-08-28-platform-backend-selection-research`).

Backend-specific admission and memory semantics are necessary because the common abstraction is device selection, not allocator identity. Sharing the load window, placement contract, and reporting shape removes duplicated decisions; preserving CUDA's established admission and giving MPS capability-based admission avoids pretending unlike memory systems expose the same evidence (`2026-09-01-platform-backend-selection-reference`).

Keeping packaging outside this implementation lane limits blast radius and respects the separate provisioning work already underway.

## Consequences

Apple silicon becomes a supported accelerator target without weakening the CPU prohibition. Model placement, recovery, and diagnostics gain one canonical backend contract, and capability output stops reporting unified-memory hardware as GPU-absent or zero-VRAM.

MPS cannot reject transient system-wide memory pressure before load as precisely as CUDA rejects foreign VRAM pressure. It may therefore fail during allocation on a heavily pressured Mac, and that failure must remain explicit rather than falling back to CPU. The self-hosted macOS tier gains a real-model support guard whose runtime and gated model access must stay bounded and controlled.

Adding another accelerator now requires resolution, backend operations, honest memory semantics, and real full-stack evidence. Linux packaging remains unresolved by this implementation and must not be inferred complete from MPS support.
