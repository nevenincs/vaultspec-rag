---
tags:
  - '#audit'
  - '#pipeline-performance'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:128c1afe080b2cfc79fb27bea96b2dffc50dc4bb8731ee331b1a5abc93a2f621'
related:
  - "[[2026-09-30-pipeline-performance-plan]]"
  - "[[2026-09-30-sparseencode-adr]]"
  - "[[2026-07-29-encode-batch-adaptivity-adr]]"
  - "[[2026-09-26-gpu-single-owner-adr]]"
  - "[[2026-09-30-pipeline-performance-research]]"
---

# `pipeline-performance` audit: `Profiling harness and CPU optimization review with pending GPU evidence`

## Scope

Independent GPT-6.1 Sol review of S01 and partial S02 against b9d2daf0, including uncommitted profiling-harness and AST changes. Foreign staged origin/main merge changes are excluded. Governing plan: `2026-09-30-pipeline-performance-plan`; sparse, batching and GPU ownership decisions bound the review. Overall verdict PENDING: verified native CPU evidence is now available and borrowed lifetime cleanup is closed; admitted CUDA measurements and sustained energy comparisons remain outstanding.

## Findings

### verification | low | Native and CUDA profiling evidence remains pending

Applicable evidence: 72 focused pytest passes, Ruff/format/type passes, five intended guard-mutation failures followed by restored passes. Official wheel archive SHA and local executable pin agree with reviewed official PyPI metadata, but archive member provenance and native execution remain outstanding until the constants are committed. Two CUDA attempts correctly refused borrowing with 11 active tickets. They prove admission behavior, not encoder timing, output parity, actual kernel attribution or GPU memory improvements. Root owns these runs when borrowing is available; S02/S03 remain open.

### borrowed-gpu-lifetime | high | Cleanup must precede service resume

Initial review found no explicit borrowed-model/cache teardown in the harness. Returning from the consumer can free models while retaining allocator blocks, whereas resident resume occurs before borrower process exit. Release owned references and unused allocator memory inside the consumer, once at teardown, before borrowed work returns; verify cleanup ordering even on failure. S01 is reopened for this correction. No per-arm or per-bucket cache flushing is permitted.

### chunking | low | Exact parity supports compatibility and timing gains are modest

Lazy decoding skips spans where original container/structural predicates already force traversal. Character budgets, leaf splitting, metadata, order and UTF-8 remain unchanged. Exact parity covered 820 sources at five budgets; Unicode tests cover the affected boundaries. Twenty first and 36 repeat default-budget pairs yield a combined median about 1.023x with 36/56 wins under noisy CPU conditions. This supports a modest observed Python chunking improvement, not a universal indexing-throughput claim.

### measurement-scope | low | Sweeps and device observations retain explicit limits

Adaptive ceilings persist across cases; snapshots expose that stateful history. NVML index zero can mismatch CUDA on reordered/multiple-device hosts. Native attachment lacks a startup handshake. Python-only CPU samples do not generalize to every grammar. Live GPU samples include desktop activity and cannot attribute occupancy/utilization to individual encoders. The earlier combined OOM-count defect was corrected by summing independent per-encoder maxima and covered by a focused test.

### borrowed-gpu-lifetime-closure | low | Consumer teardown resolves the high lifetime finding

Independent re-review closes the preceding high finding. `encoder_work` unwinds model locals/closures before teardown. Failure handling clears traceback frames across exception chains to release retained model references, then consumer-owned GC, synchronization, one canonical cache release and synchronization precede the exclusive teardown-memory artifact and borrower return. Cleanup failures propagate. Applicable evidence: 74 focused passes plus two intended teardown mutation failures and restored passes in `.pytest-tmp/profile-teardown-proofs.txt`. An initial mutation exposed an incidental mock AttributeError; the incomplete snapshot mock was corrected before accepting the intended assertion failure. No per-arm/per-bucket cache flushing was added. Overall verdict remains PENDING for committed pins/native provenance execution and admitted real CUDA profiling, timing/memory and encoder parity.

### live-sampler-interruption | high | Terminating blocking sampling can leave the target suspended

The supervisor's live native diagnostic fell behind and timed out. Terminating its blocking profiler left outstanding process/thread suspension. Recovery restored the same validated service instance without restart or job cancellation. Blocking native sampling is unsafe for interrupted supervised runs; S01 was reopened to require a nonblocking default and explicit exclusion of native mode. No accepted live stack artifact or GPU inference measurement follows from the failed run.

### live-sampler-interruption-closure | low | Nonblocking default and proven guards close the interruption finding

Independent GPT-6.1 Sol re-review found no new code blocker in the corrected default. `sampling_command` uses `--nonblocking`, excludes `--native`, and targets only the current process. Official py-spy config disallows native/nonblocking together. Both guard mutations failed at the intended assertion and passed after restoration. Corrected isolated CPU passes completed with stable source hashes and sampler read errors reported, never hidden. Applicable Ruff, format, focused type and 74-test gates pass. The high finding is closed; no live blocking sampler will be used. Overall review remains PENDING for admitted real CUDA/energy evidence and encoder parity.

### ast-checkpoint | low | Independent review passes S02 with timing uncertainty preserved

S02 PASS applies to the unchanged AST candidate `1fc776c0e3d49f8f0ad17afc9cdf2dff07c45f430c08977660e9a57db3d2f69b`. Exact tuple parity covers 820 inputs, including four synthetic cases, at five budgets. Current combined focused pytest passes 83 tests; applicable Ruff/format/focused type gates pass after the energy-addition lint/type corrections. The repeat median-ratio interval 0.9873–1.0409x includes no improvement, so behavior is verified and timing remains a modest observed optimization candidate. No end-to-end indexing or energy gain is claimed. Sequencing now closes this independent CPU checkpoint while retaining required GPU/energy work in S03 and final integrated review in S04.

### sustained-energy-scope | low | Device-wide power estimates need sustained windows and boundary limits

Independent review finds no blocking code defect in the opt-in energy addition. It retains canonical admission, one GPU consumer, synchronization, alternating caps, actual bucket/OOM state and final-only cache release. Power integration covers the actual sampled span and withholds per-item estimates below coverage thresholds. Ada NVML power is a one-second average, so immediate arm transitions can mix prior-arm power into boundary samples. Prefer 30-second sustained windows and disclose this when assessing small differences. Per-item estimates use sampled-span mean power and whole-window throughput, assuming representative power at uncovered edges. They include desktop/background work, adaptive ceilings, synchronization and bookkeeping; they cannot establish model-only energy or end-to-end indexing efficiency. Source: https://docs.nvidia.com/deploy/archive/R550/nvml-api/group__nvmlDeviceQueries.html . Overall remains PENDING for real admitted CUDA/energy, encoder parity and final energy guard/gate evidence.

## Recommendations

S01 correction is ready for its explicit-path checkpoint with verified native provenance and completed CPU sampling. Keep the original externally owned merge untouched. Use canonical borrowing to isolate the pinned new model from the resident old-model service; never bypass active tickets or cancel another session's jobs for evidence. Obtain actual CUDA kernels, synchronized timing, allocated/reserved peaks, sustained device-wide energy and sparse parity before selecting a planner default or closing remaining GPU work. Reuse the exact AST parity and paired measurements, with their modest/noisy limits, for the CPU checkpoint. Completion still requires all remaining Steps and integrated review PASS.
