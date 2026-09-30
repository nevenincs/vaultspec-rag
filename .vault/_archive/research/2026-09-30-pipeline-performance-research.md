---
tags:
  - '#research'
  - '#pipeline-performance'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:0429c186388f5e5eae3b53ac13312f97ffbf17aac17c9b9ece2a7b9cbeaf24f6'
related:
  - "[[2026-09-30-sparseencode-research]]"
  - "[[2026-07-29-encode-batch-adaptivity-research]]"
---

# `pipeline-performance` research: `CPU and CUDA profiling targets after the sparse upgrade`

Rigorous profiling should first attribute the wide sparse vocabulary intermediates, dense library lock scope and CPU chunk/storage work; the existing sparse length-grouping improvement is already landed. Static evidence identifies candidates, not measured improvements. Reproducible CPU samples and CUDA traces will select changes without weakening representation or lifecycle contracts.

## Findings

### Sparse peak demand needs realistic bucket measurements

The reviewed sparse checkpoint has vocabulary width 50,370 and is loaded float32 with SDPA. A hypothetical [32,512,50370] float32 logits tensor alone occupies about 3.07 GiB, before upstream activation intermediates. The pooled result is much smaller. Measure actual operator shapes and peaks for production-like batch caps rather than inferring a leak from driver occupancy. Sources: `src/vaultspec_rag/_sparse_encoder.py:44`, `src/vaultspec_rag/_sparse_profile.py`, and `2026-09-30-sparseencode-research`.

The current sparse planner caps estimated length at 512, so long documents can reach the 32-item caller cap under a 24,000-token budget. The earlier uncapped character estimator could split long inputs below that cap. There is no removed hidden inner cap of eight relative to commit 3311ccdf: both versions explicitly use each bucket's size as the forward batch size, and the configured generic default is 32. An old method docstring describing default eight is stale. Sources: `src/vaultspec_rag/embeddings.py:914`, `:1226`, `src/vaultspec_rag/config/_settings.py:220`, and `git show 3311ccdf:src/vaultspec_rag/embeddings.py`.

### Dense library work exceeds the nominal forward lock

Dense bucket locking encloses the full Sentence Transformers encode call, which includes library tokenization, sorting and postprocessing. Sparse preparation/conversion are already separated from forward locking. CPU samples plus CUDA ranges can establish lock occupancy versus device time, while accepted dense library ownership prevents casually replacing it with a duplicated custom encode loop. Sources: `src/vaultspec_rag/embeddings.py:914`, `:1034`, `:1252`, and `2026-07-29-encode-batch-adaptivity-adr`.

### CPU production already overlaps compute but code storage remains serial

The CPU producer drains FIRST_COMPLETED and refills a bounded submission window; it does not wait in original submission order. Code slices encode, convert, upsert and checkpoint on the one consumer, whereas vault/document paths use the existing bounded slice writer. Adopting that writer for code is a hypothesis requiring measured storage idle time and preservation of confirmed-write/checkpoint ordering. Sources: `src/vaultspec_rag/indexer/_chunk_producer.py:616`, `:663`, `src/vaultspec_rag/indexer/_streaming.py:370`, `:966`, and `2026-07-21-large-index-resilience-adr`.

AST traversal decodes structural child spans before recursively decoding them again; oversized container spans are also decoded before descent. Removing redundant decoding could preserve exact chunk behavior, but CPU profiles must establish its value. Sources: `src/vaultspec_rag/indexer/_ast_chunker.py:220`, `:287`. The canonical CPU producer harness is `src/vaultspec_rag/tests/_chunk_production.py`; existing CPU chunk and end-to-end real-index benchmarks are `bench_codebase_chunking.py` and `bench_large_index_resilience.py` under `src/vaultspec_rag/tests/benchmarks`.

### Profiling and timing answer different questions

Use all-thread and separately GIL-filtered py-spy samples, then short torch CPU/CUDA traces inside the actual consumer. Windows x86-64 native stacks are supported by current py-spy, but idle classification can misclassify blocked I/O and GIL filtering omits native extensions releasing the GIL. A Python stack is not CUDA kernel duration. Check Chrome exports for real kernel events before claiming CUDA attribution; missing CUPTI can leave incomplete device traces. Shape/memory instrumentation adds overhead, so throughput comparisons run separately without profiling.

Synchronize around unprofiled wall-clock runs and use CUDA events when attributing device execution. Reset peak counters without flushing warm caches. Allocated bytes represent live tensors, reserved bytes represent allocator-managed memory, and driver occupancy also includes context/other processes. NVIDIA device utilization has an internal sample period; faster polling can repeat readings, and Windows WDDM process memory can be unavailable. Sources: https://github.com/benfred/py-spy , https://docs.pytorch.org/docs/2.14/profiler.html , https://docs.pytorch.org/docs/2.14/notes/cuda.html , https://docs.nvidia.com/deploy/nvidia-smi/index.html .

### Native profiler provenance precedes execution

The existing operator py-spy binary reports no PE product version, but its bytes contain py-spy0.4.2 and hash to SHA256 6e83ab095f40453742d01a2719a178f308534015da519ec0659d2584139dc995 (4,815,360 bytes). It has not been executed. The official py-spy 0.4.2 Windows wheel has SHA256 8b06a353c177677e4e1701b288d8c58e2f8d4208ee81a8048d9f72ba800918f8. Commit reviewed constants first, verify the archive before extraction, compare its executable bytes, and reverify immediately before launch. Source: https://pypi.org/project/py-spy/0.4.2/ and the read-only local binary digest. The installed torch package includes cupti64_2025.3.0.dll; actual CUDA trace support still requires a runtime check.

### Existing rulings cover compatible tuning

Accepted sparseencode, batching, GPU pipeline/single-owner and large-index-resilience decisions cover measurement, upstream-delegated sparse semantics, canonical dense library encoding, token-budget/OOM recovery and bounded lifetimes. Compatible CPU conversion/chunking or calibrated batch tuning needs no new architecture commitment. Default backend/precision changes, replacement pooling, parallel GPU consumers/streams, resident-reranker eviction or compatibility changes need a separately grounded costly-decision review. Initial hardware validation is CUDA on RTX 4080 SUPER with torch 2.14.0+cu130, Sentence Transformers 6.1.0 and Transformers 5.17.0; no minimum-version or MPS claim follows.

### CPU measurements and retained AST candidate

Initial cProfile: 33 real production Python sources, 564714 UTF-8 bytes, 613 chunks. Ten corpus passes took 1.693 seconds including output-hash serialization. Native parsing consumed 1.209 seconds (about 71% total); bytes decoding consumed 0.041 seconds (about 2.4%). This is Python chunking attribution, not end-to-end indexing or all-language performance. Evidence: ignored `.pytest-tmp/chunk-baseline-profile.txt`, `.pytest-tmp/chunk-baseline.pstats` and `.pytest-tmp/chunk-baseline.json`.

The retained AST candidate defers container decoding and avoids structural-child decoding immediately before recursive collection. Character budgets, chunk text/spans/metadata/order remain unchanged. Exact tuple parity covered 820 Python sources plus Unicode/decorator/oversized edge cases at budgets 40, 80, 512, 1500 and 8000. Focused tests also cover JavaScript, TypeScript, Rust and Go. An initial slower candidate was discarded. The simplified default-budget candidate measured median paired speed ratios 1.04511 over 20 alternating pairs and 1.01035 over 36 repeat pairs; combined descriptive median 1.02293, with 36 of 56 wins. Each arm times three canonical corpus passes without hash serialization. Timing selection also includes synthetic edge cases. Evidence: `.pytest-tmp/chunk-paired-candidate.json` and `.pytest-tmp/chunk-paired-repeat.json`. Repeat parity reuses the unchanged first run (`parity_reused: true`); its empty digest is not a new output digest. These small, noisy CPU results under live service load do not certify the quiet-machine performance lane or a large indexing gain.

### Device observation and blocked inference evidence

Thirty read-only one-second NVML samples showed approximately 4300–4545 MiB used, utilization 0–35%, and 6.9–24.3 W. These device-wide values include desktop/other processes, not RAG-only utilization or isolated encoder demand. Evidence: `.pytest-tmp/live-gpu-observe.json`. Optional operator binding `nvidia-ml-py==13.615.71` was installed; project dependency metadata and installed package version were not synchronized or changed.

Two canonical borrower attempts were refused before model construction because the service retained 11 compute tickets. Ten attempts reported PAUSING; nine had no active worker, while one held pipeline/project/writer resources. Logs showed indexing continued, so no stall or ticket leak is established. Limiter waiters cannot reach cooperative worker checkpoints until admitted. No cancellation, restart, ownership bypass, live rebuild or borrower CUDA allocation occurred. Evidence: `.pytest-tmp/pipeline-gpu-baseline.log`, `.pytest-tmp/pipeline-gpu-baseline-retry.log`, `.pytest-tmp/pausing-jobs.json` and `.pytest-tmp/profile-service-log.json`.

An externally owned origin/main merge remains in progress. Its staged installation/docs/test files were left untouched. The merge prevents the explicit-path Step commit and therefore the required committed-pin boundary for native py-spy execution. The official wheel was downloaded over constrained HTTPS and its archive digest matched the reviewed pin, but no extraction or native execution occurred. Actual py-spy samples, CUDA kernels/peaks, encoder comparisons and sparse parity need a completed pin commit and admitted GPU window. S02 and S03 remain open.

### Sparse memory calibration remains the primary GPU candidate

Cached pinned upstream `modeling_splade.py:67` creates logits; `:68` applies shift/ReLU/log1p, `:71`–`:72` top12 gating, `:106` pooling-mask multiplication, `:107` max pooling. Each [32,512,50370] float32 tensor occupies 3148.125 MiB, while pooled [32,50370] output is about 6.15 MiB. Overlap/peak demand remain unmeasured. Next compare sparse-only padded-token budgets 4096/8192/12288 with current 24000, preserving upstream forward, dtype, attention, folding, independent learned ceilings and bucket-local OOM retry. Full-length buckets would become 8/16/24 rather than 32 items, while short inputs could keep larger batches. No default was changed on geometry alone. CPU sparse extraction and reusing the bounded code-slice writer remain secondary hypotheses needing measured CPU/storage cost and behavior/checkpoint parity.

## Sources

`2026-09-30-sparseencode-research`, `2026-09-30-sparseencode-adr`, `2026-07-29-encode-batch-adaptivity-adr`, `2026-06-02-index-gpu-pipeline-adr`, `2026-07-21-large-index-resilience-adr`, `2026-09-26-gpu-single-owner-adr`.

https://github.com/benfred/py-spy

https://docs.pytorch.org/docs/2.14/profiler.html

https://docs.pytorch.org/docs/2.14/notes/cuda.html

https://docs.nvidia.com/deploy/nvidia-smi/index.html

https://pypi.org/project/py-spy/0.4.2/
