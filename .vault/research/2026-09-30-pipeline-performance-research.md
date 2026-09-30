---
tags:
  - '#research'
  - '#pipeline-performance'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:3fe7981ae639650e7a42bda657bd6c48f3281e9f6e9bfdd28093bc281fa664a1'
related:
  - "[[2026-09-30-sparseencode-research]]"
  - "[[2026-07-29-encode-batch-adaptivity-research]]"
---

# `pipeline-performance` research: `CPU and CUDA profiling targets after the sparse upgrade`

Rigorous profiling should first attribute the wide sparse vocabulary intermediates, dense library lock scope and CPU chunk/storage work; the existing sparse length-grouping improvement is already landed. Static evidence identifies candidates, not measured improvements. Reproducible CPU samples and CUDA traces will select changes without weakening representation or lifecycle contracts.

## Findings

### Sparse peak demand needs realistic bucket measurements

The reviewed sparse checkpoint has vocabulary width 50,370 and is loaded float 32 with SDPA. A hypothetical [32,512,50370] float 32 logits tensor alone occupies about 3.07 GiB, before upstream activation intermediates. The pooled result is much smaller. Measure actual operator shapes and peaks for production-like batch caps rather than inferring a leak from driver occupancy. Sources: `src/vaultspec_rag/_sparse_encoder.py:44`, `src/vaultspec_rag/_sparse_profile.py`, and `2026-09-30-sparseencode-research`.

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

The retained AST candidate defers container decoding and avoids structural-child decoding immediately before recursive collection. Character budgets, chunk text/spans/metadata/order remain unchanged. Exact tuple parity covered 820 inputs including four Unicode/decorator/oversized synthetic cases at budgets 40, 80, 512, 1500 and 8000. Focused tests also cover JavaScript, TypeScript, Rust and Go. An initial slower candidate was discarded. The simplified default-budget candidate measured median paired speed ratios 1.04511 over 20 alternating pairs and 1.01035 over 36 repeat pairs; combined descriptive median 1.02293, with 36 of 56 wins. Each arm times three canonical corpus passes without hash serialization. Timing selection also includes synthetic edge cases. Evidence: `.pytest-tmp/chunk-paired-candidate.json` and `.pytest-tmp/chunk-paired-repeat.json`. Repeat parity reuses the unchanged first run (`parity_reused: true`); its empty digest is not a new output digest. These small, noisy CPU results under live service load do not certify the quiet-machine performance lane or a large indexing gain.

### Device observation and blocked inference evidence

Thirty read-only one-second NVML samples showed approximately 4300–4545 MiB used, utilization 0–35%, and 6.9–24.3 W. These device-wide values include desktop/other processes, not RAG-only utilization or isolated encoder demand. Evidence: `.pytest-tmp/live-gpu-observe.json`. Optional operator binding `nvidia-ml-py==13.615.71` was installed; project dependency metadata and installed package version were not synchronized or changed.

Two canonical borrower attempts were refused before model construction because the service retained 11 compute tickets. Ten attempts reported PAUSING; nine had no active worker, while one held pipeline/project/writer resources. Logs showed indexing continued, so no stall or ticket leak is established. Limiter waiters cannot reach cooperative worker checkpoints until admitted. No cancellation, restart, ownership bypass, live rebuild or borrower CUDA allocation occurred. Evidence: `.pytest-tmp/pipeline-gpu-baseline.log`, `.pytest-tmp/pipeline-gpu-baseline-retry.log`, `.pytest-tmp/pausing-jobs.json` and `.pytest-tmp/profile-service-log.json`.

An externally owned origin/main merge remains in progress. Its staged installation/docs/test files were left untouched. The merge prevents the explicit-path Step commit and therefore the required committed-pin boundary for native py-spy execution. The official wheel was downloaded over constrained HTTPS and its archive digest matched the reviewed pin, but no extraction or native execution occurred. Actual py-spy samples, CUDA kernels/peaks, encoder comparisons and sparse parity need a completed pin commit and admitted GPU window. S02 and S03 remain open.

### Sparse memory calibration remains the primary GPU candidate

Cached pinned upstream `modeling_splade.py:67` creates logits; `:68` applies shift/ReLU/log1p, `:71`–`:72` top12 gating, `:106` pooling-mask multiplication, `:107` max pooling. Each [32,512,50370] float 32 tensor occupies 3148.125 MiB, while pooled [32,50370] output is about 6.15 MiB. Overlap/peak demand remain unmeasured. Next compare sparse-only padded-token budgets 4096/8192/12288 with current 24000, preserving upstream forward, dtype, attention, folding, independent learned ceilings and bucket-local OOM retry. Full-length buckets would become 8/16/24 rather than 32 items, while short inputs could keep larger batches. No default was changed on geometry alone. CPU sparse extraction and reusing the bounded code-slice writer remain secondary hypotheses needing measured CPU/storage cost and behavior/checkpoint parity.

### Execution isolation

The performance lane moved to `Y:/code/vaultspec-rag-worktrees/pipeline-performance` on `feature/pipeline-performance`, based on b9d2daf0, while the externally owned sparseencode merge continues. Only owned profiling tools, records and AST changes were copied; foreign staged installation changes were excluded. Earlier observations retain their original source/corpus hashes and runtime scope. The existing environment is reused through an explicit interpreter/PYTHONPATH without synchronizing installed package metadata. The isolated explicit-path S01 commit now permits verified native CPU sampling. Shared CUDA still requires canonical borrowing; this relocation does not authorize parallel GPU inference.

### Completed CPU stack evidence and native provenance

S01 commit 0550d8f2 established reviewed executable/archive pins. The verified official wheel's single executable member and installed py-spy bytes matched the committed executable digest; each launch was rehashed. Two isolated 30-second native CPU passes collected 2916 all-thread and 2999 GIL-filtered samples with zero sampler errors. The parser call at `_ast_chunker.py:80` accounted for about 90.29% and 91.96% of samples; tree-sitter native frames were present in about 95.16% and 96.17%. These are inclusive sample proportions on the fixed Python corpus, not CPU utilization or GPU kernel timing. Evidence: `.pytest-tmp/pipeline-cpu-pyspy`.

The corrected default uses Python-only nonblocking sampling. Both 30-second passes completed with source stability verified: 2938 samples/10 read errors and 2981 samples/18 read errors, demonstrating the documented partial-read limitation. Evidence: `.pytest-tmp/pipeline-cpu-nonblocking-verified` including manifests, logs, speedscope files and summary. A concurrent guard-mutation run produced incompatible native/nonblocking arguments in an earlier attempt; that failed attempt is excluded from measurement evidence. Existing paired AST evidence and corpus hashes remain unchanged.

### Live sampling interruption and safety correction

A bounded native live diagnostic on the installed 0.5.3 resident service timed out while sampling fell behind. Terminating the blocking profiler left service threads/process suspension outstanding. Recovery revalidated the original PID/creation time, reversed the sampler's outstanding thread/process suspension, and confirmed a fresh managed-service heartbeat, models loaded, admissions running and no suspended threads. There was no restart, job cancellation or index rebuild. Recovery artifacts: `.pytest-tmp/service-thread-recovery.json` and `.pytest-tmp/service-process-recovery.json`.

Default profiling now passes `--nonblocking` and excludes `--native`. Official py-spy 0.4.2 cannot combine these flags; nonblocking reads do not suspend the target and can miss frames. Two guard mutations each produced the intended assertion failure and restored passing test (`.pytest-tmp/profile-nonblocking-proofs.txt`). A subsequent low-rate live nonblocking diagnostic also timed out but did not suspend the service and yielded no accepted stack artifact. Device-wide NVML observations remain observations only. GPU operation attribution belongs to the admitted Torch CUDA trace, not these failed live samples. Sources: https://raw.githubusercontent.com/benfred/py-spy/v0.4.2/src/config.rs and https://raw.githubusercontent.com/benfred/py-spy/v0.4.2/src/python_spy.rs .

### User priorities and runtime separation

The user clarified that indexing time and GPU energy use govern candidate selection, and that another session owns the original merge. The resident GPU service uses another model/runtime. Controlled measurements therefore load the pinned new ModernBERT model from current source only after authenticated borrowing releases resident models, then release benchmark models/cache before the existing resident service resumes. Installed runtime metadata is not upgraded during this handoff. Peak memory is measured alongside throughput and sustained device-wide energy per processed item; a lower memory cap alone does not establish an improvement for the user's priorities.

### CPU checkpoint uncertainty and sequencing

S02 is now the independently verified AST checkpoint; admitted encoder/energy selection remains required in S03, with final integrated review S04. This changes sequencing without removing GPU work. The unchanged AST candidate hash is `1fc776c0e3d49f8f0ad17afc9cdf2dff07c45f430c08977660e9a57db3d2f69b`. Conditional 95% paired-bootstrap median-ratio intervals (10,000 resamples, seed 20260930) are 20 pairs: 1.0205–1.0773x; 36 pairs: 0.9873–1.0409x. The repeat interval includes no gain, so the observed small positive median is descriptive, not a certified performance guarantee. Do not pool these runs into a quiet-machine or end-to-end indexing claim. Evidence: `.pytest-tmp/chunk-timing-uncertainty.json`; raw paired observations and exact parity remain applicable.

### Admitted CUDA baseline and sustained power measurements

The completed authenticated borrower used the current pinned ModernBERT sparse model, float 32 SDPA, and canonical Qwen/Qwen3-Embedding-0.6B dense model, revision 97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3, fp16 SDPA/max length 2048. RTX 4080 SUPER, driver 610.88, torch 2.14.0+cu130; source HEAD fae34944 with fingerprinted energy-harness additions. Source stability passed. The isolated fixed corpus derives 32-item short, long, mixed and token-dense workloads from real Python chunks; it is not an all-language or full indexing corpus. Evidence: `.pytest-tmp/pipeline-gpu-energy-held-jobs/manifest.json`, `model-manifest.json`, `results.json`.

Three rounds per cap, with two warmups, produced 180 synchronized unprofiled observations. Combined median seconds for caps 8/32 were short 0.626/0.245, long 1.712/1.874, mixed 1.655/1.791, token-dense 0.573/0.331. Full-length sparse cap 32 attempts OOM at observed allocated peaks up to 11.06 GiB and replan under 8192 tokens; cap8 sparse peak is about 4.34 GiB. Requested cap 32 often executes learned cap16 after retry. Report individual retry tails and actual buckets, not nominal caps alone. Evidence: `sweep.json`, `sweep-summary.json`.

Twenty-four alternating 30-second combined dense-then-sparse windows have complete power coverage by the harness rule, minimum fraction 0.9406. Median estimated device-wide joules per item for caps 8/32: short 0.478/0.237; long 14.891/15.545; mixed 13.516/14.078; token-dense 1.220/2.608. Corresponding median items/sec: short 50.031/163.944, long 17.909/16.668, mixed 18.265/16.859, token-dense 53.106/93.706. Every long/mixed cap 32 window records one sparse OOM; cap8 records none. Larger item caps are therefore workload dependent, and lower memory alone is not the selection criterion. These are device-wide sustained encoder estimates including desktop/background load, bookkeeping and adaptive history, not model-only or end-to-end indexing energy. Immediate arm boundaries can contain NVML's prior one-second power average. Evidence: `energy-windows.json`, `energy-summary.json`, `nvml.json`.

The separate instrumented trace contains 17052 actual CUDA kernel events. FP16 dense attention operator shapes 9x1771, 12x1427 and 10x1452 account for approximately 700 ms in the two-iteration mixed trace; sparse vocabulary projection `[8192,768]` by `[768,50370]` has substantial cumulative allocations. Instrumented CPU/CUDA totals overlap and cannot rank wall-clock CPU tokenization/conversion costs. Cumulative operator allocation bytes are not peak live memory. Teardown precedes borrower return with 8.125 MiB allocated and 20 MiB reserved. Evidence: `cuda-trace.json`, `operators.txt`, `bucket-tokens.json`, `teardown.json`.

### Job preservation and runtime separation during measurement

The user explicitly authorized cancellation/requeue for benchmarking. Supported graceful desired-PAUSED holds instead preserved six captured running job IDs, specs, dispatcher bindings and durable checkpoints. All six acknowledged pause and released resources before ordinary authenticated borrowing. No service restart, forced handoff, configuration eligibility bypass or package synchronization was used. During the run another actor changed four held jobs to CANCELLED; the supervisor preserved that changed intent. The other two were resumed with fresh revision checks, reconciled under attempt2 and succeeded. Post-run detail confirms no captured job remains in a supervisor-owned pause. The benchmark child exited zero; its supervisor exited one because its conservative restore check treated external control changes as unresolved. Those four external cancellations are not benchmark failures or actions by this supervisor. Evidence: `.pytest-tmp/gpu-job-holds/captured.json`, `holds.json`, `restorations.json`, `post-run-audit.json`, `benchmark.log`.

### Recovery credit and independent sparse tuning

Static inspection and ceiling snapshots reveal `_run_bucketed_encode` currently credits the nominal requested budget after a call, even when all executed buckets are smaller. Sixteen low-load calls can certify an 8192-token ceiling and later promote an unexercised 16384-token probe, rearming a full 32 OOM. Credit the largest successfully executed bucket's estimated padded-token footprint instead; retain successful high-load recovery and bucket-local retry. The independent sparse budget candidate compares 4096/8192/24000 at fixed item cap 32 while preserving dense 24000, pinned upstream model semantics and separate learned ceilings. A provisional 4096 default is not accepted on memory geometry alone; paired throughput, sustained energy, token/score parity and applicable guards determine the final choice. Sources: `src/vaultspec_rag/embeddings.py`, `src/vaultspec_rag/embeddings.py:168`, and the admitted baseline ceiling/OOM observations above.

### CPU worker scaling near the automatic threshold

The shipped CPU chunk producer processed 644 real production Python files repeated under unique paths, 10860080 bytes, with cold spawned pools and full CodeChunk DTO parity. Three randomized rounds gave median seconds for 1/2/4/8/24 workers: 2.8055/2.8294/1.7501/1.8117/3.9762. All 11800 chunks share output digest eca7f2bc52c5bc01c05dfd09eec776fdff17e4de8b66476d95bfaa9f9250a014. Parent stayed torch-free and source stability passed. Auto selects all24 logical CPUs just beyond its 8 MiB gate; here four workers were approximately 2.27x faster than24 for the CPU stage. This small three-round copied-source experiment does not establish full indexing or energy gains, nor a universal new automatic policy. A larger frozen test-source holdout follows before making a policy recommendation. Evidence: `.pytest-tmp/chunk-worker-scaling-verified`.

### Actual-load recovery refinement and preflight evidence

Independent review found that exact ceiling equality could prevent recovery under discrete packing: an OOM footprint900 learns450, while 100-token items pack four to400. Recovery now qualifies an actual successful footprint when less than one exercised item's padded-token size remains at the current ceiling. The inequality is strict:400+50==450 leaves room and earns no credit. Only an actual successful footprint above the ceiling promotes it. The item quantum belongs to the same largest successful bucket, and both observations reset after OOM; earlier large prefixes cannot undo new backoff. At768, a512-token singleton may earn a bounded probe after sustained packing-saturated success, but cannot promote that probe merely because the requested budget is1536. Sources: `src/vaultspec_rag/embeddings.py:384`, `:988`, and focused bucket-planner guards.

Final preflight passed 253 focused tests covering planner/config/harness/AST/configuration documentation/central environment ownership, full Ruff,917-file format check, focused type checks and docs/feature conformance. A test-local list type annotation fixed three invariant-generic type diagnostics without changing behavior. Four original encoder guards plus17 final recovery/comparison/argument guards were mutation-proven at intended assertions, restored and passed. Finite/nonnegative weight and finite dot-score guards reject matching invalid values before timed windows; invalid dot payloads serialize as null. Existing energy, teardown and native-provenance proof evidence remains applicable to unchanged guards. Artifacts: `.pytest-tmp/s03-focused-gates.log`, `encoder-tuning-guard-proofs.txt`, `final-profile-guard-proofs.txt`. Source is frozen before candidate GPU allocation;4096 remains a candidate awaiting measurements.

### Larger CPU holdout changes the preferred worker count

The larger frozen holdout repeats493 real test Python sources under unique paths:3451 files,45880842 bytes,49462 full chunk DTOs. Three randomized rounds yielded median seconds for4/8/12/24 workers:12.3821/10.8928/9.3689/14.0643. Full output parity digest1839197719e3bf74013bcd5596a5898492fd90537d46d1aef4b98f528740969b held across all arms; the parent stayed torch-free. Twelve workers were approximately1.50x faster than24 for this stage, while the smaller production corpus favored four. Individual noisy observations and copied Python corpora do not support a universal automatic worker cap or full-index/energy claim. No worker policy default changed. Artifact: `.pytest-tmp/chunk-worker-scaling-holdout`.

### Clean publication explains the second handoff delay

Two later running CLI rebuild jobs in `Y:/code/cadrumo-worktrees/mcp` did not acknowledge script-owned PAUSED holds within240seconds. Both holds were withdrawn successfully, with original desired RUNNING restored. The user-approved cancellation/requeue path then captured and requested cancellation of only those exact two IDs/specs/attempts, recording fresh revision checks and owned request timestamps. Pending cancellation cannot be reversed by RUNNING; terminal acknowledgement is required for canonical retry with immutable parent lineage and identical rebuild authority/spec. Supervisor artifacts: `.pytest-tmp/gpu-job-holds-budget-comparison`, `.pytest-tmp/gpu-owned-cancellation-comparison`.

Installed0.5.3 and current dispatcher paths pass `clean=not resumed` for fresh code/document rebuilds. The shared control token protects the entire clean publication from collection preparation through indexing, ingest barrier, stale reconciliation and valid metadata publication. Checkpoints intentionally defer pause/cancel throughout that protected interval; continued progress is not a token leak or ignored control. The capacity waiter should observe cancellation at its entry checkpoint after admission. The1200-second supervisor observation bound is not an API guarantee. Root continues waiting for acknowledged resource release before normal authenticated borrowing. Sources: `src/vaultspec_rag/job_dispatch.py:281`, `src/vaultspec_rag/indexer/_codebase_indexer.py:705`, `src/vaultspec_rag/indexer/_document_indexer.py:1222`, `src/vaultspec_rag/job_control.py`, and accepted large-index-resilience coverage. Reducing this control latency would require revisiting clean-publication safety, potentially verified shadow publication; it is a separate costly-decision opportunity.

### Strict parity rejects the smaller sparse budget

The first candidate run stopped before all timed windows because 4096 failed the unchanged rtol=1e-4/atol=1e-5 document-weight comparison. All 384 document comparisons and 12 query comparisons preserved sparse coordinates and finite nonnegative weights. All query vectors were bit-identical and all query-document score comparisons passed. Nevertheless, 4096 failed 46 document comparisons: long 27/32 (maximum absolute drift 3.1211413443e-5), mixed 16/32 (2.3424625397e-5), token-dense 3/32 (2.3081898689e-5). Short vectors were bit-identical. Per-arm records exactly match aggregate records. Shape-dependent float 32 drift is plausible but raw vectors were not retained, so its cause and maximum relative weight error are unproved. No tolerance was relaxed.

8192 and 24000 document and query vectors were bit-identical to the reference across all four workloads. For long/mixed content, the reference first OOMed at 32 items and then succeeded at 16+16; 8192 executes 16+16 without that failed attempt. The failed run's source/corpus hashes were independently verified unchanged; teardown left 8.125 MiB allocated and 20 MiB reserved. Evidence: `.pytest-tmp/pipeline-sparse-budget-comparison/sparse-budget-parity.json`, per-arm records, `source-stability-after-parity-failure.json`, `teardown.json`. The failed comparison provides no energy evidence. The provisional 4096 default was replaced by an 8192 candidate; final selection requires paired measurements against 24000 under the same corrected accounting code.

### Owned cancellations reconciled through retry lineage

The user explicitly authorized cancelling and requeuing pending work for benchmarking. Only the two captured rebuild jobs for `Y:/code/cadrumo-worktrees/mcp` were cancelled. Both acknowledged terminal cancellation and released resources before the normal authenticated borrower started. The document retry child is `b3993831-61b4-4037-8f20-254ea8e03fc8` (parent `a9b5a6ea-cf1e-4634-8e30-198994123df4`), and code child is `24d038a6-66e1-4eb9-81ba-2166088d238a` (parent `ad1d758f-3d5e-41cd-a9db-7f8d89fd64e7`). Fresh canonical detail reads prove identical original specifications, parent lineage and desired running state; the document child has succeeded and the code child is advancing. The code retry HTTP response timed out after creation, so response failure was reconciled against server state rather than treated as failure to create a child. Evidence: `.pytest-tmp/gpu-owned-cancellation-comparison/requeue-reconciliation.json`, `retry-before-list.json`, `code-retry-reconciliation-response.json`, `service-restored.json`. The resident identity remains PID 60756; no package metadata, model configuration or service process was replaced.

### Publication metadata is a separate profiling opportunity

The clean rebuild's protected publication interval includes final metadata, so graceful pause/cancel acknowledgement is deliberately deferred until its exit. The visible `write metadata` counter is only 0/1. Within it, route migration purges stale/rejected Qdrant points through bounded paging, checkpoint proof/ledger work seals publication, served-generation bindings and destination evidence are reconciled, and prior compatible ledger rows are compacted before readiness publication. Pipeline joins and initial ingest barrier precede this label; it is not evidence of another full-root discovery scan. Sources: `indexer/_generation_lifecycle.py:314`, `_route_migration.py:593`, `_checkpoint_common.py:373` and `:603`; clean protected intervals in `_codebase_indexer.py:705` and `_document_indexer.py:1222`. Cancellation acknowledgement took several minutes in this phase. Profile route paging/evidence validation and ledger proof/compaction as distinct subphases before changing them. Shrinking the protection interval or adopting shadow publication requires decision coverage; no control or publication semantics were changed here.

### Completed paired comparison and conservative selection

The second normal authenticated borrower completed successfully after both requeued rebuilds naturally succeeded. It measured 24 alternating 30-second combined dense-then-sparse windows (three pairs per workload), with a fixed item cap 32 and dense budget 24000. Each arm received a fresh sparse ceiling and two warmups; dense adaptive state and allocator history persisted. All eight fresh sparse document/query/score parity comparisons passed, all power windows met coverage requirements (minimum0.939571), and source/corpus hashes remained unchanged. Evidence: `.pytest-tmp/pipeline-sparse-budget-passing-comparison/manifest.json`, `model-manifest.json`, `results.json`, `sparse-budget-parity.json`, `sparse-budget-windows.json`, `sparse-budget-summary.json`; per-window records persist independently.

The table reports the median of three paired reductions for 8192 relative to 24000. Positive means less time or estimated device-wide energy per item. These are descriptive encoder observations, not significance tests or end-to-end indexing measurements.

| Workload    | Time per item reduction | Energy per item reduction | Timed sparse OOMs 8192/24000 |
| ----------- | ----------------------: | ------------------------: | ---------------------------: |
| Short       |                   2.70% |                    -9.33% |                          0/0 |
| Long        |                   1.44% |                     1.19% |                          0/3 |
| Mixed       |                   1.77% |                     1.43% |                          0/3 |
| Token-dense |                   0.70% |                     0.22% |                          0/0 |

All three mixed pairs improved time (1.50–2.82%) and energy (1.15–3.53%). Long time ranges from -0.13% to1.76%, and energy improves0.75–2.71%. All three short energy pairs regress6.25–10.44%, despite identical 32-item batches and bit-identical vectors. Identical shapes do not invalidate that observation; its cause remains unresolved. Short time varies -4.27% to5.78%; token-dense energy varies -0.14% to2.73%. Raw per-round values, medians and actual bucket histograms remain in the summary. Arm medians and paired-ratio medians are different estimators and must not be substituted for one another.

The 8192 arm has no timed or warmup sparse OOM on any workload. Every long/mixed reference window has one timed sparse OOM, and its warmup records at least one cumulative OOM. No dense OOM is recorded. Both arms have identical peak live CUDA allocation by workload:2.171 GiB short,6.835 GiB long/mixed,6.484 GiB token-dense. Reserved peaks remain about8.0 GiB and reflect retained allocator history. Failed allocation requests are not included as allocated memory, and removing retries does not establish a measured reduction in live peak memory.

Final selection keeps 24000 as the default of the new independent sparse budget.8192 is exposed as opt-in tuning for workloads resembling the tested long/mixed corpus, with time/power measurement advised. This ships independent calibration and corrected actual-load recovery without asserting universal energy improvement. The 4096 arm remains rejected under the unchanged weight tolerance. Independent GPT-6.1 Sol review recommended this conservative selection; a short-only repeat or randomized/A–A control is optional follow-up research, not repeated testing until a favorable result appears. Any later default promotion needs reproducible evidence explaining or removing the regression under a prespecified comparison.

The completed run profiled an 8192-configured instance. After source freeze ended, only the default value/assertion and user documentation changed to 24000; both measured arms explicitly override that default. Encoder/accounting/model/harness code is unchanged from the frozen comparison. Fresh full lint/917-file format/focused eight-file type checks and 94 affected configuration/documentation/environment tests passed. The remaining planner/harness/AST coverage reuses the applicable 253-test preflight and restored mutation proofs; no new GPU run is justified by this default-only selection.

### Successful encoder stacks and actual transfer timing

After the unprofiled energy windows, the same owned GPU process completed two separate 30-second100 Hz nonblocking py-spy recordings. The all-thread recording has 2219 samples and 73 read errors; its GPU consumer contributes 2218 samples/22.18s sampled weight. The GIL recording has 261 samples and 21 errors, all on that consumer. Partial-read errors are retained. GIL-filtered observations are a narrower population, and sample weight is neither CPU utilization nor total GPU runtime.

In all-thread consumer leaf samples, SentenceTransformers `batch_to_device` accounts for38.14%, the dense output CPU conversion for18.35%, and sparse batch CPU conversion for12.35%. Those are Python-frame residence measurements and can include waiting for prior asynchronous CUDA work. The existing separate mixed CUDA trace contains 74 device-copy events totaling approximately3.498 ms (HtoD0.180 ms, pinned DtoH0.026 ms, DtoD0.077 ms, pageable DtoH3.215 ms), while 74 CPU `cudaMemcpyAsync` events total215.093 ms. Their differing populations/timing do not establish host-transfer bandwidth as the dominant cost. GIL leaf observations include tensor construction12.64% and tokenizer flattening6.51% of GIL samples; they are not those percentages of indexing wall time. Evidence: `encoder.speedscope.json`, `encoder.speedscope.log`, `encoder-gil.speedscope.json`, `encoder-gil.speedscope.log`, `encoder-stack-summary.json`, and `.pytest-tmp/pipeline-gpu-energy-held-jobs/cuda-transfer-summary.json`.

### Final operational outcome and next profiling targets

Teardown completed before borrower return with8.125 MiB allocated and20 MiB reserved. Fresh canonical service records show the original resident PID 60756 running, admissions open, no borrower bound and no active compute tickets. Both owned retry children succeeded with identical original specifications and parent lineage, and all index/project/writer/pipeline resources are released. No cancellation/requeue remains unresolved. Evidence: `.pytest-tmp/gpu-owned-cancellation-comparison/final-restoration.json` and `.pytest-tmp/gpu-passing-budget-supervisor-final/exit.json`.

Next targets remain evidence-backed opportunities rather than shipped policies: dense padded-attention calibration (baseline long dense cap4 about 1.117 s versus cap 32 about 1.405 s), workload-sensitive spawned CPU worker counts (12 versus 24 about 1.50x in the larger holdout), and publication metadata subphase profiling. The AST optimization preserves exact chunk behavior but its repeat timing interval includes no gain. Conversion-frame residence cannot justify an asynchronous-transfer or GPU-stream change. CPU-produce/GPU-consume overlap and bounded writer behavior remain canonical; backend, precision, pooling, reranker lifetime or publication-protection changes need decision coverage and separate validation.

## Sources

`2026-09-30-sparseencode-research`, `2026-09-30-sparseencode-adr`, `2026-07-29-encode-batch-adaptivity-adr`, `2026-06-02-index-gpu-pipeline-adr`, `2026-07-21-large-index-resilience-adr`, `2026-09-26-gpu-single-owner-adr`.

https://github.com/benfred/py-spy

https://docs.pytorch.org/docs/2.14/profiler.html

https://docs.pytorch.org/docs/2.14/notes/cuda.html

https://docs.nvidia.com/deploy/nvidia-smi/index.html

https://pypi.org/project/py-spy/0.4.2/
