---
tags:
  - '#adr'
  - '#loopback-http-security'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:2cb1eb13f5c9200f8089edb5cf46ff2c01abf4399b7d3a15f126e4463bd20438'
related:
  - "[[2026-07-22-service-health-client-hardening-research]]"
  - "[[2026-05-31-service-token-identity-adr]]"
  - "[[2026-06-01-service-observability-adr]]"
  - "[[2026-09-30-monitor-browser-adr]]"
---

# `loopback-http-security` adr: `Protect loopback HTTP credentials from browser origins` | (**status:** `accepted`)

## Problem Statement

A browser hostname can rebind to loopback while retaining its attacker-controlled HTTP authority. The daemon previously accepted that authority and disclosed its REST credential from unauthenticated health. Loopback binding alone does not enforce the browser boundary.

## Considerations

The existing service-health-client-hardening research establishes health-based credential recovery and the credential-bearing transport. The reported finding and the current request path confirm that host and origin validation are absent. Existing clients need local discovery, health identity checks and bounded recovery; the browser monitor keeps credentials on its server.

## Considered options

- Keep public credential recovery and validate only Host: rejected because one missed ingress check would still disclose a usable credential.
- Remove all health identity responses and migrate every lifecycle consumer: unnecessary for the reported boundary; a caller already holding the correct credential can retain its identity response.
- Choose secret-free unauthenticated health, protected file discovery and shared HTTP authority validation together.

## Constraints

Authorization: the user's 2026-10-04 request explicitly authorizes removing service_token from unauthenticated health, protected same-user discovery and application-level Host and Origin enforcement. This ruling refines service-token-identity and service-observability within their HTTP credential scope and replaces monitor-browser's health-based credential recovery. Their remaining ownership, identity and adapter contracts continue to apply.

Unauthenticated health must omit the credential. Authenticated health may echo only a credential the caller already presented correctly, preserving local identity checks without allowing credential bootstrap. Credentials are obtained and refreshed exclusively from same-user protected discovery for the addressed port, including the machine pointer. Protect temporary publications before writing secret bytes. Reject arbitrary DNS names, malformed or multiple Host/Origin headers and nonmatching browser origins before routing, even when a valid token is presented. Permit literal loopback addresses and localhost; DNS resolution and forwarded headers cannot add authority. Maintain loopback binding and route token checks.

## Implementation

Install one HTTP ingress middleware in the production app factory. Keep health ungated but serialize its token only after successful existing token authentication. Select discovery credentials by target port for Python health probes, ordinary authenticated calls and monitor recovery. Publish both discovery copies with private file permissions, including protected Windows DACLs, through the existing atomic writer.

## Rationale

The shared app factory covers the entire route table and rejects browser requests before route side effects. Independent file discovery removes HTTP credential bootstrap. An authenticated health identity response preserves callers without granting a credential to a party that lacks it.

## Consequences

Explicit-port operations require access to the matching local or machine discovery file. A missing or stale credential results in an authentication refusal instead of learning it from the network. Unauthenticated health remains available at approved loopback authorities. Monitor users retain automatic connection through the existing server-side bridge.
