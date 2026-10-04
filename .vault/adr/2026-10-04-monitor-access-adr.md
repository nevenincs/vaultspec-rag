---
tags:
  - '#adr'
  - '#monitor-access'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:2087a7eefc93fd7b32b775ac17c9b0d006f393c09eea83069e247767dc3c8fdf'
related:
  - "[[2026-10-04-monitor-access-reference]]"
  - "[[2026-09-30-monitor-browser-adr]]"
  - "[[2026-09-30-monitor-tooling-adr]]"
  - "[[2026-10-02-monitor-delivery-adr]]"
  - "[[2026-10-02-monitor-lifecycle-adr]]"
---

# `monitor-access` adr: `Confine the credential-free operator monitor to loopback` | (**status:** `accepted`)

## Problem Statement

The remotely reachable monitor treats Tailnet source ranges as operator authorization and lends every admitted peer local backend authority. Evidence: `2026-10-04-monitor-access-reference`.

## Considerations

The user's 2026-10-04 instruction explicitly requests fixing this validated vulnerability and recommends loopback by default. Local credential-free operation can remain behind a loopback boundary. Prior accepted wildcard/Tailnet access commitments must be reconciled.

## Considered options

- Loopback-only listeners and shared request admission: chosen because it closes remote deputy access across every entry point while retaining the local operator workflow.
- Retain remote mode with application credentials or authenticated sessions and separate destructive-operation authorization: deferred because remote mode is unnecessary for this fix and requires a browser credential lifecycle and access policy.
- Rely on Tailnet addresses, Host, Origin or unverified identity headers: rejected because reachability and caller-controlled headers do not establish operator authority.

## Constraints

The monitor has no direct remote mode. Packaged, managed, Vite dev and preview listeners bind 127.0.0.1. Every monitor HTTP request and WebSocket upgrade, including assets and metadata, requires an exact admitted loopback socket peer and a localhost, .localhost, 127.0.0.1 or [::1] authority, with matching Origin when present. Reject Tailnet peers and authorities even under a wildcard development override. Forwarded and Tailscale identity headers grant no authority.

Credential-free reads and existing controls remain available to local operators through the canonical local owner. Bounded forwarding, token redaction, cancellation, strict development ports, managed allocation and shutdown remain unchanged. Remote use requires an authenticated tunnel terminating at loopback; exposing the monitor through an unauthenticated reverse proxy or Tailscale Serve is unsupported. Future direct remote support requires application authentication and separate authorization for destructive actions.

This is a scoped reversal of the wildcard/Tailnet network policy in `2026-09-30-monitor-browser-adr`, `2026-09-30-monitor-tooling-adr` and `2026-10-02-monitor-delivery-adr`, plus the inherited network policy in `2026-10-02-monitor-lifecycle-adr`. Reconcile their current policy wording to this loopback boundary while preserving historical authorization and their other commitments. These broader records remain accepted within the exception.

## Implementation

We will remove Tailnet and remote-host admission from the shared middleware, enforce it before HTTP route dispatch and Vite WebSocket handling, declare the loopback bind in the root manifest, remove remote setup instructions, and verify rejected peer representations and real local workflows. This bounded direct work needs no plan.

## Rationale

The shared middleware is the narrowest authority boundary for credential injection, lifecycle subprocesses and persisted inventory fallbacks. Restricting the listener and admission guard together removes remote reachability and prevents development overrides from restoring remote operator access.

## Consequences

Direct Tailnet and Tailscale Serve access stops working. Local browsers and local proxy aliases retain automatic service access. Authorization basis: the user's explicit security-fix request and supplied loopback remediation. Acceptance records the authorized boundary, not completion of verification. Reconsider direct remote mode only with an authenticated application/session design and distinct destructive authorization.
