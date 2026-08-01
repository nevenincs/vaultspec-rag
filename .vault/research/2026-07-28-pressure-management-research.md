---
tags:
  - '#research'
  - '#pressure-management'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
body_hash: 'sha256:a5c58c73b126e89e6c65febcc1874c06e0ebf5227326ee166bf89ee35921acf1'
related: []
---

# `pressure-management` research: `Tiered pressure management and managed degradation`

The system's only responses to resource pressure today are block, time out, fail
typed, or open a circuit. Under contention it does none of these for a long
time: it crawls. A live incident this session showed a vault index job pinned at
192/4609 chunks for over five minutes while a foreign 12-worker test fleet plus
roughly 18 resident MCP shim processes held the GPU at 100% utilization and
15.5/16 GiB - one encode forward pass stretched to minutes, every surface stayed
silent, and the job later completed unmodified (+2113 chunks in 535 s) once the
card freed. Nothing yielded, deferred, or shrank. The accepted index-observability
decision record (`2026-07-28-index-observability-adr`) deliberately deferred
auto-defer-under-GPU-saturation until degradation evidence accumulates; this
research is the groundwork for making that decision properly, widened from the
GPU to the whole resource chain (GPU, host memory, storage backend, disk).

The evidence picture: the pipeline is already a chain of bounded
producer/consumer stages with clean backpressure, per-job telemetry that can
attribute cause landed this session, and every mechanism a controller needs
(admission gate, durable per-root backoff, cooperative run control, slice
boundaries) already exists as a seam. What is missing is (a) a machine-level
pressure verdict computed from the telemetry, (b) any adaptive response between
"run at full pace" and "fail", and (c) any machine-wide governance of aggregate
storage writes. The architecture the evidence supports is a three-tier pressure
model computed in the service domain from existing signals, driving a fixed
shed/yield ladder whose rungs each map onto a named existing seam - decisions on
thresholds, scope, and rollout order belong to the follow-on ADR and are listed
at the end.

## Findings

### What buckling actually is here: sojourn time, not queue depth

Claim: the system degrades by stretching in place, and every symptom is a
*time* signal, not a depth signal. The bounded queues do their job - memory
never overflowed - so pressure shows up as elongated occupancy: a forward pass
that normally finishes in single-digit seconds taking minutes, a synchronous
Qdrant write blocking the single writer thread, the writer's 2-slot queue
(`src/vaultspec_rag/indexer/_streaming.py:581`) staying full, the encode thread
stalling on `submit` (`src/vaultspec_rag/indexer/_streaming.py:612`). Every
Qdrant write is synchronous with a config-bounded server timeout
(`src/vaultspec_rag/store_runtime.py:295`, default 120 s at
`src/vaultspec_rag/config/_settings.py:278`), so backend slowness propagates
upstream as throughput collapse, exactly as designed - but with no controller
reading the collapse.

This matches the CoDel result from network queueing: a standing queue is
diagnosed by packet sojourn time, not queue length
(https://queue.acm.org/detail.cfm?id=2209336). The repo already measures the
right thing: forward-pass age and in-flight state
(`src/vaultspec_rag/jobs.py:880`), progress-stamp age
(`src/vaultspec_rag/server/_routes_jobs.py:321`), and backend probe latency
with a 2 s bound and 5 s cache (`src/vaultspec_rag/jobs.py:160`). A tier model
should be built on these ages, not on queue occupancy, which the bounded design
deliberately keeps small and therefore uninformative.

Separately measured and out of scope here: per-publish fsync in the job manager
(5.5 ms/call) is being fixed independently, and hashing loops now run
4,800-33,000 files/s behind a stat gate - neither is the buckling mechanism.

### The telemetry a controller can read exists as of this session

Claim: no new measurement is required for a first controller; the inputs are
already computed, cached, and shaped.

- Per-job three-way verdict `healthy`/`degraded`/`stalled`
  (`src/vaultspec_rag/server/_routes_jobs.py:370`), thresholds shared
  service-wide: 60 s degraded, 300 s stalled
  (`src/vaultspec_rag/_job_errors.py:45`, `src/vaultspec_rag/_job_errors.py:35`).
- Cause-attributed evidence on unhealthy verdicts:
  `degradation_evidence` (`src/vaultspec_rag/jobs.py:1002`) with three
  independent findings - forward window and encode-thread liveness
  (`src/vaultspec_rag/jobs.py:880`), machine-wide GPU pressure via the
  read-only probe `cuda_pressure()` returning utilization percent, used MiB,
  total MiB (`src/vaultspec_rag/memory_probe.py:209`, shaped at
  `src/vaultspec_rag/jobs.py:921`), and a bounded backend liveness probe with
  latency (`src/vaultspec_rag/jobs.py:940`).
- Forward-pass entry/exit boundaries reported live from the encode slice
  through the reporter protocol (`src/vaultspec_rag/progress.py:60`, fired at
  `src/vaultspec_rag/indexer/_streaming.py:493`).
- Limiter occupancy including waiter counts for search, index, and encode
  limiters (`src/vaultspec_rag/concurrency.py:112`).

The GPU memory figures are device-wide (`mem_get_info`), so they see foreign
processes' pressure - the incident's defining signal - not just this process
(`src/vaultspec_rag/memory_probe.py:225`). Utilization degrades independently
when NVML is absent. Every probe reports absence rather than raising, so a tier
evaluator built on them inherits torch-free-host safety for free.

### Tiered pressure model: three tiers riding the existing vocabulary

Claim: the service should compute one machine-level pressure tier -
`nominal` / `elevated` / `critical` - in the service domain, from the same
signals the degradation verdict already samples, and surface it as a sibling of
that verdict rather than a parallel vocabulary. The per-job axis (is *this job*
healthy) and the machine axis (is *this machine* under pressure) are different
questions, but they should share the evidence block shape, the thresholds, and
the adapters (`/jobs` envelope, CLI, MCP), per the service-surface rule that
entry points adapt to service-domain behaviour and never own it.

Signals and proposed tier semantics (thresholds are ADR decisions; the
*structure* is what the evidence supports):

| Signal                                     | Source                                  | Elevated when                                        | Critical when                                                                          |
| ------------------------------------------ | --------------------------------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Forward-pass age (in-flight, thread alive) | `src/vaultspec_rag/jobs.py:880`         | >= 60 s (reuse `DEGRADED_THRESHOLD_SECONDS`)         | >= 300 s (reuse `STALL_THRESHOLD_SECONDS`)                                             |
| GPU utilization AND device memory          | `src/vaultspec_rag/memory_probe.py:209` | sustained high on both (incident: 100%, 15.5/16 GiB) | n/a alone - GPU saturation without forward-age evidence is foreign load, not our stall |
| Backend probe latency                      | `src/vaultspec_rag/jobs.py:940`         | latency above normal band (measured baseline needed) | probe unanswered (`alive: None`) or repeated `timeout`/`unavailable` classifications   |
| Encode-limiter waiters                     | `src/vaultspec_rag/concurrency.py:112`  | waiting > 0 for a sustained window                   | n/a (bounded by design)                                                                |
| Disk / typed failures                      | `src/vaultspec_rag/_job_errors.py:58`   | n/a                                                  | any `disk_full`, `disk_preflight_failed` in the window                                 |

Two structural points the incident forces:

1. GPU signals alone must never reach `critical`. The incident job was
   *healthy work on a starved card* - it finished untouched. GPU saturation
   plus a stretched forward is `elevated` (yield, defer new work); only
   store-side evidence (backend unanswered, disk full) or a dead encode thread
   justifies `critical`. Kubernetes draws the same line: PressureStall-style
   soft eviction thresholds require a sustained grace period, hard thresholds
   act immediately
   (https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/).
1. Hysteresis must be asymmetric: fast attack, slow release. Escalate on M
   consecutive samples over the enter threshold (the 5 s probe-cache cadence at
   `src/vaultspec_rag/jobs.py:161` is a natural sample clock); de-escalate only
   after a longer continuous clear window (order of 60 s). The repo already
   encodes this ratchet philosophy twice: the resident CUDA baseline only grows
   on transient observations (`src/vaultspec_rag/memory_probe.py:389`), and the
   storage-grace rule resets protection clocks on any contrary observation so
   races extend protection rather than shorten it. A tier that flaps is worse
   than no tier: every ladder rung below assumes the tier is stable enough to
   act on.

Where computed: a small service-domain evaluator adjacent to
`degradation_evidence` in `src/vaultspec_rag/jobs.py` - torch-free call path,
reading only the guarded probes - sampled on the jobs-envelope cadence and
persisted per transition to the managed log so tier history accumulates as the
evidence the deferred ADR asked for. Surfaced as one `pressure` block on the
jobs envelope carrying tier, entered-at, and the evidence triple, rendered by
CLI/MCP/TUI from the same block.

### The shed/yield ladder: what degrades first, what never degrades

Claim: rungs must be ordered by reversibility and blast radius, each rung
mapped to an existing seam, and the never-degrades set stated as hard
invariants. The brownout literature calls this separating mandatory from
optional work and switching optional work off under pressure
(https://dl.acm.org/doi/10.1145/2568225.2568227); the SRE load-shedding
literature adds that degradation must be feedback-driven and honest to clients
(https://sre.google/sre-book/handling-overload/).

Never degrades, at any tier:

- Search availability and priority. Searches are seconds-scale, hold the GPU
  lock briefly, and are the product. The limiter partition already guarantees
  index jobs cannot starve searches of threads
  (`src/vaultspec_rag/concurrency.py:1`).
- Durability and crash safety: synchronous confirmed writes, non-destructive
  generation publication, fail-stop writer semantics
  (`src/vaultspec_rag/indexer/_streaming.py:552`).
- The one-GPU-consumer rule and the single machine-wide encode admission slot
  (`src/vaultspec_rag/concurrency.py:40`).
- Bounded, liveness-guarded waits. Every rung below *paces*; none may wait
  unboundedly.
- In-flight forwards. A dispatched CUDA kernel is not preemptible; killing the
  process mid-forward is the failure mode the crash-safety floor exists to
  survive, not a control action.

The ladder, first-to-shed first (rungs 1-2 at `elevated`, 3-4 as `elevated`
persists, 5-6 at `critical`):

1. **Defer watcher-triggered index jobs; searches and operator jobs proceed.**
   Seam: admission (`src/vaultspec_rag/jobs.py:1206`) already records initiator
   kind, and the watcher already owns durable per-root+source retry state with
   `next_retry_at`, jittered exponential backoff, and a failure-threshold
   circuit (`src/vaultspec_rag/watcher_retry.py:163`). A pressure deferral is a
   new *non-failure* settlement: push `next_retry_at` out without incrementing
   `consecutive_failures`, so pressure never walks a healthy root toward
   `watcher_circuit_open`. Reversibility: total - the retry fires when due.
   Relief: stops new encode load at the source; large when agent fleets churn
   files. Risk: index staleness, bounded by the retry horizon and by the
   convergence-pending bit that already survives process loss.
1. **Inter-slice yields proportional to tier.** Seam: the slice loops
   (`src/vaultspec_rag/indexer/_streaming.py:802` vault,
   `src/vaultspec_rag/indexer/_streaming.py:1580` codebase) already checkpoint
   run control at every slice boundary outside the GPU lock. A tier-read sleep
   at that boundary - jittered, capped, checkpoint-interleaved so pause/cancel
   latency is unchanged - converts "crawl at 100% contention" into explicit
   paced progress and hands the card timeslices the foreign load can actually
   use. Reversibility: instant (next boundary reads a lower tier).
   Relief: direct GPU-contention relief between our forwards. Risk: longer
   wall clock while elevated - which is the designed intent, and the
   degradation verdict plus forward telemetry keep it visible rather than
   silent.
1. **Space or coalesce storage writes.** Seam: the single writer thread
   (`src/vaultspec_rag/indexer/_streaming.py:590`) is the one place every
   store mutation for a run already serializes; an inter-task pacing delay
   there (or a shared token-bucket consult, next finding) spreads write
   pressure the way InnoDB's adaptive flushing spreads page writes by redo
   rate (https://dev.mysql.com/doc/refman/8.4/en/innodb-buffer-pool-flushing.html)
   and Postgres spreads checkpoint I/O across the interval
   (https://www.postgresql.org/docs/current/wal-configuration.html).
   Reversibility: instant. Relief: lets a struggling Qdrant drain; the
   bounded queue then backpressures encode naturally - the existing design
   does the rest. Risk: writer-queue fill stalls the encode thread sooner;
   acceptable because that stall is the *ordered, bounded* form of the same
   wait the backend would otherwise impose chaotically.
1. **Shrink encode batch/slice sizes.** Seam: `encode_batch_size` is already
   threaded per-slice (`src/vaultspec_rag/indexer/_streaming.py:119`,
   `src/vaultspec_rag/indexer/_streaming.py:157`) and slice packing is
   config-bounded (`src/vaultspec_rag/indexer/_streaming.py:1431`). Smaller
   forwards mean shorter GPU-lock holds (finer-grained yielding to searches
   and foreign load) and lower per-forward CUDA peak. Reversibility: per
   slice. Relief: moderate. Risk: highest of the reversible rungs - it
   forfeits length-sorted padding efficiency the pipeline was specifically
   tuned for and reduces throughput even after pressure clears unless
   recovery is explicit; hence it sits below the pure-pacing rungs and needs
   Stage-0 evidence before adoption.
1. **Pause preprocess hooks and non-essential producers.** Seam: watcher
   execution/intake, where hook batches are scheduled. CPU-side relief only;
   at `critical` the store side is the constraint, so this rung mostly stops
   feeding a pipeline that cannot drain. Reversibility: resume on
   de-escalation; the durable convergence intent already covers missed work.
1. **Refuse new index admissions with an honest retry-after.** Seam:
   admission (`src/vaultspec_rag/jobs.py:1206`), which already refuses typed
   (`job_capacity_exceeded` at `src/vaultspec_rag/_job_errors.py:69`). A new
   typed refusal carrying the tier and a jittered retry-after keeps the
   already-done/refusal envelope contract intact: exit non-zero, one
   structured envelope, remediation text, never a hang. This is the SRE-book
   client-honesty rung: a cheap early "not now" beats an expensive late
   timeout (https://sre.google/sre-book/addressing-cascading-failures/).
   Searches are never refused.

### Backoff shapes: AIMD for pacing, jittered exponential for deferral, token bucket for writes

Claim: three different control problems on the ladder want three different,
well-understood shapes - and two of the three are already in the repo.

- **Deferral and refusal retry-after: capped exponential with jitter.** This
  is the repo's existing, deliberately centralized shape
  (`src/vaultspec_rag/_backoff.py:46`), with overflow clamping and cap-honoring
  jitter already reasoned through (`src/vaultspec_rag/_backoff.py:1`). Full
  jitter is the right variant for decorrelating N deferred roots retrying into
  a shared resource (https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/).
  Reuse it; do not mint a new curve.
- **Inter-slice yield pacing: AIMD.** Additively lengthen the yield while
  samples stay elevated; multiplicatively shorten it on clear samples (or
  equivalently, multiplicatively cut pace on pressure, additively recover).
  The decisive property is Chiu-Jain convergence: N uncoordinated daemons
  running AIMD against one shared bottleneck converge toward fair shares
  without any coordinator (https://doi.org/10.1016/0169-7552(89)90019-6,
  operationalized in TCP by RFC 5681). That makes AIMD the only rung shape
  that *partially solves the cross-process problem by itself* - the
  multi-daemon fairness emerges from the shape, not from shared state.
  Netflix's concurrency-limits library applies the same family
  (gradient/Vegas-style adaptive limits) to service concurrency and is the
  closest production analogue (https://github.com/Netflix/concurrency-limits).
- **Machine-wide write governor: token bucket with tier-modulated refill.**
  A bucket bounds burst (a slice's points land together) while the refill rate
  is the single knob a tier controller turns down under backend pressure and
  restores on de-escalation. Database flushing heuristics are the precedent
  for rate-modulated background writes cited above; the bucket form is
  preferable to a pure delay because it keeps the nominal path zero-cost -
  tokens are plentiful at `nominal` and the consult is a non-blocking read.

Not chosen for any rung: unmodified exponential backoff on the *pacing* path
(it converges to near-zero throughput and recovers too slowly for a resource
that frees all at once, as the incident card did), and deadline-driven
kill-and-retry (repeats the whole forward's work against the same contention -
the tail-at-scale hedging insight does not apply where the retry lands on the
same single device, https://dl.acm.org/doi/10.1145/2408776.2408794).

### Cross-process coordination: one daemon computes truth; a durable sidecar shares it

Claim: the minimal mechanism consistent with the in-repo precedents is (a) the
singleton daemon as the pressure evaluator, (b) a small durable pressure
ledger under the managed status dir for processes the daemon does not host,
and (c) fail-open staleness semantics.

The encode admission gate is instructive: it is machine-wide *because the
daemon is the machine singleton* (`src/vaultspec_rag/concurrency.py:77`) - no
file lock was needed for the service path. The same holds for the tier
evaluator and the write governor's authoritative state: every service-path
index job already runs inside the daemon, so an in-daemon token bucket governs
the aggregate service write stream with zero new IPC.

What the daemon does not host: foreign test fleets, local-only-mode shims, and
per-worktree duplicate corpora each indexing a full clone. For those, the
durable watcher-retry state is the in-repo pattern for cross-process,
crash-surviving coordination state - schema-versioned bounded JSON per scope,
atomic durable replacement, `FileLock` guarded
(`src/vaultspec_rag/watcher_retry.py:53`, locks from
`src/vaultspec_rag/_store_locks.py`, machine-scope precedent in
`src/vaultspec_rag/_machine_lock.py`). A pressure ledger in that pattern - one
small file, written by the daemon on tier transitions, read (never written) by
non-daemon indexers before heavy work - extends pressure truth machine-wide
without inventing a bus.

Staleness must fail open: a ledger older than a TTL (a few sample periods) is
treated as `nominal`. A dead daemon must never brake anyone - the inverse rule
from the storage-grace clock (where uncertainty extends protection) because
here the protected asset is availability of foreground work, not data.

Two boundaries this mechanism respects:

- It is not a client-side point-operation lock on server-mode Qdrant. The
  governor paces *submission* at slice-writer granularity; it never serializes
  or wraps individual store operations, which the storage discipline forbids
  and which measurably destroyed search latency when a store-wide mutex
  existed.
- The duplicate-corpora aggravation (every agent worktree indexing its own
  clone) is a demand-side problem the governor only cushions; worktree index
  reuse (`2026-07-24-worktree-index-reuse-adr`) attacks the duplication
  itself and remains the higher-leverage fix for that specific load source.

### Multi-GPU: keep the boundary

Claim: the one-device, one-consumer architecture should stand, and the
pressure system should be designed so it does not care.

The buckling mechanism is contention for shared commons - one card, one disk,
one Qdrant - from processes outside our control. A second device would change
which commons saturates first, not the need for a controller; and the hard
rules (one GPU consumer thread, no CUDA streams for compute parallelism, no
second consumer) encode measured platform behaviour that pressure management
has no evidence to overturn. The tier evaluator reads device-wide probes and
the ladder acts at slice boundaries; neither assumes device count. If bigger
hardware later justifies revisiting the consumer topology, that is its own
ADR with its own benchmarks - this system's signals (per-device
`cuda_pressure`, forward ages) extend additively.

### Staged adoption: what today's telemetry supports now vs what needs evidence

Claim: the observability ADR's deferral was conditioned on evidence; the
stages below are ordered so each one generates the evidence the next one
needs.

- **Stage 0 - compute and surface the tier; change no behaviour.** The
  evaluator, hysteresis, envelope block, and managed-log transition records
  are pure additions over existing probes. This *is* the evidence
  accumulation the deferred decision asked for: tier history against job
  outcomes calibrates every threshold the ADR must set.
- **Stage 1 - deferral rungs at `critical` (rungs 1 and 6).** Lowest risk:
  both reuse hardened seams (watcher retry state, typed admission refusal),
  both are pure admission-time decisions with total reversibility, and
  `critical` is the tier with the least threshold uncertainty (backend
  unanswered, disk full - conditions that already fail jobs today, just
  later and worse).
- **Stage 2 - inter-slice AIMD yields at `elevated` (rung 2).** Needs
  Stage-0 evidence to pick the elevated GPU thresholds and yield caps;
  mechanically small (one paced checkpoint at an existing boundary).
- **Stage 3 - write governor (rung 3), then batch shrinking (rung 4).** The
  governor should land after the fsync fix settles and after Stage 0
  establishes a backend-latency baseline; batch adaptation is last because it
  trades against a deliberate padding optimisation and its relief is the
  least certain.

Decisions the follow-on ADR must settle:

1. Tier definitions: exact signal thresholds, M-of-N attack window,
   clear-window length - and whether `elevated` reuses
   `DEGRADED_THRESHOLD_SECONDS`/`STALL_THRESHOLD_SECONDS` as proposed or gets
   independent constants.
1. Scope of automatic action: does the ladder ever act on operator-initiated
   jobs, or only watcher/automatic ones? (Initiator attribution exists at
   admission; the proposal above degrades only automatic work and informs
   operators.)
1. Governor topology: in-daemon only, or in-daemon plus the durable ledger
   for non-daemon processes - and the fail-open TTL.
1. Surface contract: the `pressure` block's exact shape on the jobs envelope
   and whether tier transitions emit log events, metrics gauges, or both.
1. Backoff parameters per rung: AIMD increase/decrease constants, yield cap,
   deferral horizon cap, refill-rate schedule per tier.
1. Confirmation that the one-GPU-consumer boundary is retained (recommended)
   and that batch-size adaptation (rung 4) is in or out of the first
   implementation.

Not investigated: Windows-specific I/O prioritization (SetPriorityClass /
IoPriority) as an OS-level shed lever - potentially useful but process-global
and unportable to the "bigger hardware later" path; and cgroup-style
enforcement, which has no Windows equivalent for this deployment.

## Sources

In-repo (all verified in the working tree at time of writing):

- `src/vaultspec_rag/_job_errors.py:35` - stall threshold; `:45` degraded threshold; `:58` typed failure vocabulary; `:69` capacity refusal
- `src/vaultspec_rag/server/_routes_jobs.py:321` - stall classification; `:370` three-way degradation verdict
- `src/vaultspec_rag/jobs.py:880` - forward evidence; `:921` GPU evidence; `:940` bounded backend probe; `:160` probe timeout/cache constants; `:1002` `degradation_evidence`; `:1206` index-job admission
- `src/vaultspec_rag/memory_probe.py:209` - `cuda_pressure` read-only device-wide probe; `:389` monotonic resident-baseline ratchet
- `src/vaultspec_rag/concurrency.py:40` - single machine-wide encode slot; `:77` `get_encode_limiter`; `:112` limiter occupancy stats
- `src/vaultspec_rag/job_manager/_execution.py:479` - encode-bearing jobs routed through the encode limiter
- `src/vaultspec_rag/indexer/_streaming.py:552` - `_SliceWriter` single writer thread, bounded queue, fail-stop; `:581` 2-slot queue; `:612` bounded submit; `:493` forward-boundary callbacks; `:802` vault slice loop; `:1580` codebase slice loop; `:119`/`:157` per-slice `encode_batch_size`; `:1431` bounded slice packing
- `src/vaultspec_rag/_backoff.py:34` - `capped_exponential`; `:46` `jittered_backoff`
- `src/vaultspec_rag/watcher_retry.py:53` - durable schema-versioned per-root/source state; `:163` `WatcherRetryPolicy` retry + circuit authority
- `src/vaultspec_rag/_store_writes.py:181` - store write retry budget against the configured operation timeout; `src/vaultspec_rag/store_runtime.py:295` server-mode client timeout; `src/vaultspec_rag/config/_settings.py:278` 120 s default
- `src/vaultspec_rag/index_profiles.py:412` - admission-time profile validation; `src/vaultspec_rag/indexer/_resource_ceilings.py:101` - `admit_index_ceilings`
- `src/vaultspec_rag/progress.py:60` - reporter protocol forward boundaries
- `src/vaultspec_rag/_machine_lock.py`, `src/vaultspec_rag/_fd_lock.py`, `src/vaultspec_rag/_store_locks.py` - cross-process lock precedents
- `2026-07-28-index-observability-adr` - deferred auto-defer-under-saturation pending evidence
- `2026-07-24-worktree-index-reuse-adr` - demand-side fix for duplicate worktree corpora

External:

- https://queue.acm.org/detail.cfm?id=2209336 - Nichols and Jacobson, "Controlling Queue Delay" (CoDel): diagnose standing queues by sojourn time
- https://doi.org/10.1016/0169-7552(89)90019-6 - Chiu and Jain (1989): AIMD convergence to fairness among uncoordinated flows
- RFC 5681 - TCP congestion control (AIMD operationalized)
- https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/ - Brooker (2015): full jitter for decorrelated retries
- https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/ - soft (grace-period) vs hard eviction thresholds
- https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/ - QoS classes ordering what is evicted first
- https://sre.google/sre-book/handling-overload/ - load shedding and graceful degradation
- https://sre.google/sre-book/addressing-cascading-failures/ - early refusal beats late timeout; retry hygiene
- https://dl.acm.org/doi/10.1145/2568225.2568227 - Klein et al., "Brownout" (ICSE 2014): controller-driven deactivation of optional work
- https://queue.acm.org/detail.cfm?id=2839461 - Maurer, "Fail at Scale": controlled delay and adaptive LIFO queueing under overload
- https://dev.mysql.com/doc/refman/8.4/en/innodb-buffer-pool-flushing.html - InnoDB adaptive flushing: write rate modulated by pressure signal
- https://www.postgresql.org/docs/current/wal-configuration.html - Postgres checkpoint spreading (`checkpoint_completion_target`)
- https://github.com/Netflix/concurrency-limits - production adaptive concurrency limiting (gradient/Vegas family)
- https://dl.acm.org/doi/10.1145/2408776.2408794 - Dean and Barroso, "The Tail at Scale" (and why hedging does not apply to a single shared device)
