---
tags:
  - '#adr'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-30'
related:
  - '[[2026-07-24-service-quiesce-research]]'
  - '[[2026-06-12-service-concurrency-adr]]'
  - '[[2026-07-23-ci-self-hosted-gpu-runner-adr]]'
  - '[[2026-07-21-service-job-control-adr]]'
  - '[[2026-06-24-service-hardware-singleton-adr]]'
  - '[[2026-07-28-pressure-management-adr]]'
---
# `service-quiesce` adr: `Acknowledged global resource quiescence` | (**status:** `accepted`)

## Problem Statement

The shipped hold gate can report pause before compute drains or resident GPU memory is released. It also shares one mutable gate with every attempt token, so one token's absorbing cancellation can disable later global pauses. A pause that is merely requested, or that retains an admitted worker, project lease, model reference, or VRAM, cannot safely hand the device to another tenant. The accepted job-control, hardware-singleton, and pressure-management records establish the lifecycle, single-machine, and advisory boundaries this amendment must preserve.

## Considerations

- `2026-07-21-service-job-control-adr` requires cooperative control acknowledgement only after execution resources release; a global pause cannot retain a worker or capacity slot and claim quiescence.
- `2026-06-24-service-hardware-singleton-adr` makes the resident service the sole hardware authority. A GPU-borrow lease must therefore be distinct from, and never weaken, the service identity lock.
- `2026-07-28-pressure-management-adr` remains observe-only. Quiesce state is an explicit lifecycle command, not an automatic response to a pressure tier.
- CUDA work remains non-preemptible. The bounded handoff point is a safe checkpoint or completion of a previously admitted GPU section; no wait may occur under `gpu_lock`, a protected mutation, or a store write.
- MCP remains service-only and no-local-fallback. Its existing service-state visibility consumes the controller status; public MCP does not gain lifecycle mutation authority.

## Considered options

- **Keep the process-wide Event hold gate.** Rejected: it can be poisoned by token-local cancellation, retains admitted resources, and cannot truthfully attest VRAM release.
- **Park every running stack until resume.** Rejected: parked jobs and searches retain capacity, leases, and model references needed for release; it violates the acknowledgement boundary.
- **Stop or restart the daemon.** Rejected: quiesce must preserve the resident service, its storage ownership, and logical job identities.
- **Service-owned resource-quiesce controller with cooperative unwind and GPU-residency release (chosen).** It closes admission, drains work, releases GPU residency, and exposes an explicit borrow-safe state.
- **Reuse the service singleton lock as the borrower lease.** Rejected: releasing or sharing identity authority could admit a second service.
- **Acquire borrower authority in the service or use only a PID.** Rejected: neither proves that the process which will use the GPU currently holds the OS lease; PID reuse and a server-owned acquisition permit an unrelated caller to resume or borrow.
- **Add separate borrower lifecycle routes.** Rejected: the authenticated pause and resume routes are the one lifecycle envelope. An optional capability field preserves that contract without duplicating its acknowledgement semantics.
- **Let unreachable service delegation fall back to local GPU work.** Rejected: an uncertain or live singleton is a contention hazard, not permission to allocate CUDA locally.

## Constraints

- The controller, routes, CLI, MCP client, TUI, and discovery paths stay torch-free. GPU release and rebuild route through the central GPU owner only after drain.
- Cancellation and shutdown remain token-local, absorbing control. They may wake or unwind their own attempt but never alter global pause state.
- Global pause preserves logical job identity and desired running intent. It may unwind a current attempt and requeue it after resume; it never claims instruction-pointer continuation.
- The state `quiesced` is reachable only when admissions are closed, all pre-pause compute tickets are drained, managed index resources are released, and resident GPU components are unloaded and cache release has completed. Every other state is unsafe for a borrower.
- A timeout or rebuild failure fails closed: admissions remain closed, the structured outcome says `safe_to_borrow_gpu: false`, and no adapter reports success.
- `warming` remains an admission-closed controller state through GPU rebuild and durable same-ID job recovery preparation. Recovery preparation failure is the typed non-success outcome `resume_recovery_failed`; it does not create a fifth controller state, and the controller remains `warming` with admissions closed.
- Resume recovery considers only active jobs in `paused` or `queued` whose desired state is `running`. It preserves desired `paused` and `cancelled` intent, persists recovery preparation before compute admission opens, and never changes logical job identity.
- Resume recovery holds the job-manager lock only for scan, state mutation, and persistence; dispatch occurs after that lock is released. The registry transition condition serializes transition ownership only, and the GPU lock remains confined to GPU residency rebuild work; these locks are not nested across recovery or admission waits.
- No service start, local fallback, or GPU-live test may silently allocate while a machine singleton is live, undiscoverable, pausing, warming, or otherwise unsafe. Intentional local GPU work requires a distinct machine-global borrower lease and a verified safe condition.
- The existing loopback service token remains mandatory for every pause and resume request. A borrower capability is a second coordination factor, never a replacement for route authentication, and it must not appear in lifecycle snapshots, status, discovery, logs, errors, or tracebacks.

## Implementation

`ServiceRegistry` owns one `ServiceQuiesceController`, not a shared `QuiesceGate`. Its serialized state machine is `running`, `pausing`, `quiesced`, and `warming`, carrying an admission epoch, active compute-ticket count, drain evidence, timestamps, GPU-residency evidence, and optional borrower-lease identity.

Pause closes the current admission epoch, asks active managed index attempts to cooperatively unwind at safe checkpoints, rejects new search work with a retryable quiescing outcome, and waits boundedly for all pre-pause tickets and managed resources to drain. After the drain, the registry serializes with the GPU lock, detaches GPU dependencies from retained project slots without closing stores or Qdrant, releases the shared embedding and reranker objects, and releases allocator cache through the centralized GPU gate. Only then does the route return `quiesced` with `vram_released: true` and `safe_to_borrow_gpu: true`.

Resume enters `warming` and rebuilds the GPU stack while compute admission remains closed. Still in `warming`, the job manager performs an idempotent same-ID recovery-preparation scan over active `paused` and `queued` jobs whose desired state is `running`: eligible paused work is prepared as queued, already-queued eligible work is retained for retry convergence, and desired paused or cancelled work is untouched. The complete preparation result is persisted before the controller opens a new admission epoch. Only after that durable preparation succeeds does the controller transition to `running`; dispatch is scheduled after the job-manager lock is released.

If recovery preparation or its persistence fails, resume returns the typed non-success outcome `resume_recovery_failed`, leaves the controller in `warming` with admissions closed, and schedules no work. A later resume retries the same `paused`-plus-`queued`, desired-`running` scan so partial durable preparation converges without allocating a new logical job ID. This failure is an outcome within the existing four-state machine, not a fifth state.

The service route owns this contract. CLI pause/resume renders the route's one JSON envelope and exits zero only for the achieved terminal state. Health, service-state, jobs output, MCP service-state, and the TUI render the same controller block. The existing pressure block remains an independent advisory.

A borrower uses a second, machine-global advisory lock beside the identity lock. Acquisition creates a private lease record containing the holder PID and a 32-byte cryptographically random, base64url opaque capability; the raw capability is held by the borrower and is valid only while that OS lock remains held, with no clock-based expiry. The borrower obtains and retains that lease before calling authenticated `POST /pause` with the optional JSON field `borrower_capability`, and calls authenticated `POST /resume` with the same field before releasing the lease. Calls without that optional field remain the ordinary operator pause/resume flow.

The body is either absent/an empty JSON object for the ordinary operator flow, or a JSON object whose only borrower field is `borrower_capability: string`; it is a nonempty URL-safe capability, not a PID or a lease identifier. The service verifies a borrower pause by observing both live contention on the borrower lock and an exact constant-time match between the supplied capability and the lease record. It records its private borrower binding only after the ordinary pause has reached the achieved, safe `quiesced` snapshot. While that binding exists, a resume without the matching capability, or a pause/resume carrying a different capability, is rejected without changing controller state; a matching successful resume clears the binding. The lifecycle heartbeat independently verifies the bound lease and, after OS release on borrower death, resumes only that borrower-bound quiescence. It never auto-resumes an unbound operator pause, and it retains bound quiescence if lease verification is unavailable. Lease/capability denials use the existing authenticated lifecycle envelope with `ok: false`, matching `status` and `error`, a message, `retryable: true`, and the unchanged canonical quiesce block: `invalid_borrower_capability` for a malformed body field, `borrower_lease_not_held` when no matching live lease exists, `borrower_capability_invalid` when a live lease does not match, `borrower_lease_unavailable` when the OS lease cannot be verified, `borrower_lease_required` for an unqualified resume of a bound quiescence, and `borrower_lease_mismatch` for a different capability against an existing binding. They reveal neither capability nor PID. The identity singleton lock is never released or repurposed.

## Rationale

Resource quiescence is the smallest truthful lifecycle contract: it preserves service and job identity while making the GPU handoff observable and safe. It applies the job-control acknowledgement rule to the daemon as a whole, keeps GPU serialization and protected-mutation discipline intact, and turns the existing singleton mechanism into a distinct borrower coordination channel without creating a second resident service. Explicit states and fail-closed outcomes prevent automation, tests, or local fallback from treating an unreachable or only partially drained daemon as available hardware.

## Consequences

- Operators and automation receive an exact, idempotent answer about whether GPU borrowing is safe; `paused` is replaced by `quiesced` only after release.
- Running index attempts may restart a convergence attempt on resume rather than preserve a Python stack, but they release resources truthfully and retain logical identity.
- Resume can fail after GPU residency rebuild but before admission reopens when same-ID recovery preparation cannot be persisted. The service then remains safely closed in `warming`, reports `resume_recovery_failed`, and can retry without losing job identity or overriding operator pause or cancel intent.
- Search requests during transition receive a retryable service outcome rather than holding model references or GPU admission.
- GPU residency release/rebuild adds registry lifecycle complexity and requires bounded failure reporting, but does not close stores, stop the daemon, or change pressure policy.
- Intentional local GPU runs become explicit, lease-protected operations. Uncertain service discovery and automatic local fallback become hard refusals.
- Borrower coordination carries a lease-lifetime secret only in the borrower process, lease record, and authenticated request body. This adds strict no-logging/no-projection handling, but binds service acknowledgement and resume authority to current OS-level possession rather than a reusable process identifier.
