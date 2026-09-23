---
tags:
  - '#adr'
  - '#status-messages'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:472afbd9c439dccc6eb47d42a2fb87debe60a20d5e4fe714ab672533778354f3'
related:
  - "[[2026-09-23-status-messages-adr]]"
  - "[[2026-09-23-status-messages-audit]]"
  - "[[2026-06-24-service-doctor-liveness-adr]]"
---

# `status-messages` adr: `exit codes and degradation codes for the typed operator state` | (**status:** `deprecated`)

## Problem Statement

Authorized as recommended on 2026-09-23 and applied to
`2026-09-23-status-messages-adr`; this proposal is retired.

Implementing `2026-09-23-status-messages-adr` left three choices the accepted record
does not settle, all recorded in `2026-09-23-status-messages-audit`:

- **Degradation codes.** The record lists `JOB_STALLED`. The service emits
  `JOBS_STALLED`, a count of jobs, and also emits `JOBS_DEGRADED`, which the record
  does not list.
- **An `error` health verdict.** `ServiceLifecycle` owns the broker exit code, so a
  service that answers its port with the verdict `error` is `running` and exits 0.
  Before the change, any verdict other than `ready` exited 4.
- **A starting service in `server doctor`.** Doctor liveness now comes from the
  lifecycle, so a starting service is live. `server doctor` then exits 0, with
  `ok: false` and status `starting`, where it used to exit 1.

This proposal amends the accepted record. It does not replace it.

## Considerations

- **Brokers key on exit codes** (0 running, 3 stopped, 4 fault, 5 starting). Any change
  to what a code means must be deliberate
  (`2026-06-11-service-status-convergence-adr`).
- **Paused and degraded are not faults.** The accepted record requires that a paused
  or degraded service stop reading as unreachable. Both still answer requests or
  deliberately hold.
- **`error` is different.** The service reports `error` only when models are not loaded
  and it never finished starting (`src/vaultspec_rag/server/_lifespan.py`). It cannot
  answer a search.
- **Doctor exit weighting.** The doctor-liveness decision raises the exit code for a
  dead daemon that was expected to be running. A starting daemon is neither dead nor a
  divergence.

## Considered options

- **Degradation codes:**
  - A. Amend the record's member list to the emitted codes. Recommended: the wire
    already carries them and a count is the accurate reading.
  - B. Rename the code to `JOB_STALLED`. This changes a wire value for spelling alone.
- **An `error` health verdict:**
  - A. Lifecycle alone owns the exit code, and health never raises it. This is
    today's behaviour.
  - B. An `error` verdict raises the exit code to 4. Paused and degraded stay 0.
    Recommended: it restores the old broker behaviour for a service that cannot
    serve, and still meets the record's intent for paused and degraded.
- **A starting service in `server doctor`:**
  - A. Exit 0, with status `starting`. This is today's behaviour. Recommended: nothing
    is wrong and nothing needs an operator.
  - B. Exit 1, treating it as a warning, as before.

## Constraints

- One envelope per exit, and a non-zero exit when the requested state is not
  achieved (the service-surface rule).
- The exit code keeps a single owner. If option B is chosen for the `error` verdict,
  the lift is one rule in the lifecycle composition, not a second derivation in a
  renderer.

## Implementation

If authorized as recommended, three changes follow:

- **Degradation codes:** amend the member list in `2026-09-23-status-messages-adr` to
  the emitted codes. No code change.
- **An `error` health verdict:** add one rule where a port-answering service's
  lifecycle is composed: a parsed `HealthVerdict.ERROR` yields a fault lifecycle with
  exit 4. Add a mutation-checked test beside the probe-sentinel tests, and add a
  changelog line.
- **A starting service in `server doctor`:** keep exit 0, and record the change in the
  release note.

## Rationale

Each recommendation keeps the exit code a statement about whether the service can do
its job. A service that cannot serve is a fault. A paused, degraded or starting service
is not.

## Consequences

- **Gain:** brokers regain a fault signal for a service stuck in `error`.
- **Cost:** option B for the `error` verdict needs one more behavioural change after the
  feature's plan closed, delivered as a follow-on Step.
