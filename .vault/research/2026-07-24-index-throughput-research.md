---
tags:
  - '#research'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:d9cc524977dcab36bea1088d1bd4fc904652ba946cc92fd46b55e935d6c50f6c'
related:
  - "[[2026-07-24-index-cuda-ceiling-research]]"
  - "[[2026-07-24-worktree-index-reuse-adr]]"
---

# `index-throughput` research: `where reindex wall-clock goes`

Full reindex jobs on this machine were reported at 45-75+ minutes. A read-only forensic pass over 256 persisted job records, the daemon service log, and the indexer/store source decomposed real rebuild-class jobs into stages and attributed the wall-clock. Headline: the long jobs belong to a sibling PDF-heavy corpus, not this repository (this repo rebuilds in 157 s code / 337 s vault / 6 s documents); the dominant machine-wide sink is uncapped cross-job GPU-lock contention (4-6x wall inflation), the secondary sink is serial CPU/ingest stages. The recently landed CUDA-ceiling fixes are present in-tree and are not a live regression.

## Findings

### The 45-75 minute jobs are a different corpus

Parsed from the daemon's persisted job records: this repository's rebuilds measure code 157 s, vault 337 s, document 6 s; its worst-ever run was one incremental vault at 1,517 s committing +6 chunks. The 2,935-4,495 s rebuild-class jobs all belong to a sibling PDF-heavy corpus on the same machine. The indexer and service code are shared, so every mechanism below generalizes; only the premise "this repo takes 45-75 minutes" is corrected.

### Stage decomposition of real rebuild jobs (from per-step service-log timestamps)

- Rebuild code, 44,747 chunks, 2,619 s wall: chunk+embed 2,583 s (98.6%); everything else (queue, scan, prepare, purge, metadata) under 25 s combined.
- Rebuild vault, 11,374 chunks, 2,613 s wall: queued 448 s (17%), parse documents 458 s (17.5%), embed+upsert 1,702 s (65%).
- Rebuild document, 27,560 chunks, 4,495 s wall: one embed+upsert stage of 4,469 s (99%) that folds the PDF preprocess hook subprocesses inline (445 preprocess log lines in the window).

### Sink 1 (dominant): uncapped cross-job GPU-lock contention

No cross-job concurrency cap exists anywhere - no admission semaphore in `src/vaultspec_rag/server/job_dispatch.py` or the watcher (the only semaphores are watcher state-transaction slots, `src/vaultspec_rag/server/watcher.py:69`). Index jobs run fully concurrently and serialize only on the single process-wide GPU lock. Overlap analysis of one 4,495 s window found 8 index jobs running simultaneously, including three rebuilds started within one second of each other, plus a second repository being watched. Direct proof from wall-clock vs the job's internal operation timer: incremental code worked 622 s but spent 3,110 s wall (2,489 s blocked); incremental document 1,892 s work vs 4,348 s wall; incremental vault 796 s work vs 2,935 s wall while committing +0 chunks; one vault rebuild spent 448 s queued before its scan began. A 44,747-chunk code encode that should run roughly 400-600 s solo took 2,583 s inside chunk+embed - about 4-6x inflation, consistent with three rebuilds interleaving on one lock. A single GPU gains nothing from this concurrency: the forwards serialize regardless, so the contention is pure added wall-clock.

### Sink 2: serial CPU and ingest stages

- Vault parse is a genuine 458 s single-threaded markdown-split stage (`_stream_encode_and_upsert_vault` calling `split_document`, `src/vaultspec_rag/indexer/_streaming.py:487`).
- Vault and document paths have no producer/consumer overlap: their encode loops are synchronous slice loops (`src/vaultspec_rag/indexer/_streaming.py:501,1163`), so the GPU idles during each slice's upsert and cache flush. The code path does overlap (weighted segment queue + spawn process-pool producer + single GPU consumer, `src/vaultspec_rag/indexer/_codebase_indexer.py:213`).
- Upserts run with the qdrant-client default `wait=True` (no explicit `wait=` at `src/vaultspec_rag/store.py:1091`), so each 512-chunk slice blocks until durably applied; the bounded 16 MB WAL (`src/vaultspec_rag/store_schema.py:92-93`) forces more frequent flush cycles under rebuild volume.
- Incremental vault re-does near-full work for near-zero net change: +0/+6-chunk jobs still spent 796-1,516 s (parse plus re-embed of unchanged content).
- Managed-profile batch sizes: vault 32, code 32, document 12; CUDA cache flush every 8 slices (`src/vaultspec_rag/config.py:566,573`) - each flush is a device sync, and 44k-chunk rebuilds pay hundreds of them.

### CUDA-OOM backoff is transient, not a throttle regression

`src/vaultspec_rag/embeddings.py:607-614` halves the batch size and retries within a single encode call, resetting to the configured value on the next slice; the indexer-level OOM hook fails the job checkpoint-resumably rather than shrink-and-continue. No permanent throughput loss follows an OOM-adjacent event.

### Regression verdicts (indexer/store/embeddings history since 2026-07-03)

- CUDA-ceiling defects: already fixed in this working tree (dedicated document encode sub-batch `2889f78f`, capacity-derived ceiling `4a52c6c3`, lock-bracketed forward-peak recording `c212a8e8`); the uncommitted ceiling research measured the pre-fix deployed service. Not a live regression.
- Document write-policy lock + backpressure (`c3cd3e81`): plausible minor ingest cost; verdict LOW.
- Store retry hardening (`e7a7cc7e`, `e9d9d9d0`, `202635ee`): retries fire only on failure; no happy-path regression.
- Prealloc geometry bounding (WAL 16 MB, 2 segments) combined with default `wait=True`: plausible ingest-throughput trade; verdict LOW-MODERATE, needs measurement.
- Unique chunk ids by construction (`5ec437c9`): marginal per-chunk hashing; no meaningful regression.

### Opportunity ranking (evidence-weighted)

Safe, small: (1) cap or serialize concurrent index jobs - collapses Sink 1, removing roughly 2,000-2,500 s of lock-wait per contended job at zero throughput cost on a single GPU; if it changes the watcher's admission model it warrants its own decision record; (2) explicit ingest wait policy (`wait=False` or grouped async upsert) plus revisiting the WAL bound; (3) fewer cache-flush device syncs. Larger, own decisions: parallelize vault parsing under the CPU-only worker rule; make incremental vault truly incremental (scope to changed paths, lean on encode-seam vector reuse); adopt producer/consumer overlap for vault/document paths under the single-GPU-consumer rule.

### Not investigated

Live re-measurement of ingest throughput under `wait=False` and larger WAL (needs a write-capable window); per-hook PDF preprocess timing distribution; whether the queue-wait accounting fully separates admission wait from GPU-lock wait inside chunk+embed.

### Follow-up empirical findings (isolated benchmark + failure-mode probes, run 2026-07-24)

An isolated benchmark against the pinned qdrant 1.18.2 (managed binary, tmp storage, production geometry and payload indexes, 50k synthetic points in 512-point batches, fresh-server-per-cell, two reps order-reversed) measured: non-blocking upsert waits are throughput-neutral in the current synchronous per-slice pattern (acknowledgment already includes the WAL write; client serialization dominates the ~470 ms per-batch call); the bounded 16 MB WAL costs about 10-13% versus default geometry; the application drain barrier is essentially free (well under a second after ~100 unwaited batches); and gRPC transport is 20-25% cheaper per upsert call than REST (383 vs 482 ms p50, same-session control). Failure-mode probes proved a silent-drop class: an upsert naming an unknown vector returns acknowledged and never applies with no error surfaced anywhere - only an exact-count check detects it - while wrong dimensions, missing collections, and malformed sparse rows still raise synchronously even without wait; acknowledged writes survive kill -9 (WAL-durable). Two bug-class defects were confirmed by code reading: the vault slice path empties the CUDA cache every slice (the flush-cadence throttle was never applied to it, `src/vaultspec_rag/indexer/_streaming.py:439`) and the document per-file loop leaves cache release defaulting on per slice (`src/vaultspec_rag/indexer/_document_indexer.py:578`, default at `src/vaultspec_rag/indexer/_streaming.py:561`) - roughly 2,300 forced device syncs inside the 4,469 s PDF rebuild - both gated on reserved-memory validation because cache flushing may be load-bearing against fragmentation. The +0-chunk incremental mystery resolved to two amplifiers: whole-file digests flip on the CLI-maintained modified-stamp (`src/vaultspec_rag/indexer/_vault_indexer.py:719-723,1044-1048`) and any watcher attempt failure escalates the next incremental to an unscoped full-corpus pass (`src/vaultspec_rag/server/watcher_retry.py:255`, `src/vaultspec_rag/server/watcher.py:1648-1658`). Also established: the daemon already runs index jobs through a four-slot capacity limiter (`src/vaultspec_rag/server/job_manager.py:720-725`, `src/vaultspec_rag/config.py:622`) whose wait time is invisibly reported as running - the admission gate is a capacity-and-reporting change, not new machinery.

## Sources

- `~/.vaultspec-rag/jobs-state.json` (256 job records, parsed 2026-07-24) and the daemon `service.log` per-step timestamps - stage tables and wall-vs-work gaps above
- `src/vaultspec_rag/server/job_dispatch.py`, `src/vaultspec_rag/server/watcher.py:69` - no cross-job admission cap
- `src/vaultspec_rag/indexer/_streaming.py:487,501,1163` - vault parse stage and synchronous vault/document slice loops
- `src/vaultspec_rag/indexer/_codebase_indexer.py:213,2010,2019` - code-path producer/consumer, OOM hook, forward-peak recording
- `src/vaultspec_rag/store.py:1091` - upsert with client-default wait semantics
- `src/vaultspec_rag/store_schema.py:92-93` - bounded WAL/segment geometry
- `src/vaultspec_rag/config.py:566,573` - batch sizes and flush cadence
- `src/vaultspec_rag/embeddings.py:607-614` - transient OOM backoff
- commits `2889f78f`, `4a52c6c3`, `c212a8e8`, `c3cd3e81`, `e7a7cc7e`, `e9d9d9d0`, `202635ee`, `5ec437c9`
