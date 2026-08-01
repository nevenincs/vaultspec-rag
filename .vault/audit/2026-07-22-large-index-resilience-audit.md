---
tags:
  - '#audit'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:495f0145a92a19e150f1fe94a40a94ad5cd78fb430f196fb71e776b997295b5a'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `large-index-resilience` audit: `Final implementation review`

## Scope

Reviewed commit `994ce2d00e2bab7422da5a641b83510f5241bec2` and the
current checkpoint, retry, finalization, service-operability, GPU-discipline,
and acceptance paths against the accepted research, ADR, implementation plan,
repository rules, and audit template. The review covered bounded producer and
consumer shutdown, storage-before-ledger ordering, replay granularity,
no-progress enforcement, finalization cost, canonical service projections,
single-consumer GPU locking, and real-behavior test integrity.

## Findings

### replay-granularity | medium | One store mutation can leave many ledger units to replay

`CodebaseIndexer._spawn_weighted_consumer` now passes all chunks from a
`WeightedCodeSlice` to one synchronous store upsert, then calls
`CodeRunCheckpoint.record_confirmed_segment` separately for every segment in
that slice. A process loss after the upsert and before or during that loop can
therefore leave multiple storage-confirmed file segments absent from the
ledger. The compatible retry safely re-upserts stable IDs, but it can replay
every unrecorded segment in the slice rather than at most the single
architecture-defined commit unit. The new small-file batching test proves that
multiple file segments share one store mutation, but no interruption test
covers the gap between that mutation and the sequence of ledger transactions.

### resilience-projection | medium | Canonical job snapshots omit the decided resilience state

The service-domain `JobSnapshot` and `JobResourceSnapshot` expose lifecycle,
point-in-time start and finish memory, and resource ownership, but they carry
no generation ID, committed or replayed units, checkpoint compatibility, last
durable progress, retry or circuit state, memory peaks or ceilings, selected
profile, or typed resilience outcome. `jobs.resource_snapshot` likewise
samples only current RSS and CUDA values. Consequently jobs, health, and CLI
cannot project one canonical checkpoint, retry, circuit, memory, and admission
account as required by ADR D8; the corresponding P09 and P11 plan steps remain
open.

### finalization-liveness | high | Large-run reconciliation is neither scale-bounded nor deadline-aware

Commit `994ce2d0` invokes `reconcile_generation_storage` before every code
generation publication. Its same-kind purge classifies each stored point and
calls `_ledger_file_state`, which starts a fresh ordered iteration of the
generation's file-state rows for that point. At the supported floor this can
degrade toward point-count times file-count ledger work. The subsequent
cross-kind reconciliation also performs at least one opposite-collection
lookup per converged file. Neither loop receives the `RunPolicy`, polls a safe
point, clamps storage work to the remaining no-progress budget, or records a
durable finalization phase. A large run can therefore finish ingestion and
then spend an unbounded period in reconciliation, ignoring cancellation and
the no-progress deadline and repeating the same work on resume before metadata
publication.

### acceptance-floor | high | The declared large-corpus completion gate has not been exercised

The new harness defaults to the required 83,624-file and 250,872-chunk corpus,
but the committed automated evidence only runs production indexing at 192 and
384 files for N/two-N memory comparison and at 256 files for search headroom.
The previously recorded 250,872-chunk evidence exercises the producer,
segmenter, queue, and slice packer without model forwards, checkpoint writes,
finalization, or the real backend. There is no retained report from a complete
default harness run, and plan steps S44 through S47 plus the final W05 matrix
remain open. The managed-service completion floor, real-CUDA high-water at
representative scale, concurrent search headroom across a sustained index,
and the newly activated finalization path are therefore not acceptance-proven.

## Recommendations

- Restore one-to-one storage mutation and ledger commit-unit recovery, or add a
  transactional ledger representation whose replay guarantee explicitly
  matches the bounded multi-segment store mutation, then interrupt that exact
  post-store boundary with real storage.
- Replace per-point file-state rescans with a bounded merge or indexed lookup,
  batch cross-kind ownership checks, and thread `RunPolicy` checkpoints and
  durable phase transitions through all reconciliation work.
- Project generation, checkpoint, replay, deadline, retry, circuit, memory
  high-water and ceilings, profile, and typed terminal state from the service
  domain to every adapter without recomputing policy.
- Keep the feature open until the default real-backend harness completes the
  declared floor, N/two-N and concurrent-search CUDA evidence is retained, and
  focused, full-suite, lint, type, and policy gates pass.

## Resolution review

### replay-granularity | resolved | Store mutation and ledger recovery now share one atomic boundary

Commit `a1846ff0` records every segment unit covered by one bounded weighted
upsert in a single SQLite transaction and advances durable progress once for
that store mutation. The interruption regression exercises rollback at the
post-store checkpoint boundary against the production ledger and confirms that
recovery observes either the complete bounded mutation or none of it. The
focused checkpoint and ledger verification passed 18 CPU tests.

### resilience-projection | resolved | Canonical snapshots now own one persisted resilience account

Commit `c5a8ab8e` adds the service-owned resilience value to `JobSnapshot`,
persists and restores it, and restricts live updates to the exact task-owned
attempt. Terminal watcher settlement may update only the exact retained
attempt, so durable retry and circuit truth cannot be attached to stale work.
Code and document dispatch publish admission ceilings and profile before model
loading, then publish generation, commit, replay, no-progress, memory, and
terminal evidence from the actual checkpoint. Watcher-owned jobs merge the
same checkpoint account with persistent circuit and retry state. Job routes,
domain status, health, and CLI consume the canonical nested object without
recomputing policy; the CLI renders checkpoint compatibility, replay, deadline,
retry, circuit, RSS and CUDA high-water and ceilings, profile, and outcome.

The focused real-manager test proves exact task ownership, terminal-attempt
ownership, atomic filesystem persistence and restore, identical status and CLI
input, circuit settlement, and value validation without substitutes. Ruff,
formatting, and Ty passed for all 14 changed source and test files; the focused
CPU run passed 3 tests.

### finalization-liveness | resolved | Reconciliation is paged, indexed, and deadline-aware

Commit `5def952b` replaces repeated file-state rescans with indexed batch
lookups, replaces per-file opposite-collection queries with one paged scan, and
threads `RunPolicy` checkpoints through scanning, journaling, deletion, and
replay. Commit `a4d73d70` retains the last confirmed route owner while rejecting
newer incomplete or not-routed observations, caches bounded destination
evidence, and checkpoints each bounded retrieval page. The real-store route
verification passed 5 CPU tests with the GPU-only case deselected. Independent
re-review found no remaining low-or-higher correctness or liveness issue in the
finalization path.

### acceptance-floor | open | Full-scale backend and GPU evidence is still required

The code remediations above do not satisfy the declared acceptance floor.
There is still no retained successful default 83,624-file and 250,872-chunk
production run, representative real-CUDA N/two-N report, or sustained
concurrent-search headroom report. The attempted repository commit gate passed
Ruff, formatting, and Ty but failed the repository-wide complexity baseline on
existing blocks, so the complete policy gate is also not green. This high
finding remains open together with plan steps S44 through S51; it must not be
closed from reduced CPU evidence.

## Final review outcome

Independent review against ADR decisions D3 through D8 and the four original
findings found no remaining low-or-higher issue in replay granularity,
finalization liveness, or canonical resilience projection. The implementation
remediation is complete in commits `5def952b`, `a1846ff0`, `a4d73d70`, and
`c5a8ab8e`. The feature as a whole remains open solely on the explicit
acceptance-floor finding and its real-backend, GPU, full-suite, and policy-gate
evidence.

## Post-implementation re-review

Re-reviewed commits `54df3b01` through `2c325eb8` against ADR decisions D4,
D5, D7, and D8, the approved implementation plan, repository GPU and storage
rules, and the real-behavior test policy. The focused CPU verification passed
131 tests. A cumulative changed-test scan found no newly added patching,
monkeypatching, fake or stub classes, skips, xfails, or tautological assertions.
The behavior-preserving policy, route-validation, CLI-outcome, health-projection,
and test-phase extractions introduced no additional low-or-higher finding.

### memory-budget-enforcement | high | CUDA ceilings do not govern the forward lifetime

The admitted code budget samples before an encode/store slice and only after
the synchronous store operation returns. Although the streaming helper already
has an after-encode callback boundary outside the GPU lock, the code path does
not use it for `MemoryBudget`. Its reported CUDA high-water is therefore only
the maximum of sparse point-in-time samples, not the allocator high-water, and
a transient allocated or reserved breach can disappear before the next sample.
A persistent allocator OOM at batch size one also propagates as the raw Torch
exception instead of `cuda_memory_ceiling`. In addition,
`index_cuda_allocator_fraction` is validated and exposed but is never applied
to Torch before model loading, so the process-wide headroom decision is not
enforced. The CUDA regression lowers the ceiling below the already-allocated
baseline and asserts failure at `before code dispatch`; it does not exercise a
forward, after-forward measurement, allocator OOM translation, or cleanup after
a mid-slice ceiling breach.

### document-resilience-parity | high | Document jobs advertise ceilings they do not enforce or measure

Document dispatch publishes profile ceilings before model loading, but
`DocumentIndexer` does not create the production `MemoryBudget`, does not clamp
those ceilings with operator configuration, and does not expose a memory-budget
snapshot. Its separate resource counter compares only against profile bytes,
classifies RSS or CUDA excess as `corpus_limit_exceeded`, and tracks reserved
CUDA without allocated CUDA. The canonical projection then emits all document
RSS and CUDA peaks as null while retaining the advertised ceilings. The adapter
parity test proves that a manually seeded resilience object survives HTTP,
health, and CLI transport; it does not prove that document execution produces
that object. Operators can consequently receive a canonical-looking account
whose ceilings and typed outcomes are not the policy the document run used.

### document-write-deadline | high | A blocked local document write can outlive the run deadline

The bounded local point-write lock is used only by code upserts. The document
indexer calls `encode_and_upsert_document_slice` without its checkpoint's
`StoreWritePolicy`, and document upserts still acquire the ordinary blocking
collection lock before entering the retry helper. A competing local operation
can therefore retain the vector-bearing document slice, document writer
authority, and job attempt beyond the durable no-progress deadline. The new
real blocked-write regression covers code only, so it cannot demonstrate
bounded document unwind or truthful cancellation acknowledgement after the
document lock is contended.

## Post-implementation recommendations

- Apply the configured process allocator fraction before any model load, sample
  both allocated and reserved CUDA immediately outside every forward boundary,
  retain authoritative allocator peaks, and translate terminal allocator OOM
  through the same typed memory-ceiling path.
- Give code and document runs one admitted memory-budget contract derived from
  the selected profile and operator configuration, and project only the
  ceilings, peaks, and typed outcome that execution actually enforced.
- Pass the document checkpoint's write policy through every managed document
  mutation and use the same deadline-aware local write lock as code. Prove the
  behavior with a real contended document collection and resource-release
  assertions.
- Keep `acceptance-floor` and the final implementation gates open. The 131-test
  CPU result verifies focused mechanics only; it is not the required full-scale
  backend or representative CUDA evidence.
