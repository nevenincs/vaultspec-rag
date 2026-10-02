---
tags:
  - '#adr'
  - '#monitor-lifecycle'
date: '2026-10-02'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:82bf4f815d6f6b7caa7af02fc2f860db6953ecf8b0711b27d262eba4d599b528'
related:
  - "[[2026-10-02-monitor-lifecycle-reference]]"
  - "[[2026-09-30-monitor-browser-adr]]"
  - "[[2026-09-30-monitor-tooling-adr]]"
  - "[[2026-07-21-machine-discovery-recovery-adr]]"
  - "[[2026-06-24-service-discovery-schema-adr]]"
---

# `monitor-lifecycle` adr: `Couple the local monitor to managed server lifecycle` | (**status:** `accepted`)

## Problem Statement

Server start currently supplies no monitor. The user requests automatic frontend startup, backend-port-plus-one allocation with upward retries, user scratch discovery, and coupled stop. Evidence is in `2026-10-02-monitor-lifecycle-reference`.

## Considerations

The existing local bridge owns automatic credentials and delegates controls to canonical service owners. Windows forcibly kills the daemon, so lifespan cleanup alone cannot guarantee frontend teardown. The complete owner-published snapshot must preserve the assigned monitor port across heartbeat repair. The user subsequently clarified that managed startup must consume resources compiled from our sources, and supplied the separate delivery session's Bun executable direction. No compiled artifact exists yet.

## Considered options

- A daemon-owned compiled monitor executable retaining the existing bridge: chosen following the user's explicit compiled-resource clarification.
- Daemon-owned source-checkout Vite startup: used for the initial lifecycle proof, then removed from managed startup because the user requires prebuilt resources.
- A separately started fixed-port monitor: rejected for managed use because it cannot satisfy the requested start/stop coupling.
- A new Python copy of browser forwarding behavior: rejected because it duplicates the existing bridge and expands the migration surface.

## Constraints

The user's 2026-10-02 request authorizes coupling start and stop, scanning upward from the actual backend port plus one, recording the actual assignment in user scratch, and clearing it on stop. Their same-day clarification requires prebuilt monitor resources. CI, frontend compilation and packaging remain excluded and owned by the separate session.

Managed startup launches only the compiled `vaultspec-rag-monitor` executable. Resolve an explicit absolute `VAULTSPEC_RAG_MONITOR_BINARY` override, otherwise the installed command on PATH. Do not compile, acquire dependencies or fall back to checkout-local Vite during service startup. Missing or incompatible executables fail the coupled start before model warming. Package installation and verified binary acquisition belong to delivery; this launcher performs no download or provisioning.

Share the backend's loopback bind probe to scan upward before spawning. The compiled monitor must continue upward if another process wins the bind race, without wrapping or leaving 1..65535. Do not alter the backend's existing occupied-port refusal. Treat monitor startup failure as a failed coupled start and clean up the child.

Publish additive monitor port/PID/incarnation diagnostics in the canonical daemon snapshot and retain a user-scratch identity record for forced-stop recovery. Repeated server start reuses a live monitor. Process cleanup requires verified PID incarnation and must preserve a live successor's state. A broken parent pipe closes the frontend even when daemon teardown is bypassed.

This is an explicit managed-runtime exception to fixed manifest ports and independent source-development lifecycle in monitor-tooling and monitor-browser. Their shared development harness, declared network/origin policy, server-only credentials, service behavior owners and standalone dev/preview commands continue to govern source development.

## Implementation

The HTTP daemon constructs one torch-free Python supervisor, starts it after singleton acquisition, publishes its assignment, and stops it during rollback/shutdown. Canonical CLI stop also performs verified orphan cleanup and fails if the frontend survives. Canonical start output reports the assigned monitor URL.

Consumer contract for the delivery session: invoke the compiled command with `--managed --port STARTING_PORT`, from user scratch rather than a checkout. Supply the actual backend port via `VAULTSPEC_RAG_PORT`, the scratch directory via `VAULTSPEC_RAG_STATUS_DIR`, and the initialized owner's absolute interpreter via `VAULTSPEC_RAG_MONITOR_PYTHON`. The child emits exactly `vaultspec.monitor.ready ACTUAL_PORT` followed by a newline after binding, keeps stdin open for the parent's ownership pipe, and exits within five seconds of EOF. The parent supervises the executable directly rather than a compiler or package-runner wrapper. Matching flag spelling is an implementation detail to reconcile with the producer before binary integration verification.

Positive launch/HTTP/parent-death verification requires the real compiled executable. Keep those checks explicit and report their pending prerequisite until delivery provides it; prototype Vite evidence does not establish delivered-binary correctness.

## Rationale

Owning the monitor beneath the daemon ties its lifetime to the requested service lifetime. A prebuilt executable meets the user's runtime requirement while retaining the existing bridge and canonical service owners. Complete discovery snapshots maintain assignment through self-healing publication.

## Consequences

Managed service startup requires the installed compiled monitor command. Frontend source tooling remains confined to development and compilation. The lifecycle implementation cannot complete delivered-binary validation until the other session builds the artifact. Stopping through a managed browser ends that browser's web server as well as the backend; standalone development monitors retain their own lifecycle.
