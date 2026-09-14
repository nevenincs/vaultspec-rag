---
tags:
  - '#audit'
  - '#index-throughput'
date: '2026-09-14'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:6e761c823e86c50c08642ddce1580780c2cd56970ea80b89b6232838970ccaa7'
related:
  - "[[2026-07-24-index-throughput-plan]]"
  - "[[2026-07-24-index-throughput-adr]]"
---
# `index-throughput` audit: `closeout decision and measurement safety`

## Scope

Audited the two remaining plan rows against the accepted decision, current client and service topology, production memory telemetry, cadence defaults, prior measurements, and the live device state.

## Findings

### grpc-transport | high | transport change exceeds the accepted decision boundary

The managed server derives a non-default gRPC port that the store configuration does not carry, while remote server URLs do not imply any gRPC port. The gRPC exception surface also needs explicit equivalence for donor misses and unrecoverable write failures. Switching transport inside this plan would choose a new configuration and failure-classification contract without an accepted decision.

### cadence-measurement | high | the current device window cannot produce an attributable comparison

The device was saturated by active watcher indexing. Cooperative service pause timed out while five compute tickets remained held; the pause was immediately aborted through the supported resume operation. Running cadence arms in that state would vary contention and cadence together, so no before/after claim could be attributed to the knob.

### telemetry | low | the vault production high-water prerequisite is already satisfied

Vault runs register the shared forward-peak recorder, sample process and allocator readings around the run, retain an immutable snapshot, and project observed peaks to job resilience without inventing a vault support ceiling. Focused tests include mutation evidence for recorder registration, snapshot publication, observe-only behavior, and projection.

## Recommendations

Create a separate ADR for gRPC port ownership, unmanaged-server configuration, and gRPC error classification before changing server transport. Keep the vault and document cadence defaults at one until an alternating, uncontended rebuild A/B records wall time, work time, allocated and reserved peaks, ceiling distance, and OOM events. Use service quiescence only when ticket drain completes; otherwise record the window as unavailable.
