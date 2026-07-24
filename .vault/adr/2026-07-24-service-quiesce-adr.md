---
tags:
  - '#adr'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - "[[2026-07-24-service-quiesce-research]]"
  - "[[2026-06-12-service-concurrency-adr]]"
  - "[[2026-07-23-ci-self-hosted-gpu-runner-adr]]"
---

# `service-quiesce` adr: `Cooperative zero-CPU GPU quiesce gate` | (**status:** `accepted`)

## Problem Statement

The resident RAG daemon, the self-hosted GPU CI runner, and the local test suite
share one physical RTX 4080 SUPER (16 GiB) and contend for it indefinitely,
producing OOM crashes and CI wedges (`2026-07-24-service-quiesce-research`;
`2026-07-23-ci-self-hosted-gpu-runner-adr` constrains the runner to a separate
account and serialises out-of-lock process VRAM precisely because 16 GiB cannot
co-schedule two GPU tenants). The daemon has no way to stand down: an ephemeral
consumer that needs the whole device cannot get it, and best-effort account
isolation is the only lever today. We need a global pause the daemon can hold
with zero idle CPU (no busy-poll, no sleep-loop) that even deeply in-flight work
threads honour promptly, so a short-lived external GPU consumer can borrow the
device and the daemon resumes afterward. The decision is needed now because the
contention is actively wedging CI, and the project already owns every primitive
required, so the cost of building it is small and the cost of not building it is
recurring outages.

## Considerations

- The existing `RunControl` pause is **unwinding** - `checkpoint()` raises a
  `BaseException`-derived signal that aborts the attempt so orchestration
  reconciles desired state (`2026-07-24-service-quiesce-research`). Quiesce needs
  the opposite: hold-and-resume the *same* attempt. These are orthogonal and must
  coexist, not merge.
- `checkpoint()` is called from **inside** `protected()` spans today (the codebase
  indexer brackets its publication mutation in `protected()` and checkpoints
  within it). A hold that parks a worker mid-indivisible-mutation wedges the
  indexer under its writer lock - the same shutdown-hang failure class the single
  GPU consumer already guards. The gate wait must therefore be protected-aware,
  deferred exactly like the existing unwind delivery.
- There is exactly one GPU lock per process serialising every forward pass, and
  holding it beyond the forward pass serialises all tenants
  (`2026-06-12-service-concurrency-adr`; `gpu-lock-wraps-forward-passes-only`).
  Any quiesce wait must sit outside the GPU lock and outside a `protected()`
  span or a held store write, or it deadlocks the writer lock.
- The gate primitive must be torch-free: it is reachable from the spawn-worker
  import chain and from search, and importing torch there reintroduces the
  CUDA-in-subprocess crash class (`index-workers-stay-cpu-only`,
  `torch-loads-through-centralized-gpu-gate`).
- The promptness bound is set by physics already accepted for cancellation: a
  dispatched CUDA kernel is not preemptible from Python mid-kernel, and the
  consumer RTX 4080 has no MIG partitioning to force it
  (`2026-07-24-service-quiesce-research`). "Promptly" means at the next unprotected
  checkpoint or slice boundary - sub-second, identical to today's cancellation
  latency.
- Search is multi-tenant: several requests run concurrently (around concurrency 4)
  each taking the GPU lock in turn (`2026-06-12-service-concurrency-adr`). An
  admission gate stops new entrants but cannot preempt requests already past
  admission.
- An idle daemon - the common case exactly when CI wants the GPU - reaches no
  checkpoint and runs no search, yet still holds its resident model VRAM (several
  GiB). A purely lazy checkpoint-time observation therefore covers the busy daemon
  but not the idle one; freeing idle VRAM needs an active wakeup, not a passive
  probe.
- Crash-safety is load-bearing: if an external actor dies mid-borrow, the daemon
  must not stay paused forever (`2026-07-24-service-quiesce-research`).
- Quiesce pauses; it never stops or kills. It must not become a channel by which
  one actor terminates another (`storage-maintenance-is-lifecycle-inert`).
- The machine already owns a crash-safe, cross-platform OS advisory lock with a
  STATUS_DIR-independent machine-global anchor and an atomic discovery pointer
  (`2026-07-24-service-quiesce-research`), reusable for a cross-process signal.

## Considered options

- **In-process `threading.Event` gate with an absorbing-open latch (chosen
  primitive).** Convention set = running, clear = paused; a worker calls `wait()`
  at an unprotected checkpoint and parks in the OS futex at zero CPU until `set()`
  wakes all waiters. A latch makes an absorbing request (cancel/shutdown) open the
  gate irreversibly. Torch-free pure `threading`, exactly the required semantics.
  Chosen.
- **Busy or sleep poll (`while paused: sleep`).** Burns a wakeup per worker per
  interval, adds up to the interval of resume latency, scales CPU with worker
  count. Rejected - it is the idle spin the requirement forbids.
- **`threading.Condition` with a predicate.** A correct, zero-CPU way to wait on
  the *disjunction* the gate genuinely needs - "resume requested OR an absorbing
  request is pending" - which a bare boolean `Event` cannot express, exposing a
  lost-wakeup if a `pause()` races a pending shutdown. But the latch (an absorbing
  request opens the gate irreversibly and makes `pause()`/`clear()` a no-op while
  pending) collapses that disjunction back to a single boolean without the extra
  predicate-and-lock machinery a `Condition` carries. Rejected in favour of
  Event-plus-latch, which is strictly less machinery for the same guarantee.
- **A lock the worker tries to acquire.** A paused daemon would hold a lock across
  an unbounded external window, and lock ownership is thread-bound (releaser must
  be acquirer), mismatching a controller-sets/worker-waits topology. Rejected.
- **Cross-process RELEASE: second OS advisory lock the external actor holds (chosen
  for phase 2).** A distinct "quiesce lease" lock beside `service.lock`; process
  death auto-releases the OS lock, so a dead actor can never leave the lease held.
  Chosen as the crash-safe release mechanism - strongest crash-safety, maximal
  reuse of hardened machinery. The daemon-side OBSERVATION and wakeup of this lease
  is a separate, still-open question (see Implementation), not settled by this
  choice.
- **Cross-process: heartbeat-expiry JSON sentinel.** A `service.quiesce.json` with
  an `expires_at` the actor renews; the daemon treats an expired lease as absent.
  Viable and observable, but relies on a wall-clock renewal loop and a dead actor
  un-wedges only after the expiry lapses, not immediately. Rejected as the release
  mechanism in favour of the OS lock (death is the release, no clock).
- **Overload the identity machine lock into a GPU lease.** The daemon holds the
  identity lock for its whole lifetime; releasing it to let a consumer take it
  would let a *second daemon* start. Rejected - the GPU lease must be a distinct
  lock, not an overload of the singleton authority.
- **Named OS event (Windows `CreateEvent`).** Maps naturally to the boolean and
  waits cross-process at zero CPU, but has no clean POSIX equivalent (named
  semaphore semantics and cleanup differ), forcing two code paths. Rejected as the
  cross-process mechanism; the in-process `Event` stays the intra-daemon primitive.
- **NVIDIA MIG.** Hardware partitioning is enterprise/data-center only and
  explicitly absent on consumer GeForce including the RTX 4080. Rejected - not
  available on the hardware.
- **NVIDIA CUDA MPS.** Linux-only (the workstation and GPU CI runner are
  Windows-native) and provides spatial SM sharing with **no VRAM isolation** -
  co-resident clients still OOM, the exact failure this feature prevents.
  Rejected.
- **Job schedulers (Slurm, Kubernetes device plugins, Ray).** The industrial
  multi-tenant GPU answer, but each is a heavyweight cluster control plane grossly
  disproportionate to one workstation with one GPU and a companion CLI tool.
  Rejected as overkill.

## Constraints

- The gate primitive carries no torch import and must stay importable from the
  spawn-worker chain and from search without pulling CUDA onto either. It lives
  beside `RunControl` (in `job_control.py` or a sibling module), never behind
  `_gpu.load_torch()`.
- **Protected-aware, generalized to every checkpoint site.** The hold-gate wait is
  skipped while a `protected()` span is active (a positive protected depth),
  exactly like the existing unwind delivery defers there, and is honored only at
  the next unprotected checkpoint. More broadly, any current or future checkpoint
  site must keep the gate wait OUT of any `gpu_lock`, `protected()`, or
  held-store-write span - today the streaming consumer already brackets its
  checkpoints outside `gpu_lock`, and that placement must be preserved. Parking
  inside any of those spans deadlocks the writer lock or serialises all tenants.
- An absorbing shutdown or cancel request must always win over a hold, with no
  lost-wakeup even when a `pause()` races a pending absorbing request: a quiesced
  worker MUST NOT block forever. This is the load-bearing correctness point and is
  met by the latch (see Implementation).
- Phase 2's cross-process auto-quiesce and the `torch.cuda.empty_cache()` VRAM
  release cannot be verified green without a live contended GPU: the resident
  service holds several GiB and any GPU-live test co-schedules against it, the
  exact 16 GiB OOM hazard. Phase 2 therefore requires a coordinated GPU
  maintenance window and is sequenced after phase 1
  (`2026-07-24-service-quiesce-research`).
- Parent-feature stability: `RunControl`, the single GPU lock, and the machine OS
  advisory lock are all shipped, hardened, and load-bearing today; quiesce is an
  additive layer over stable parents, not new infrastructure.

## Implementation

**Phase 1 (ship now, fully green GPU-free).**

A small torch-free object (working name `QuiesceGate`) wraps a `threading.Event`
with the convention set = running, clear = paused. It exposes `wait()` (blocks
in-kernel at zero CPU while paused, wakes instantly on resume), `pause()`,
`resume()`, and `is_paused()`. It lives beside `RunControl` so both indexers and
search reach it without importing torch. The control token holds an optional
reference to the gate so absorbing requests can latch it (below).

`checkpoint()` consults the gate first, before evaluating the existing unwind
signal, but **only when no `protected()` span is active**: while a protected span
is open the gate wait is skipped and deferred to the next unprotected checkpoint,
mirroring how the token already withholds unwind delivery inside a protected span.
This keeps a hold from ever parking a worker mid-mutation under the writer lock.

The absorbing-open latch is the load-bearing correctness mechanism. Setting any
absorbing request on the token (`request_cancel()` or `request_shutdown()`) also
latches the gate OPEN irreversibly: a latched-open gate's `wait()` returns
immediately, and `pause()` and `clear()` become no-ops while an absorbing request
is pending. This closes the lost-wakeup race: once shutdown is requested the gate
cannot be re-cleared by a concurrent `pause()` (a racing `server pause`, or a
phase-2 lease re-observation), so a woken worker always reaches the post-gate
re-check of absorbing signals and raises the shutdown or cancel signal rather than
re-parking. A worker resumed by shutdown proceeds straight into its unwind rather
than continuing the attempt.

Search takes the GPU lock directly and does not thread `run_control`. Quiesce
gates search at **admission**: a request waits on the gate before acquiring the
GPU lock for encode or rerank. Search is multi-tenant (around concurrency 4), so
admission gating blocks only new entrants; requests already past admission drain
their GPU sections and no new request is admitted. The promptness bound is
therefore the concurrency cap times one encode-plus-rerank each, not a single
in-flight search - still sub-second, and no request already inside its GPU section
is preempted (mid-kernel is never preemptible).

`server pause` and `server resume` CLI verbs drive the gate and follow the
structured-idempotent JSON envelope pattern the lifecycle verbs already use
(`broker-facing-cli-outcomes-are-structured-and-idempotent`): exactly one envelope
on every exit path, and an already-satisfied request (pause when already paused,
resume when already running) is a success at exit 0 with an `already_*` status,
never a non-zero fault. As with all operability surfaces the behaviour is
service-domain owned and the CLI adapts to it (`service-domain-owns-operability`).

**Phase 2 (defer; design partly open, needs a coordinated GPU maintenance window).**

The crash-safe RELEASE mechanism is decided: a second OS advisory lock - the
"quiesce lease" - beside the identity `service.lock`, distinct from it, held by the
external CI or test actor for the duration of its GPU work. Process death
auto-releases the OS lock, so no external actor's death can leave the lease held.

The daemon-side OBSERVATION and wakeup of that lease is deliberately left as an
open design question the plan must resolve, not settled here, because lazy
checkpoint-time probing has two holes. First, an idle daemon reaches no checkpoint
and runs no search, so it never observes a lease acquire and never frees its
resident VRAM - and idle is the common case exactly when CI wants the GPU, so
"idle is not contending" is false for VRAM. Second, a parked daemon has no running
thread to notice the external actor releasing the OS lock, so automatic resume does
not follow from checkpoint-time probing alone. The candidate observers -
event-driven notification, a bounded timeout re-probe, or an OS-level cross-process
wait - trade off against the codebase's "no free-running timer threads" preference
and must be chosen in the plan. The honest interim answer for the idle case is
phase-1 `server pause`: it is synchronous, an operator or CI pre-step invokes it
directly, and it is the natural site to drive `torch.cuda.empty_cache()` once phase
2 lands. On entering quiesce the daemon calls `empty_cache()` once behind the
centralized `_gpu.load_torch()` gate, never inside the torch-free gate primitive or
the worker checkpoint.

**Yield policy (both phases): service yields to ephemeral, priority by lifetime.**
The long-lived pausable daemon stands down for the short-lived, time-bounded
consumer (CI job, test run): the consumer signals intent, the daemon quiesces at
the next unprotected checkpoint (or synchronously on `server pause`), releases
reclaimable VRAM, the external work runs, the signal clears, and the daemon
resumes.

The pause and resume behaviours are guards under `guard-tests-prove-they-can-fail`,
three of which need both-direction proof. First, "a worker blocks when quiesced"
must fail if the gate is stubbed open (worker proceeds) - the test must join the
parked thread with a bounded timeout so a broken-open gate fails the assertion
rather than hanging the suite. Second, "a worker resumes when released" must fail
if release is broken (worker stays blocked). Third, "shutdown wins over a
concurrent re-pause" - a `pause()` racing a pending shutdown must not re-park the
worker - provable GPU-free by latching an absorbing request and racing a `pause()`,
asserting the worker still unwinds. Each is proven red-then-green in one sequence
and recorded in the execution record. The phase-2 crash-safety guard ("a dead
actor releases the lease") is likewise a both-directions guard, provable GPU-free
by killing a child that holds the lease and asserting the OS frees it.

## Rationale

`threading.Event.wait()` is the zero-CPU professional primitive: it parks on an
internal `Condition`, releasing the GIL and the CPU with no polling, and wakes all
waiters immediately on `set()` (`2026-07-24-service-quiesce-research`). It is the
minimum machinery that satisfies the hard "no idle spin" requirement and is
torch-free, so it can sit on the spawn-worker import chain and in search without
violating the CUDA-isolation and centralized-torch-gate rules. Consulting it only
at unprotected `checkpoint()` sites inherits the sub-second promptness bound the
project already accepts for cancellation, at no new cost, and keeps the hold out of
indivisible-mutation spans.

The correctness subtlety a bare boolean gate hides is that "resume" and "an
absorbing request is pending" are two conditions a woken worker must distinguish; a
naive `Event` exposes a lost-wakeup when a `pause()` races a pending shutdown. A
`threading.Condition` could wait on that disjunction directly, but the
absorbing-open latch collapses it to a single boolean - an absorbing request opens
the gate irreversibly and disables `pause()`/`clear()` while pending - which is
strictly less machinery for the same guarantee. That is why Event-plus-latch is
chosen over `Condition`.

The second-OS-lock lease wins the crash-safe RELEASE question on the one criterion
that is non-negotiable - a dead actor must never leave the daemon paused - because
process death is the release, the same guarantee the identity machine lock already
relies on; a heartbeat-expiry sentinel only lapses after a timeout and needs a
renewal loop. It reuses the most already-hardened machinery (the machine lock's
try-lock probe and machine-global anchoring) and, by being a *distinct* lock,
avoids the fatal flaw of overloading the singleton identity lock (which would admit
a second daemon). The daemon-side observation/wakeup that turns a held lease into an
actual quiesce - and frees idle VRAM - is the genuinely open part, deferred to the
plan. MIG, MPS, and cluster schedulers are all knocked out on the facts - MIG
absent on the hardware, MPS Linux-only with no VRAM isolation, schedulers
disproportionate - leaving the cooperative-checkpoint gate as the only fit for one
Windows workstation with one 16 GiB GPU.

Sequencing phase 1 ahead of phase 2 keeps a fully green GPU-free unit boundary: the
gate, checkpoint and search-admission integration, the CLI envelopes, and the
pause/resume/shutdown-race guards are all pure `threading` or OS code testable on
any host, and they immediately solve daemon-internal contention and manual CI
coordination (`server pause` as a CI pre-step, `server resume` as a post-step).
Phase 2's VRAM release, cross-process auto-handshake, and idle-daemon wakeup are the
only parts that need the live contended GPU or an unsettled observer design, so they
defer without blocking the shippable value.

## Consequences

- **Phase 1 delivers now:** a zero-CPU global pause honoured at every unprotected
  indexer checkpoint and at search admission, an operator or CI control surface
  (`server pause` and `server resume`) with idempotent structured JSON envelopes,
  and three both-direction guard tests - all green on any host, GPU or not. This
  alone lets a human or a CI pre/post-step coordinate the GPU manually and stops the
  daemon's own threads from contending during a borrow.
- **Phase 2 defers, with a stated cost and an open question:** until the
  cross-process lease plus its observer land, the handshake is manual - a failed CI
  job that never runs its `server resume` post-step leaves the daemon paused, with
  no automatic recovery - and the automatic idle-daemon case (free resident VRAM
  when nothing is indexing) has no answer that lazy checkpoint probing can provide.
  Phase 1 `server pause` is the honest interim: synchronous, and the site that will
  drive `empty_cache()` once phase 2 lands.
- **Promptness is bounded, not instant:** a busy daemon yields at its next
  unprotected checkpoint or slice boundary (sub-second); search yields as in-flight
  requests drain under the concurrency cap while new ones are held; an idle daemon
  yields only on an explicit `server pause` until the phase-2 observer exists.
  Mid-kernel work is never preempted. This matches existing cancellation latency and
  is not a regression.
- **New correctness surface to keep honest:** the checkpoint now consults a hold
  gate and an unwind signal, protected-aware and latched. The invariant that
  shutdown always wins over a hold - even against a racing re-pause - is load-bearing
  and defended by the shutdown-race guard; the protected-awareness invariant is
  defended by keeping the gate wait out of every `gpu_lock`, `protected()`, and
  held-store-write span at every checkpoint site, present and future.
- **Opens a general yield pathway:** the service-yields-to-ephemeral handshake and
  the lease-bound quiesce lease are reusable beyond CI - any future ephemeral GPU
  consumer on the box (a one-off benchmark, an interactive experiment) can borrow
  the device through the same cooperative surface without a scheduler.
- **Pitfall guarded by rule:** quiesce must remain a pause, never a stop or kill
  (`storage-maintenance-is-lifecycle-inert`); the cross-process actor borrows the
  GPU and the daemon stays alive throughout.

## Codification candidate

A rule candidate is warranted once phase 1 lands: **"the quiesce gate is torch-free,
protected-aware, and checkpoint-consulted."** The constraint to codify, stated
directly (not as a citation), is that the global pause primitive is pure `threading`
with no torch import so it stays importable from spawn workers and search; that its
wait is consulted only at unprotected checkpoints and at search admission and never
inside a `gpu_lock`, `protected()` span, or held store write; and that any absorbing
shutdown or cancel latches the gate open irreversibly so a quiesced worker can never
block forever, even against a racing re-pause. This complements
`gpu-consumer-single-thread`, `gpu-lock-wraps-forward-passes-only`, and
`torch-loads-through-centralized-gpu-gate`.
