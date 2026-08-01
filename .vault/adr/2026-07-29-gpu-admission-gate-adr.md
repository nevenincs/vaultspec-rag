---
tags:
  - '#adr'
  - '#gpu-admission-gate'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:9aba6ac095b2a0a02628df9dd23a179160872afed1469249ddb169c7542a5390'
related:
  - "[[2026-07-29-gpu-admission-gate-research]]"
  - "[[2026-07-24-service-quiesce-adr]]"
  - "[[2026-07-24-index-cuda-ceiling-adr]]"
  - "[[2026-07-24-index-cuda-shared-device-adr]]"
  - "[[2026-07-28-pressure-management-adr]]"
  - "[[2026-07-23-ci-self-hosted-gpu-runner-adr]]"
  - "[[2026-06-12-service-concurrency-adr]]"
---

# `gpu-admission-gate` adr: `fail-fast GPU admission gate and structural parallel-GPU-test ban` | (**status:** `proposed`)

## Problem Statement

Concurrent agent-launched pytest processes each loaded the embedding and
reranker stacks onto the one 16 GiB RTX 4080 SUPER, starved VRAM, and crashed
the workstation. Nothing in the system refuses at either seam where refusal is
cheap: `load_torch()` admits every model load on nothing but CUDA presence,
and the test suite's only anti-parallelism measure is an xdist grouping that
misses two of the slow tiers, says nothing across pytest processes, and does
not prevent VRAM overlap even where it applies
(`2026-07-29-gpu-admission-gate-research`). The CI GPU job checks only that
CUDA is visible and its own comments record shared-GPU contention as unsolved.
A decision is needed now because the crash class is live - any two concurrent
GPU consumers reproduce it - and because
`2026-07-24-index-cuda-shared-device-adr` explicitly deferred the multi-tenant
case to exactly this space. The requirement is instant fail-fast refusal
before a model load and before a test run, plus a ban on parallelised GPU
tests enforced in code, not comments.

## Considerations

- The device-wide free-memory reading exists, is torch-tolerant, and sees
  foreign processes; a second reader is forbidden
  (`2026-07-29-gpu-admission-gate-research`, `canonical one-reader` finding).
- Once a process's own models are resident, a device-wide reading counts that
  residency as pressure, so an admission predicate is only meaningful before
  the first load (`2026-07-29-gpu-admission-gate-research`).
- The pressure tier is history-based, daemon-resident, observe-only, and
  fails open on staleness - the wrong shape and the wrong authority for a
  synchronous safety gate (`2026-07-28-pressure-management-adr`,
  `2026-07-29-gpu-admission-gate-research`).
- The per-job CUDA ceiling and baseline-net enforcement govern admitted work
  and are settled; this record must not re-litigate that arithmetic
  (`2026-07-24-index-cuda-ceiling-adr`,
  `2026-07-24-index-cuda-shared-device-adr`).
- Quiesce is implemented but unwired from tests and CI, and the shipped pause
  frees no VRAM - the resident stack stays on the card, so a free-memory
  preflight against a paused daemon still refuses
  (`2026-07-29-gpu-admission-gate-research`).
- The crash-safe cross-process pattern is the OS advisory lock whose release
  is process death; the machine already runs two instances of it
  (`2026-07-29-gpu-admission-gate-research`).
- Pytest containment redirects every configured singleton path into a
  per-session temp root, so a mutex anchored through configuration is private
  to each session and useless across processes
  (`2026-07-29-gpu-admission-gate-research`).
- The one-GPU-consumer-thread and `gpu_lock` architecture is fixed
  (`2026-06-12-service-concurrency-adr`); the CI security posture -
  dispatch-only, no fork-reachable path to the runner - is fixed
  (`2026-07-23-ci-self-hosted-gpu-runner-adr`).
- The user asked the system to signal and refuse, never to wait or queue.

## Considered options

Admission placement:

- **Inside `load_torch()`, evaluated once per process before the first
  successful load, latched thereafter (chosen).** Single existing choke
  point; zero hot-path cost; self-residency cannot poison later readings
  because there are no later readings until the latch is re-armed by a
  resident release.
- **Per-call evaluation in `load_torch()`.** A driver query per search
  encode, and the gate eventually refuses the process it already admitted
  once its own models are resident. Rejected.
- **At each model constructor.** Two-plus enforcement sites that drift; the
  canonical-code discipline exists to prevent exactly this. Rejected.

Contention predicate:

- **Free-VRAM floor from the existing guarded probe (chosen).** One
  synchronous reading, works identically in daemon, CLI-local, and pytest
  processes, and subsumes foreign-process detection - refusal is about
  insufficient room, not about who holds it.
- **Foreign CUDA process detection via NVML enumeration.** New dependency
  surface answering a question the floor already answers; "a foreign process
  exists" is not the harm, "not enough room" is. Rejected as the predicate;
  available later as diagnostic enrichment only.
- **Consume the pressure tier.** Needs tens of seconds of daemon-resident
  history a fresh process does not have, fails open on staleness, and the
  governing record forbids acting on it. Rejected.

Cross-process coordination:

- **Detection plus a load-window OS try-lock (chosen).** The free-floor
  reading and the model load are bracketed by a non-blocking OS advisory
  lock held only across that window: a concurrent loader is refused
  instantly, the check-then-load sequence is atomic across processes, and
  the lock is never held across residency so it cannot wedge; process death
  releases it, so no state is ever stale.
- **Detection-only.** Simplest and deadlock-free, but cannot close the
  simultaneous-load race: two processes both read the same free figure, both
  admit, both load. That race is the incident. Rejected alone; retained as
  the degraded mode when the lock file itself is unreachable.
- **A residency lease held for the model lifetime.** Distinguishes "loaded"
  from "about to load", but an open-ended lease is the wedge class the
  quiesce record deliberately deferred, and residency is already visible to
  the free reading without any lease. Rejected.

Parallel-GPU-test ban:

- **Refuse the session at collection time when slow-tier tests are selected
  under xdist distribution (chosen).** Extends the existing collection-time
  tier enforcement; the misconfiguration is surfaced, not absorbed.
  `group_gpu_items` is deleted with it - a session that cannot distribute
  GPU tests has nothing left to group, and grouping never prevented VRAM
  overlap anyway (residency persists on a worker across serialised tests).
- **Extend grouping to `cuda` and `subprocess_gpu`.** Fixes the confirmed
  grouping defect but keeps a mechanism that is insufficient in kind: it
  serialises execution, not residency, and is blind across processes.
  Rejected.
- **Silently force `-n 0` for GPU selections ("refuse to distribute").** Runs
  something other than what the operator asked for; hides the
  misconfiguration the refusal should teach. Rejected.

Cross-process test admission:

- **A machine-global GPU-session OS try-lock acquired in
  `pytest_runtestloop` when selected items carry any slow tier (chosen).**
  Mirrors the HF-token fail-fast precedent; a second GPU pytest session
  exits non-zero immediately, naming the holder; death releases the lock.
- **Infer siblings from pytest session temp roots.** Session roots exist for
  unit-only runs too; too coarse to distinguish a GPU session. Rejected.
- **Free-VRAM reading alone.** Cannot see a sibling that has been admitted
  but has not yet allocated. Rejected alone; retained as the second check
  behind the session lock.

Relationship to yielding the device:

- **Measure and refuse on this feature's own readings; make no request of any
  other tenant (chosen).** Load management and awareness is the whole of this
  record: report the device's condition, and refuse before a load or a test
  run when that condition is contended. Whether a resident tenant should then
  be asked to stand down - and what standing down must free to be worth
  asking - is a separate decision with its own record, being taken
  concurrently. Keeping them separate means the refusal is correct with or
  without a yielding mechanism, and the two records can be reconciled rather
  than one having silently assumed the other.
- **Drive a pause from the preflight and make pause release the resident
  stack.** Turns a refusal into a negotiation, and makes this record's
  correctness depend on an increment it does not own; the shipped pause frees
  no VRAM, so this record would have had to specify the release too, annexing
  a decision that belongs elsewhere. Rejected as out of scope, and left as a
  seam: a lane that makes yielding real can compose it ahead of this
  preflight without changing anything decided here.
- **Refuse only, and treat a resident tenant as permanently disqualifying.**
  The honest consequence of refusal without any yielding path: on this
  workstation the daemon holds models almost always, so the GPU lane refuses
  until an operator intervenes. Accepted as this record's actual cost rather
  than rejected - it is the correct behaviour for an awareness feature, and it
  is what makes the concurrent yielding work worth doing. Stated plainly in
  Consequences.

## Constraints

- The admission predicate reads only the existing guarded probe functions;
  no second `mem_get_info` reader may appear. The predicate runs inside
  `load_torch()`, which only compute paths call, so the MCP server, service
  client, and CLI service-control paths stay torch-free and the read-only
  probe paths (`/health`, `/metrics`, readiness, memory probe) are
  untouched - they never call `load_torch()` and keep reporting `cuda=False`
  on a torch-free host.
- The admission floor is configuration beside the existing CUDA knobs
  (`src/vaultspec_rag/config/_settings.py:308`), denominated in MiB like its
  neighbours. Its default is provisional by construction - the expected
  resident-stack demand plus the existing 2048 MiB headroom figure - and is
  calibratable from the same observation history the pressure record
  accumulates; the *predicate shape* (free below floor refuses) is fixed
  here, the numeral is not.
- Both new OS locks reuse the shared fd-lock helpers and the
  acquire/try-probe idiom of the machine lock; no new locking mechanism is
  invented. The GPU-session lock anchors machine-globally outside the pytest
  containment root, deliberately and documentedly exempt from the
  containment guard: the GPU is machine hardware, not per-session singleton
  state, and a contained lock would be private to each session and protect
  nothing.
- The collection-time refusal and the run-loop refusals are guards and must
  each be proven able to fail on the assertion they name - broken open, run
  alone, watched to fail, restored - per the project's guard-test
  discipline.
- The implementation cites nothing back to this record or any vault
  document; constraints are stated in the code's own prose.
- Parent stability: `load_torch()`, the memory-probe readers, the tier gate,
  the machine-lock machinery, the quiesce gate, and the registry release
  path are all landed and exercised. The only parent extended rather than
  consumed is quiesce (pause gains the release step); its record anticipated
  exactly that extension at exactly that site.
- The CI job keeps its dispatch-only trigger, runner labels, permissions,
  and concurrency settings unchanged; the preflight adds no secret exposure
  and no fork-reachable path.
- Delivery is split across concurrent lanes, and this record's implementation
  is not all one lane's to build. The test-harness layer - the collection-time
  parallel-GPU ban, the cross-session GPU admission lock, and the local and CI
  GPU lane entry points - is built first and independently, because it removes
  both incident preconditions without touching backend internals. The load-seam
  admission predicate inside `load_torch()`, the quiesce resident-release
  increment, and the operator diagnostics surface are owned by the concurrent
  global-pause and admission lanes and are not implemented here; their records
  are to be cross-referenced against this one, and any divergence reconciled,
  before those increments land. The harness layer therefore refuses on its own
  readings and must not depend on a pause that releases VRAM: driving quiesce
  from the preflight is a seam left open for the owning lane, not a
  prerequisite. Deleting `group_gpu_items` stays with the harness layer that
  supersedes it.

## Implementation

**Load admission.** `load_torch()` gains a pre-load admission step, executed
only when torch is about to be loaded for compute and no admission is
latched: acquire the load-window lock non-blocking (an OS advisory lock in a
machine-global anchor, held only across check-plus-load); refuse instantly
with a typed, stable message - in the mould of the existing
`CUDA_REQUIRED_MESSAGE` - when the lock is held by another loader; read
device-wide free memory through the existing guarded probe; refuse, naming
free, floor, and remediation, when free is below the configured floor;
otherwise proceed with the load, sample the resident baseline as today, latch
the admission, and release the lock. The latch makes every subsequent
`load_torch()` call exactly as cheap as today. The resident-release path
(below) clears the latch, so a reload after a release re-admits against
current free memory rather than riding a stale verdict. When the lock file is
unreachable (I/O error, unwritable anchor), the gate degrades to
detection-only with a logged warning rather than refusing all compute on a
filesystem hiccup - the floor check still stands, and degrading protection is
preferred to converting a disk fault into a GPU outage.

**In-session test ban.** The collection hook that already enforces tiers
gains the structural ban: when any selected item carries a slow tier
(`SLOW_TIERS`, which already includes `cuda` and `subprocess_gpu`) and the
session is running under xdist with more than zero distributed workers, the
session is refused at collection with an operator-facing message naming the
offending selection and the serial lane to use. `group_gpu_items` and its
call site are deleted in the same change, and the tests that exercised
grouping are repointed at the refusal, per the canonical-code rule.

**Cross-session test admission.** `pytest_runtestloop`, beside the existing
HF-token fail-fast, gains a GPU preflight for sessions whose selected items
carry any slow tier: try-acquire the machine-global GPU-session lock,
`pytest.exit` non-zero naming the holder pid when it is contended, hold it
for the session (the OS releases it however the session dies); then take one
free-floor reading through the same guarded probe and exit non-zero when the
card lacks headroom, reporting what is resident and what the floor requires so
the operator can act on the reading. `subprocess_gpu` children inherit
protection from the parent's session lock; their own loads pass through the
load admission above.

**Awareness surface.** Per the service-surface discipline the condition is
service-domain owned and adapters render it. The health/status diagnostics gain
a torch-tolerant device-load block - free, total, floor, and the resulting
verdict - reported as absent (never raised) on a torch-free host, so an
operator and a lane read the same figures from the same owner. One preflight
verb on the server command group is the composable form of that reading:
evaluate the device against the floor and emit exactly one structured envelope
on every exit path, exit 0 when the device admits work, exit 1 when it does
not. The verb asks nothing of any tenant and mutates nothing; it is a
read-only-probe-class consumer of the guarded memory functions and performs no
compute. That is deliberate - it makes the verb safe to run anywhere, and it
is the seam a yielding mechanism composes ahead of rather than inside.

**Lanes and CI.** The GPU test lane's entry points run the preflight verb
before pytest: locally as the documented first step of the serial lane, in CI
replacing the CUDA-visibility step (admission implies visibility - the probe
reports absence on a CUDA-less host and the floor check then refuses). A
refused preflight fails the lane before a single model is loaded, which is the
whole point: the tier does not start on a card that cannot hold it.

**Fail-fast.** No path in this feature waits, retries, queues, or negotiates.
Every check is one reading and one verdict.

## Rationale

The load-seam placement wins on a knockout: the reading is only meaningful
before the process's own models are resident, and `load_torch()` is the one
site every compute path already funnels through - the admission point and the
canonical choke point are the same line of code, so enforcing anywhere else
either duplicates the gate or checks too late. The latch is not an
optimisation but a correctness device: it is what stops the gate from reading
its own residency as foreign contention, and clearing it on resident release
is what keeps the verdict honest across a pause cycle.

The free-floor predicate wins because it is the only option that is
synchronous, process-shape-independent, and already implemented. The
simultaneous-load race is the one hole detection cannot close, and the
load-window lock closes it with the cheapest correct tool the project owns:
the same crash-safe OS lock pattern already trusted twice, narrowed to a
window so short it cannot wedge anything. The storage-discipline instinct -
unverifiable state must never shorten protection - is honoured in the only
direction that matters here: there is no state to go stale, because death is
release and the lock outlives no process.

Refusing the session beats every grouping variant because grouping was
solving the wrong problem: it serialises execution within one process while
the incident was VRAM overlap across processes and across residencies.
Keeping a mechanism that passes tests while not preventing the harm is the
precise failure mode the guard-test discipline warns about, and the
canonical-code rule requires deleting it once the refusal supersedes it. The
session lock then covers the axis no in-process mechanism can see.

Confining the record to measurement and refusal wins because the alternative
annexes a decision this feature does not own. Asking a tenant to yield is only
meaningful if standing down actually frees the card, and the shipped pause does
not - so specifying the preflight as a pause driver would have forced this
record to also specify what pause must release, which is another feature's
decision being taken concurrently. Two records each assuming the other is how
architectures drift. Measurement and refusal stand alone, are correct with or
without a yielding mechanism, and leave that mechanism a clean composition
point: the preflight verb reads and reports, and anything that wants to change
the reading first runs before it.

Fail-fast over queueing follows the requirement, and the honest cost is
accepted: a transient spike refuses work that would have succeeded seconds
later, and retry is the caller's decision, not the gate's.

## Consequences

- Both incident preconditions are structurally removed: a second GPU pytest
  session on the machine exits immediately at the session lock, and any
  blind concurrent model load is refused at the load-window lock or the
  floor. The failure mode moves from a crashed workstation to a one-line
  non-zero exit naming the contention.
- The GPU CI lane gains its first real availability preflight; a resident
  daemon no longer wedges the runner or nondeterminises results, because the
  lane clears the card before pytest starts and returns it afterwards. The
  known residual: a runner crash between pause and resume strands the daemon
  held until an operator resumes it - unchanged from the quiesce record's
  standing gap, now simply exercised more often; the always-run resume step
  bounds it to hard crashes.
- Local-mode first-load refusal is new behaviour: a local search or index on
  a contended card now fails fast with remediation instead of loading into
  near-OOM. In service mode - the default - search is unaffected, since
  models are resident long before any query; the pressure record's
  "searches are never refused" clause governs tier-driven behaviour and is
  not contradicted by a load-time admission refusal, but the distinction
  must stay legible in both records.
- Pause becomes heavier: it now releases model stacks, so resume-then-first-
  use pays the full lazy reload (tens of seconds). That is the honest price
  of a pause that actually yields the card; operators who want a light hold
  no longer have one, and if that need materialises it is a new decision,
  not a regression of this one.
- The admission floor's default will be wrong in some direction until
  calibrated; too high refuses legitimate loads on a busy-but-adequate card,
  too low admits into near-OOM where the existing ceiling and OOM backoff
  remain the net. The predicate shape is fixed precisely so the numeral can
  move on evidence without reopening the design.
- Two new machine-global lock files exist outside pytest containment; the
  exemption is deliberate but is also a precedent that must not widen -
  every other singleton effect remains contained, and the exemption's
  justification (hardware, not state) is the test for any future candidate.
- Deleting `group_gpu_items` removes the only xdist-grouping usage; any
  future wish to mix GPU and non-GPU tests in one distributed session is
  foreclosed rather than half-supported, and would need to revisit this
  record.
- Pathways opened: the admission block on the diagnostics surface is the
  natural home for later NVML per-process enrichment (who holds the card),
  and the GPU-session lock is a ready-made consumer for the quiesce phase-2
  lease/observer when that design lands - the preflight verb's pause step
  would then become automatic.
