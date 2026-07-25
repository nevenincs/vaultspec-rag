---
tags:
  - '#adr'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-25'
related:
  - "[[2026-07-24-index-throughput-research]]"
---

# `index-throughput` adr: `bound job admission and align pipeline overlap` | (**status:** `accepted`)

## Problem Statement

Rebuild-class index jobs on this machine spend 4-6x their working time on wall-clock because the daemon admits unlimited concurrent index jobs that all serialize on the single process-wide GPU lock, and because the vault and document paths run serial slice loops that idle the GPU during parsing, upserts, and cache flushes (`2026-07-24-index-throughput-research`). A single GPU gains nothing from job-level concurrency - the contention is pure added latency - and the serial stages waste the producer/consumer pattern the code path already proved. A decision is needed on how throughput is recovered without violating the GPU, storage-lock, or lifecycle rules.

## Considerations

- One GPU: concurrent encode-bearing jobs cannot overlap compute; measured inflation is 4-6x with 8 simultaneous jobs (research stage tables).
- The code path's weighted-segment producer/consumer already demonstrates the sanctioned overlap pattern under the single-consumer and forwards-only-lock rules.
- Ingest currently blocks per slice on qdrant durability (client-default wait) against a deliberately bounded 16 MB WAL; the bound came from prealloc-waste work and must not silently regress.
- Vault parse is a 458 s single-threaded CPU stage; chunk workers must stay CPU-only and spawn-safe.
- Watcher/job admission is service-domain behavior; any cap must live in the service domain and surface identically to CLI and MCP consumers.
- Encode-seam vector reuse (accepted separately) shrinks encode time for forked roots; it does not address contention or serial stages.

## Considered options

- Do nothing / rely on vector reuse alone: leaves 4-6x contention inflation and serial-stage waste untouched. Rejected.
- Per-job GPU-lock fairness tweaks (priority, smaller slices): rearranges waiting without removing it; adds complexity to the lock the rules keep minimal. Rejected.
- Job-level admission cap (one GPU-bound index job in flight machine-wide; others queue in the existing job queue): removes the dominant sink at zero throughput cost; smallest surface. CHOSEN part A.
- Explicit ingest wait policy: pass wait=False on rebuild-path upserts with a completion barrier before the job's terminal metadata write (correctness: stale-purge and meta publish must still observe applied points), re-measured against the WAL bound. CHOSEN part B.
- Align vault/document paths with the code path's producer/consumer overlap and parallelize vault parsing in CPU-only workers. CHOSEN part C (the comprehensive half; each piece must preserve the single-GPU-consumer contract).
- True-incremental vault (scope work to changed paths): DEFERRED - depends on reuse telemetry and its own correctness analysis; separate future decision.

## Constraints

- GPU rules are invariant: exactly one GPU consumer thread; the lock wraps forward passes only; chunk/parse workers stay CPU-only with lazy torch; torch loads only through the centralized gate.
- Storage rules are invariant: backend-aware locks, no store-wide mutex, no lifecycle surface from maintenance code; the WAL/segment bounds may change only with measurement proving no prealloc regression.
- Admission cap is service-domain: implemented where jobs are dispatched, surfaced consistently to /jobs, CLI, and MCP; queued-not-running must be visible state, not silence.
- No behavior change for single-job workloads; the cap only shapes concurrency.
- Depends only on in-repo machinery (job dispatch, watcher, streaming, store); no new libraries.

## Implementation

Part A: a machine-wide GPU-job admission gate in the job dispatch layer. The daemon already runs every index job through a capacity limiter (four slots by default); the gate narrows encode-bearing jobs to one dedicated encode slot through that existing machinery rather than new locking, and fixes the reporting defect that limiter waits show as running: the job record gains an admission-acquired stamp, splitting admission wait from work. Read-only work, storage maintenance, and donor reads never touch the encode slot.

Part B (re-scoped after measurement - see Rationale): rebuild-path upserts pass explicit non-blocking wait semantics with a durability barrier before stale-purge and metadata publish. The measured facts: the acknowledgment already includes the WAL write, so non-blocking waits alone are throughput-neutral in the current synchronous per-slice pattern; the barrier is nearly free; and a proven silent-drop class exists (an upsert naming an unknown vector returns acknowledged and never applies, with no error ever surfaced). The barrier therefore verifies application, not acceptance: an idempotent sentinel operation with blocking wait fences all prior updates in WAL order, followed by an exact-count assertion that catches silent drops; any shortfall fails the job. Acknowledged writes survive process kill (WAL-durable), so checkpoint resume stays sound. Part B's value is enabling Part C to move upserts off the GPU consumer thread; transport-level gains come from switching the server-mode client to gRPC (measured 20-25% cheaper per upsert call), pin-compatibility verified before adoption.

Part C: vault parsing moves into the existing spawn-safe CPU worker pool pattern; vault and document encode paths adopt the code path's bounded-queue producer/consumer with a writer-side queue so upserts, checkpoints, and cache flushes overlap the next slice's encode, under the existing single consumer thread and sentinel-plus-timed-join shutdown discipline. Two measured bug-class defects ride with this phase under a reserved-memory caution: the vault path empties the CUDA cache every slice (the existing flush throttle was never applied to it) and the document per-file loop defaults its cache release on every slice; both throttles are implemented behind the existing cadence knob with conservative defaults and flip only after peak-reserved-memory and OOM validation on real full rebuilds, because cache flushing may be load-bearing against fragmentation on a ceiling that counts reserved memory.

Telemetry: admission wait, GPU-lock wait (timed-acquire accumulator), and work become first-class per-job numbers through the existing jobs envelope, making the contention collapse a regression-guarded measurement.

Guard tests prove they can fail per project rule: the admission-cap test goes red when the gate is bypassed; the barrier test injects the proven silent-drop (accepted, never applied) and goes red when the barrier or its count assertion is removed; the overlap tests go red on a second consumer or on inline upserts returning to the consumer thread.

## Rationale

Part A removes the single largest measured sink (roughly 2,000-2,500 s of per-job lock-wait in contended windows) by narrowing an existing limiter - not new machinery - at zero throughput cost, since a single GPU cannot run two encodes. Part B was re-scoped by direct measurement on the pinned server: an isolated benchmark showed non-blocking waits alone are throughput-neutral (the acknowledgment already pays the WAL write; client serialization dominates the per-batch call) while proving both the near-zero cost of a correct application barrier and the existence of a silent-drop class only an exact-count barrier catches - so Part B is retained as the correctness foundation that lets Part C take upserts off the consumer thread, with the measured transport win (gRPC) captured separately. Part C converts the remaining serial waste into overlap using the pattern the code path already proved under the same GPU rules. Alternatives that keep unlimited admission merely redistribute waiting; per-lock fairness tweaks add complexity without removing idle time. The staging keeps each part independently measurable and revertible (`2026-07-24-index-throughput-research`).

## Consequences

STATUS OF CLAIMS: Part A's contention claims are now OBSERVED on the running system; Part B is MEASURED and confirms it buys correctness rather than speed; the flush-cadence flip stays UNMEASURED and untaken, and the gRPC transport switch stays untaken and deferred to its own decision record. The numbers below carry their status inline. Provenance matters here: the Part A figures were recorded by the resident daemon about itself - it has run the gated build for hours across the watched roots, and its persisted job records ARE the contended window, decomposed per job into admission wait, run window, internal work timer and in-run GPU-lock wait. No run was timed against a busy device and no GPU window was taken; the machine's owner declined a quiesce so the release could ship. The staged arms that decision leaves out - a solo full rebuild and the cadence A/B - remain unmeasured, and the plan's Steps for them stay open rather than carrying an estimate.

- MEASURED (Part A, 253 terminal gated index jobs): the encode slot is exclusive in production - 0 overlapping [admission, finish] hold windows out of 31,878 pairs. In-run GPU-lock wait, the sink the gate exists to remove, is p50 0.000 s and p95 0.000 s over 239 succeeded jobs, against pre-gate jobs that blocked 2,489 s, 2,456 s and 2,139 s inside their own runs. Per-job wall inflation (run window over the run's own work timer, 193 jobs working over 1 s) is p50 1.029x, p95 1.427x, max 1.975x, against the pre-gate 2.3-5.0x. The one 251.6 s lock-wait outlier is a job overlapping busy search traffic: searches take the same process-wide lock and are deliberately not gated.
- MEASURED (Part A, single-job cost): admission wait is p50 0.178 s, min 0.063 s, so an uncontended job pays sub-second gate cost; the population's longest run (1,685.3 s incremental code) took 0.1 s of admission wait and 0.0017 s of lock wait, its wall equal to its work. Single-job behavior is unchanged as intended.
- MEASURED (Part A, visibility): waiting moved into the admission queue rather than disappearing into "running" - p95 1,308 s, max 1,986 s, with up to 8 jobs queued behind one admitted job. That is the same 8-job pile the research found grinding concurrently, now queuing honestly, one holder at a time.
- NOT MEASURED: aggregate machine throughput (chunks indexed per hour) before against after, and a staged full-rebuild-class job. The gate adds no GPU capacity - it removes per-job latency inflation and makes the wait visible - and the record population contains only long incremental runs.
- MEASURED (Part B, 51,200 points in 100 slices of 512 through the production upsert, fresh managed server per cell, four order-reversed pairs): the wait policy is throughput-neutral. Blocking-handshake totals 80.1 / 112.7 / 80.0 / 72.2 s (median 80.1 s) against deferred-plus-barrier 78.0 / 90.7 / 73.8 / 78.2 s (median 78.1 s) - a 2 s gap inside a single arm's own 72-113 s spread. The barrier costs 0.060-0.242 s per run, 0.3% of the ingest at worst, and all eight cells applied 51,200 of 51,200 points. So the wait flag was never the win; its value is that it let the writer-side overlap take upserts off the encode thread.
- Non-blocking ingest shifts durability to an application-verified barrier; the barrier is new correctness surface with its own mutation-proven guard and composition proof against the writer-side queue. The measured transport win (gRPC) remains unharvested: the managed supervisor listens on http_port - 1 while the client would target the default gRPC port, so the switch needs a gRPC-port configuration surface and its own failure-mode analysis against the REST-shaped error handling, not a flag flip.
- Vault/document paths gain the code path's producer/consumer complexity (bounded queue, sentinel shutdown with time-bounded joins) - accepted cost, mitigated by reusing the proven pattern.
- The flush-cadence throttles ship conservative-default (current behavior preserved byte-for-byte) and the flip is NOT taken. Two measurements argue against taking it blind: the one path already at the raised cadence recorded peak CUDA reserved p50 7,196 MB and max 13,074 MB against a 12,895 MB derived ceiling over 131 jobs - crossing it and surviving - while the cadence-1 document path peaked 3,676 MB; and the vault path publishes no CUDA peak at all (0 of 100 finished vault jobs), because peaks reach the record through the code and document run checkpoints and the vault run has neither. The vault knob's safety signal does not currently exist, so giving the vault run a memory-budget snapshot is a prerequisite for flipping it.
- True-incremental vault and any WAL-geometry change remain separate, telemetry-gated decisions.
