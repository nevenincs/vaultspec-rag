---
tags:
  - '#audit'
  - '#pipeline-performance'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:0d44b802e2ba1253a9fba56b25ab5da9bec66c736f0eba50ad09dfc971dc757f'
related:
  - "[[2026-09-30-pipeline-performance-plan]]"
  - "[[2026-09-30-sparseencode-adr]]"
  - "[[2026-07-29-encode-batch-adaptivity-adr]]"
  - "[[2026-09-26-gpu-single-owner-adr]]"
  - "[[2026-09-30-pipeline-performance-research]]"
---

# `pipeline-performance` audit: `Profiling, encoder tuning and integrated review`

## Scope

Independent GPT-6.1 Sol integrated review of completed S01–S03, base b9d2daf0 through 66c8b9c0, with S04 recording the final review and completion. Governing plan: `2026-09-30-pipeline-performance-plan`; accepted sparse representation, adaptive batching, single GPU owner, producer/consumer pipeline and resilient publication decisions bound the work. The original externally owned sparseencode merge is excluded. Overall verdict PASS: required source/behavior checks, admitted CUDA and sustained paired energy evidence, strict selected-arm parity, nonblocking owned-process sampling, final documentation and exact-spec runtime restoration are complete. No unresolved blocking finding remains. Historical pending/failure entries below retain their original context and later closures.

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

### admitted-cuda-baseline | low | Real kernel and sustained-energy evidence is complete

Independent GPT-6.1 Sol review accepts the admitted baseline. Source stability passed, 17052 CUDA kernel events are present, all24 sustained windows meet coverage thresholds, and consumer teardown precedes resident restoration. Measured caps expose workload-dependent speed/energy and repeated full-length sparse OOMs. Child benchmark success is separate from the supervisor's conservative external-control skip exit: post-run detail proves two owned holds resumed/succeeded and four externally cancelled jobs were preserved, with no owned pause left. Evidence and numerical findings live in `2026-09-30-pipeline-performance-research`. Candidate selection, actual encoder parity and final gates remain outstanding.

### recovery-credit | medium | Nominal budget success can certify unexercised loads

The canonical encoder credits requested budget after successful calls even when observed successful buckets are smaller. Low-load successes can accumulate recovery credit or promote a probe never exercised, matching rearmed long/mixed OOMs in the baseline. S03 must credit actual successful estimated padded-token load, prove low-load calls cannot rearm/promote an unexercised probe, and retain successful full-load recovery. Independent sparse-budget calibration must preserve dense behavior, upstream math, separate ceilings, OOM/progress ordering and output semantics.

### recovery-packing | high | Exact ceiling credit can prevent recovery for non-divisible buckets

Independent pre-GPU review identified unavoidable packing slack: a450-token learned ceiling with 100-token items executes400, never reaching the original equality check. This can permanently pin recovery even after pressure clears. S03 requires justified packing slack while retaining actual-only promotion and low-load rejection.

### recovery-packing-closure | low | Exercised item quantum restores bounded recovery

Independent GPT-6.1 Sol re-review closes the high finding. Qualification uses strictly less than one exercised item's headroom; promotion uses only actual larger load. Quantum and footprint come from the same largest successful bucket and reset after OOM. Intended mutation failures and restored passes cover non-divisible packing, exact headroom, low-load calls, undersized probes and successful-prefix backoff. Finite/nonnegative vector and finite dot-score parity guards also close the pre-GPU validation gap. Applicable 253-test/lint/format/type/docs gates pass. Quantitative details and artifact homes live in `2026-09-30-pipeline-performance-research`; real candidate performance/energy/parity remain required before selecting 4096 or closing S03.

### Sparse candidate selection | high | 4096 fails strict document-weight parity

Independent payload inspection confirmed 4096 weight failures despite exact coordinates and passing query/document scores. The harness correctly persisted evidence and stopped before energy windows. Shipping the provisional 4096 default would lack required parity evidence. No tolerance relaxation is authorized.

### Sparse candidate selection closure | low | Failed arm excluded from the next comparison

The provisional configuration/default assertion/documentation now use 8192, which is bit-identical to reference vectors on all four workloads. Ninety-four affected config/documentation/environment tests, full lint/format, explicit-environment focused type checking and documentation formatting passed. Final selection remains pending paired 8192/24000 timing, power coverage, retry and sampling evidence. The historical 4096 run remains a failed experiment, not performance evidence.

### Retry response reconciliation | low | Both owned jobs have valid retry children

The supervisor reported one retry HTTP failure, but fresh server records show the child was created with identical specification and parent lineage. Both cancellations are reconciled; the document child succeeded and the code child is running with desired running state. A repeated canonical retry request also timed out; no duplicate child is claimed or intentionally created. Current comparison waits for natural completion and applies no new job controls. Benchmark outcome and job restoration are recorded separately.

### Candidate measurement | low | Paired parity and sustained windows complete

The fresh 8192/24000 comparison completed with24 valid windows, minimum power coverage0.9396, eight passing bit-identical sparse parity comparisons, stable source/corpus hashes, successful nonblocking owned-process all-thread/GIL sampling, and consumer teardown before resident restoration. Sampling errors 73/21 remain disclosed. The same corrected accounting code was used for both arms. No general peak-memory or end-to-end indexing improvement is established.

### Default selection | medium | Short energy regression prevents universal promotion

8192 avoids six timed long/mixed sparse OOMs and yields small paired time/energy improvements there. All three short pairs consume6.25–10.44% more device-wide energy per item despite identical batch shapes. Its cause remains unresolved. User priority is indexing time and GPU energy, so final implementation retains 24000 as the sparse default and exposes 8192 as opt-in workload-specific tuning. Independent reviewers recommend this selection. The former provisional 8192 default is withdrawn;4096 remains rejected. A repeat could investigate environmental/order controls but is not required to ship the conservative option.

### Recovery-credit closure | low | Actual-load accounting is verified

The canonical planner now credits the largest successfully exercised bucket and its own item quantum, resets both after OOM, prevents low-load calls from certifying unexercised probes, and permits discrete packing recovery. Independent high-finding closures, intended mutation failures/restored passes and applicable 253-test preflight remain valid. Final default selection passed fresh full lint/917-file format/eight-file type gates and 94 config/documentation/environment tests. Remaining final review concerns are record conformance and integrated completion; no code blocker is identified.

### Runtime restoration closure | low | Both owned retries succeeded and service resumed

Fresh canonical records prove both exact-spec retry children succeeded and released resources. Original PID 60756 has admissions open, no borrower bound and zero active compute tickets after the successful comparison. The first retry timeout was reconciled against created-child identity. No owned hold or cancellation remains unresolved; external controls and the original foreign merge were preserved.

### Integrated final review | low | PASS for S01–S03 and S04 completion

Independent GPT-6.1 Sol final review passes base b9d2daf0 through 66c8b9c0 with no unresolved blocking finding. The selected implementation keeps the 24000 default, exposes 8192 as workload-specific opt-in tuning, and rejects 4096 without relaxing parity. Actual-load recovery and packing slack retain independent ceilings, canonical model semantics and input/progress/OOM behavior. Normal authenticated borrowing uses one dedicated consumer and teardown before resident restoration. Original merge ownership and concurrent operator intent remain preserved.

Applicable verification includes 253 preflight tests plus 94 final affected tests, intended guard mutation failures/restored passes, full Ruff/917-file format/eight-file type checks, Markdown/feature conformance, exact 820-input AST parity, admitted 17052-kernel CUDA trace, 24 valid alternating paired windows, eight bit-identical sparse parity comparisons, successful all-thread/GIL nonblocking artifacts, unchanged measurement hashes and final restoration evidence proving both owned retry children succeeded. The supplementary selection helper's corrected import and actual passed rerun are recorded in the ledger; failed experiments remain historical evidence, not checks of the shipped selection.

Small descriptive timing/energy effects, the unresolved short-input device-wide energy regression, unchanged measured live peak allocation, sampler partial-read errors, Python-focused corpus and retained adaptive/allocator history remain explicit limits. This review establishes no end-to-end indexing or universal energy gain. Future worker sizing, dense attention/padding and publication metadata changes require their own measured validation; no further work is required to complete this approved plan.

### Publication verification | medium | Harness unit substitutions lacked the required declaration

Broader publication checks found that the CPU profiling-harness tests introduced seventeen substitution sites without their required explicit policy justification. The substitution-discipline guard correctly failed on the undeclared file. S04 reopened for this verification correction. No production, model, GPU ownership, profiler or measurement behavior changed, and the prior numerical evidence remains applicable.

### Publication verification closure | low | Exact reviewed unit boundaries retain count-growth protection

The existing guard explicitly permits reviewed sites through its bounded allowance table. The new entry records exactly seventeen existing harness unit seams and why deterministic native-admission, teardown/failure, scheduling, argument and parity barriers need them. It does not change the scanner, unexpected-file rejection, growth assertions or stale-allowance checks. Native execution, real CUDA/energy measurements and profiler artifacts remain separate actual evidence. Reducing the allowance to sixteen produced the intended count-growth failure; byte restoration and the two guard tests passed. Final combined guard/harness tests pass 52, full Ruff/917-file format and focused type checks pass. Artifacts: `.pytest-tmp/harness-substitution-bound-failure.log`, `harness-substitution-bound-restored.log`, `push-final-policy-harness-gates.log`.

Independent GPT-6.1 Sol review PASS covers this correction from 850a5b0d through the working tree. It confirms that the entry uses the guard's existing documented review mechanism without exempting future sites or weakening runtime evidence. File-level counts cannot detect replacement of an allowed site at unchanged count; this is the existing policy limitation, not a new bypass. S04 closes again after applicable conformance and document checks. The original other-session merge remains excluded from this branch.

## Recommendations

Keep 24000 as the default and measure time/power before applying 8192 to long/mixed workloads. Use the recorded raw pairs, warmup/actual bucket and OOM evidence when evaluating follow-up tuning. Dense attention/padding, workload-sensitive CPU worker allocation and publication metadata subphases are the next profiling targets. Preserve canonical GPU and publication constraints; the approved performance plan and independent review are complete.
