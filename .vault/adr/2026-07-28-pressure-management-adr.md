---
tags:
  - '#adr'
  - '#pressure-management'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
related:
  - "[[2026-07-28-pressure-management-research]]"
---

# `pressure-management` adr: `tiered pressure verdict, observe-only first` | (**status:** `accepted`)

## Problem Statement

Under resource contention the system has no response between running at full
pace and failing: it crawls, silently, for as long as the contention lasts.
The grounding in `2026-07-28-pressure-management-research` establishes both
halves of the gap - that the degradation is a sojourn-time phenomenon the
existing telemetry already measures, and that every seam a controller would
need already exists. What is missing is a verdict and a controller reading it.

A decision is needed now because the accepted `2026-07-28-index-observability-adr`
deferred auto-defer-under-saturation explicitly pending degradation evidence,
and nothing in the system currently accumulates that evidence. Every threshold
a future controller must set is unsettable until something records pressure
against outcomes. That recording is itself a decision about vocabulary,
placement, and surface, and making it ad hoc inside a later behavioural change
would fix the architecture by accident.

## Considerations

- The pipeline is already a bounded producer/consumer chain with clean
  backpressure; the seams a ladder would act on are named and hardened in the
  grounding, so no new mechanism is required for a first increment.
- Every probe the verdict would read already reports absence rather than
  raising, so a service-domain evaluator built on them inherits torch-free-host
  safety without a new guard.
- The GPU memory figures are device-wide, so they observe foreign processes -
  which is the defining signal of the incident and the reason a process-local
  view would have seen nothing.
- The incident job was healthy work on a starved card and completed unmodified.
  Any rule that would have acted on it would have been wrong.
- A flapping verdict is worse than no verdict: every rung a later stage adds
  assumes the tier is stable enough to act on.
- Entry points must adapt to service-domain behaviour and never own it, so the
  verdict has exactly one home regardless of how many surfaces render it.

## Considered options

- **Do nothing until evidence arrives.** Rejected: nothing currently produces
  the evidence, so the deferral is self-perpetuating.
- **Compute the tier and ship the deferral rungs together.** Rejected: the
  thresholds the rungs need are precisely what is unmeasured, so the rungs
  would be tuned by guess against a live GPU. The incident shows the cost of
  guessing wrong is acting on healthy work.
- **Compute the tier, change no behaviour (chosen).** Pure addition over
  existing probes; generates the calibration data every later rung needs; the
  worst failure mode is a mislabelled record.
- **Per-process pressure view instead of a machine view.** Rejected: it cannot
  see the foreign load that caused the incident.
- **Extend the per-job degradation verdict to carry machine pressure.**
  Rejected: "is this job healthy" and "is this machine under pressure" are
  different questions with different subjects; collapsing them would make the
  job verdict answer for conditions the job did not cause.

## Constraints

- The verdict must sit on the torch-free service call path, so it may read only
  the guarded read-only probes and must treat every absent probe as absence
  rather than as a nominal reading.
- Threshold calibration is the dependency this record cannot discharge: the
  values chosen here are provisional by construction, and only the observation
  history this decision creates can settle them.
- The backend-latency band has no measured baseline, so latency may inform
  `elevated` only as a sustained relative signal, never as a fixed bound.
- Cross-process coordination for non-daemon indexers depends on durable state
  this record deliberately does not create; anything needing it is out of scope
  until its own stage.
- No parent feature is unstable: the probes, admission gate, retry state, and
  slice boundaries this builds on are all landed and exercised.

## Implementation

A service-domain evaluator computes one machine-level pressure tier -
`nominal`, `elevated`, `critical` - as a sibling of the per-job degradation
verdict, sharing its evidence-block shape and its adapters. It is sampled on
the jobs-envelope cadence, using the existing probe-cache period as its sample
clock, and it lives beside the existing degradation evidence so the two cannot
drift apart.

Tier assignment is asymmetric in kind, not merely in threshold. GPU signals
alone never reach `critical`: saturation with a stretched forward pass is
`elevated`, because that is the shape of healthy work on a contended card.
`critical` requires store-side or liveness evidence - an unanswered backend
probe, repeated timeout or unavailable classifications, a typed disk failure in
the window, or a dead encode thread with a forward in flight. This asymmetry is
the load-bearing part of the model; the numeric thresholds are not.

Hysteresis is fast-attack, slow-release. A tier is entered on a short run of
consecutive samples over its enter condition and left only after a
substantially longer continuous clear window, so escalation is responsive while
de-escalation cannot oscillate. The forward-age signal reuses the existing
service-wide degraded and stall thresholds rather than minting parallel
constants.

Each transition is recorded to the managed log with its evidence, so tier
history accumulates against job outcomes. That history is the deliverable: it
is what makes the deferred thresholds settable.

The surface is one `pressure` block on the jobs envelope carrying the tier, the
instant it was entered, and the evidence, rendered from that single block by
every adapter. Transitions emit structured log events; metric gauges are left
to whichever stage first needs them.

Nothing acts on the tier. No job is deferred, paced, shrunk, or refused by this
record. The ladder, its ordering, and the boundaries below are fixed here so
later stages cannot reorder or widen them ad hoc, but none of it is authorized
by this decision.

Fixed for any later stage:

- The rung order is: defer automatic index jobs; inter-slice yields; space or
  coalesce storage writes; pause non-essential producers; refuse new automatic
  admissions with an honest retry-after. Batch-size adaptation is excluded from
  the first implementation - it trades against a deliberate padding
  optimisation and its relief is the least certain of the rungs.
- Automatic work only. Operator-initiated jobs are never deferred, refused, or
  paced; they are informed. Initiator attribution already exists at admission.
- Searches are never degraded, delayed, or refused at any tier.
- The one-GPU-consumer boundary is retained. The pressure system reads
  device-wide probes and acts at slice boundaries, so it does not depend on
  device count.
- Backoff shapes are drawn from what exists: the centralized capped exponential
  with full jitter for deferral and retry-after, additive-increase
  multiplicative-decrease for pacing, a token bucket for write governance. No
  new curve is minted.
- Governance state is in-daemon. Every service-path index job already runs
  inside the machine singleton, so in-daemon state governs the whole service
  write stream with no new inter-process channel. A durable cross-process
  ledger is deferred until a stage demonstrates it is needed.
- Staleness fails open: an absent, silent, or stale verdict is `nominal`. This
  deliberately inverts the storage-grace rule, because the asset protected here
  is availability of foreground work rather than data.

## Rationale

Observe-only wins on a knockout criterion: the thresholds every behavioural
rung requires are unmeasured, and the grounding shows the one live incident
would have been misjudged by the most obvious rule anyone would have written
from first principles. Shipping a controller now would tune it by guess against
a resource that behaves differently under foreign load than under our own.

Reusing the existing degraded and stall thresholds rather than introducing
independent constants is chosen for the same reason in reverse: with no
behaviour attached, a wrong threshold costs a mislabelled record and nothing
else, whereas a second set of age constants for the same measurement is a
drift surface that would outlive the uncertainty that justified it. Calibration
comes from the history, then the constants are revisited.

Restricting the ladder to automatic work is a judgement about who has context.
An operator who typed the command is present and knows why; degrading their
explicit request converts a performance problem into a trust problem, and the
system has no way to know their intent is less urgent than its own throughput.

In-daemon governance is chosen over durable cross-process state because it
achieves the governance goal for everything the system actually controls at
zero new cost, while the population a ledger would reach - foreign fleets and
duplicate corpora - is one the governor could only cushion. The grounding
identifies worktree index reuse as the higher-leverage attack on that specific
load source, and that is a separate decision.

## Consequences

Gains: the deferred decision becomes settable, because tier history against job
outcomes is exactly the evidence it was deferred pending. Operators gain a
machine-level answer to "is it slow because of us" that no per-job verdict can
give, and the incident class becomes visible instead of silent.

Honestly framed: nothing gets faster. A user in the incident's situation still
waits, and now sees a label explaining why. The value is entirely in what the
labelling makes possible next, so the record is only worth its cost if a later
stage actually consumes the history.

Difficulties: the evaluator must stay genuinely cheap on a path that runs on
every envelope, and it must not become a second place where degradation
semantics live. The provisional thresholds will produce some mislabelled
records, and the history must be read with that in mind rather than treated as
ground truth.

Pathways opened: each rung becomes independently adoptable against measured
thresholds, in a fixed order, without reopening the vocabulary or the surface
contract.

Pitfalls: a tier nobody consumes is dead weight and should be removed rather
than carried; a tier that flaps would poison the very history it exists to
produce, which is why the release window is long; and the temptation to let one
rung slip in early - because the seam is right there - would forfeit the
calibration this decision is entirely about.
