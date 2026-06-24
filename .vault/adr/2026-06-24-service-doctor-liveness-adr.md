---
tags:
  - '#adr'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - "[[2026-06-24-service-doctor-liveness-research]]"
---

# `service-doctor-liveness` adr: `doctor reports live service truth; flapping is diagnosed before it is fixed` | (**status:** `accepted`)

## Problem Statement

GitHub issue **#204** reports that `server doctor` declares the service `ready: true` while
the daemon is dead, and that the daemon "flaps" - coming up healthy and vanishing minutes
later with no explicit stop. The research established the doctor mechanism precisely (it never
probes the live daemon; `ready` is installed-dependency truth computed in the CLI's own
process, where the qdrant dimension reads READY simply because the binary exists on disk) and
enumerated the flapping causes (a daemon spawned inside the launching shell's Windows Job
Object that dies on shell exit; a concurrent CLI command unlinking a live daemon's discovery
file on a transient identity-check miss; the machine-lock-versus-status-dir interaction; a
pre-yield lifespan failure unlinking the just-written file). The orphan-reap and failed-start
cleanup half of #204 is owned by the landed machine-singleton campaign; this ADR decides the
**residual**: making `doctor` tell the truth about a running service, and fixing the flapping

- with the explicit discipline that the flapping causes are *confirmed by diagnosis before
  they are remediated*, since there are several and not all may fire on every host. Grounded in
  `2026-06-24-service-doctor-liveness-research`.

## Considerations

- `doctor`'s `ready` is structurally blind to the daemon: it is computed pre-runtime and the
  qdrant dimension treats "no supervisor in this process" (always true in a CLI) as READY
  (research F1, F2). The live-service truth already exists on the `server status` / `/health`
  path (F3) - the gap is that `doctor` does not consult it.
- `compute_readiness()` is intentionally process-wide and safe to call before the runtime is
  up; it is reused where a daemon must not be assumed, so its semantics should not be changed
  to fold in liveness (F1).
- The flapping has multiple credible causes of differing likelihood (F4-F7); the
  highest-confidence one (the Job-Object breakaway silent fallback, F4) is platform-specific to
  this Windows host. Fixing speculatively without confirming which cause fires risks churn.
- Two flapping causes overlap the machine-singleton campaign (the lock-vs-status-dir
  interaction F6, and the pre-yield unlink F7); those must be coordinated, not double-fixed.

## Constraints

- The no-mock test mandate plus the no-GPU-CI reality: the daemon-survival and doctor-liveness
  tests must run against real processes and the real discovery file locally; flapping
  reproduction is platform-sensitive (Windows Job Objects) and must be exercised on the host.
- Back-compat: `doctor`'s existing dependency report is relied upon as a pre-install check; the
  live-service axis must be added alongside it, not replace it, so a pure pre-install `doctor`
  still works.
- Coordination dependency: F6/F7 touch surfaces the machine-singleton campaign just landed;
  this work must not regress that campaign's guarantees and should defer the lock-scope
  reconciliation to its owners where they overlap.
- No frontier risk; all surfaces (doctor, readiness, spawn, lifecycle) are mature and in-tree.

## Implementation

High-level; a plan sequences it, and the flapping half is diagnosis-gated.

**D1 - `doctor` reports a distinct live-service axis.** Keep `compute_readiness()` as the
pre-runtime "dependencies installed and ready to start" axis, unchanged. Add a live-service
axis to `server doctor`: read the discovery file and probe `/health`/port (reusing the
`server status` lifecycle truth, per the service-domain-owns-operability discipline), and
report whether a service that is expected to be running actually is. When the daemon is dead,
`doctor` must not present `ready: true` unqualified - it reports `ready: false` or an explicit
`degraded` / `needs-restart` status, and the qdrant runtime block reflects the real live state
rather than the binary-on-disk default. The dependency axis stays visible and labelled so the
two are never conflated.

**D2 - Diagnose the flapping before remediating.** A dedicated diagnosis step instruments and
reproduces the candidate causes on this host: the spawn-without-breakaway fallback (does the
daemon survive the launching shell's exit?), and the identity-miss discovery-file unlink (can a
concurrent `status`/`start` delete a live daemon's file?). The confirmed cause set, recorded in
the execution trail, gates which remediations in D3 are applied - causes that do not fire are
not speculatively changed.

**D3 - Remediate each confirmed cause.** Per confirmation: (a) make daemon survival independent
of the launching shell - on a breakaway denial, detach by a means that outlives the parent or
fail loudly rather than silently spawning a daemon doomed to die with the shell; (b) never
unlink the discovery file on an *ambiguous* identity result - unlink only when the holder is
confirmed dead, so a transient `/health`/PID miss cannot delete a live service's file; (c) for
the machine-lock-versus-status-dir interaction and the pre-yield unlink, coordinate with the
machine-singleton campaign owners rather than re-fixing their surfaces here.

**D4 - Regression coverage, no mocks.** Tests assert: `doctor` reports a not-ready/degraded
live status when no daemon is running while still reporting dependency readiness; a daemon
survives a simulated parent-shell exit on this platform; and a concurrent lifecycle command
does not unlink a live daemon's discovery file on a transient identity miss. Real processes and
the real discovery file throughout.

## Rationale

The doctor fix (D1) is the clear, self-contained half: the truth already exists on the status
path, so `doctor` should consult it and stop conflating "dependencies installed" with "service
running" - which is what misled operators and downstream discovery. The flapping half is
deliberately staged diagnosis-before-remediation (D2 before D3) because the research surfaced
several causes of differing confidence and platform-sensitivity; confirming which fire avoids
speculative churn and respects the overlap with the machine-singleton campaign. The remediation
directions follow the research's ranked candidates and the existing operability discipline
(the service domain owns liveness; CLI and MCP adapt to it).

## Consequences

- Gains: `doctor` becomes trustworthy for operators and downstream discovery - a dead daemon is
  reported as such; the dominant flapping cause (shell-scoped daemon death) is identified and,
  once confirmed, fixed so a service started from a terminal survives the terminal closing.
- Costs and risks: the live-service probe adds a round-trip to `doctor` (bounded, like the
  status path); the diagnosis phase has no shippable artifact of its own, which is intended -
  it is the gate that makes the remediation correct. Platform-specific reproduction is
  laborious and must be done on the Windows host, not in CI.
- Pathways: a doctor that distinguishes installed-readiness from live-health, plus a daemon
  whose lifetime is decoupled from the launching shell, make the service materially more
  reliable for the downstream engine consumer that depends on discovery.

## Codification candidates

- **Rule slug:** `doctor-separates-installed-from-running`.
  **Rule:** Service health diagnostics must distinguish "dependencies installed and ready to
  start" from "a service is currently running and healthy", and must never report a dead daemon
  as ready by reading installed-dependency or on-disk-binary state alone.

- **Rule slug:** `never-unlink-live-discovery-on-ambiguous-identity`.
  **Rule:** A lifecycle command may remove the service discovery file only when the holder is
  confirmed dead; a transient or ambiguous identity-check result must never delete a possibly
  live service's discovery file.

  *(Both are candidates only - promoted after the constraint has held across at least one full
  execution cycle, per the codify discipline.)*
