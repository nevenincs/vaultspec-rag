---
tags:
  - '#audit'
  - '#pipeline-performance'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:06033a1f52241eee895377343f912db36ee7b5e5cdd0d313ad8a7511ce058972'
related:
  - "[[2026-09-30-pipeline-performance-plan]]"
  - "[[2026-09-30-sparseencode-adr]]"
  - "[[2026-07-29-encode-batch-adaptivity-adr]]"
  - "[[2026-09-26-gpu-single-owner-adr]]"
  - "[[2026-09-30-pipeline-performance-research]]"
---

# `pipeline-performance` audit: `Profiling harness and CPU optimization review with pending GPU evidence`

## Scope

Independent GPT-6.1 Sol review of S01 and partial S02 against b9d2daf0, including uncommitted profiling-harness and AST changes. Foreign staged origin/main merge changes are excluded. Governing plan: `2026-09-30-pipeline-performance-plan`; sparse, batching and GPU ownership decisions bound the review. Overall verdict PENDING: actual native/CUDA measurements remain unavailable, and borrowed lifetime cleanup is being corrected before the S01 close.

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

## Recommendations

Close the borrowed lifetime finding with consumer-owned teardown and focused passing evidence; then close S01 and make its explicit-path commit after the externally owned merge finishes. Verify the downloaded archive before inspecting its executable member and reverify the operator executable immediately before each launch. Obtain an admitted GPU window for py-spy, actual CUDA traces, sparse-budget comparisons and output parity before choosing a new default or closing S02. Reuse existing applicable checks and the unchanged AST analysis; completion requires the remaining measurements and final review.
