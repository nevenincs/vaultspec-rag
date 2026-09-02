---
tags:
  - '#reference'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:d8c7624d14f3a8c21fd795c5cf40d6faf2d6bdbe900ce0cb253b3ad00ac986c6'
related:
  - "[[2026-08-28-platform-backend-selection-research]]"
  - "[[2026-08-28-platform-backend-selection-adr]]"
---

# `platform-backend-selection` reference: `current accelerator seams and measured MPS support`

The production tree at commit `635747ee` centralizes torch import and load admission, but device identity, allocator handling, model placement, and operator reporting remain CUDA-shaped across several modules. A fleet Apple silicon host now supplies direct MPS evidence for the exact production model stack.

## Summary

### The load gate is the canonical device-selection seam

`src/vaultspec_rag/_gpu.py:65` is the only compute-path torch loader. It runs device admission, imports torch function-locally, rejects `torch.cuda.is_available() == False`, configures the CUDA allocator, and returns only the torch module (`src/vaultspec_rag/_gpu.py:88`). Any backend selection belongs here so model constructors and reporters consume one resolved device rather than repeat vendor predicates.

`src/vaultspec_rag/_gpu_admission.py:493` delegates admission to `cuda_device_memory()`. Its free-memory floor, unreadable-device streak, allocator credit, and cross-process load window are discrete-memory CUDA policy, not generic accelerator policy. The machine-global load window remains useful across backends, while the memory verdict needs a backend-specific branch because MPS exposes unified memory and no CUDA-style device-wide free-VRAM reading.

### Model placement and recovery bypass the gate's device decision

`src/vaultspec_rag/embeddings.py:739` initializes dense encoding with `device="cuda"`; `src/vaultspec_rag/embeddings.py:812` independently places the sparse model on CUDA. The same class names the card through `torch.cuda.get_device_name(0)` and catches CUDA OOM plus calls `torch.cuda.empty_cache()` at `src/vaultspec_rag/embeddings.py:1008`.

The two reranker construction paths repeat the same assumptions: shared service residency uses `device="cuda"` at `src/vaultspec_rag/service.py:295`, while lazy local search uses it at `src/vaultspec_rag/search/_searcher.py:419`. Both report the CUDA device name, and local retry catches CUDA OOM and empties the CUDA cache at `src/vaultspec_rag/search/_searcher.py:490`. A resolved device descriptor therefore needs canonical helpers for device name, OOM classification, and cache release as well as the placement string.

### Diagnostics currently equate GPU capability with CUDA

The public capability snapshot branches on `torch.cuda.is_available()` and reports CUDA properties or zero VRAM at `src/vaultspec_rag/api.py:813`. Readiness repeats that predicate and CUDA device-name lookup at `src/vaultspec_rag/_readiness.py:225`. Resident service memory uses CUDA allocated/reserved counters at `src/vaultspec_rag/server/_state.py:298`, and CLI remediation diagnoses only `torch.version.cuda` plus CUDA availability at `src/vaultspec_rag/cli/_gpu_errors.py:309`.

These are read-only probes and deliberate exceptions to the compute loader. They must remain function-local and tolerant of torch absence, but they should all project one backend-neutral capability shape. Unified memory must be represented as such or have VRAM omitted; zero VRAM is a false hardware statement.

### The production model stack runs concurrently on the smallest fleet Mac

On `Gergelys-MacBook-Neo.local` (macOS 26.5.1 build 25F80, Apple ARM64, 8 GiB unified memory), Python 3.13.11, torch 2.13.0, sentence-transformers 5.7.0, and transformers 5.16.1 ran with `PYTORCH_ENABLE_MPS_FALLBACK=0`. The exact configured revisions were Qwen embedding `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`, SPLADE `fdfeceb91d7b9de7985b38addd3ba9f53a59a355`, and BGE reranker `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`.

All three models stayed resident together on `mps:0`. Dense encoding returned a finite `(1, 1024)` vector, sparse query encoding returned `(1, 30522)` with 26 nonzero terms, and reranking returned one finite score. After all loads, torch reported 3,720.1 MiB current allocation and 4,218.5 MiB driver allocation against a 5,461.3 MiB recommended MPS working set; after all forwards the driver figure was 4,228.7 MiB. This is backend execution evidence without silent CPU fallback, not a throughput benchmark.

The probe used one guarded `/tmp` root, a private uv cache and environment, and transient copies of the gated model snapshots. Peak scratch was 4.0 GiB and cleanup was verified. The runner checkout and persistent caches were unchanged.
