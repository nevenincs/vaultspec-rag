---
tags:
  - '#audit'
  - '#service-quiesce'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
related:
  - "[[2026-07-24-service-quiesce-adr]]"
  - "[[2026-07-24-service-quiesce-plan]]"
---
# `service-quiesce` audit: `S31 identity-binding directive`

## Scope

Read-only review of S31 preflight before source repair. The review covered the relationship between machine discovery, health, authenticated service-state, strict quiesce timestamps, device capacity, and preflight's non-authorizing output.

## Findings

### discovery-version-authority | high | Compatibility was classified from ungated health instead of discovery

Preflight previously classified compatibility from the health response. Discovery is the address-and-identity authority, so its published `package_version` must supply the compatibility verdict before any health or service-state request. Missing, blank, or non-string discovery version must refuse as `service_version_unreported`; a differing discovered version must refuse as `service_version_mismatch`.

### ambient-service-state-bearer | high | Authenticated observation was not pinned to verified discovery identity

The service-state call previously used the transport's ambient status-file bearer. The repaired call must use the already verified discovery token as `initial_bearer_token`, with no ambient fallback and no unpinned refresh. Health must confirm exact discovered PID, port, token, and package version before that request. A missing or different field, including health version disagreement, must refuse as `service_identity_mismatch`; an authenticated-state 401, failed route, or non-object result must refuse as `service_state_unavailable`.

### safe-quiesce-timestamps | high | Complete-shaped state could claim safety without transition evidence

The strict quiesce parser allowed null transition timestamps and the safe predicate did not require them. A safe preflight success must require finite non-null `pause_requested_at`, `drain_acknowledged_at`, and `quiesced_at`; missing, boolean, NaN, infinite, or otherwise invalid values refuse as `service_state_incomplete`. `warming_started_at` remains optional because safe quiescence does not pass through warming.

### refusal-matrix | medium | Every observation failure needs one stable non-authorizing outcome

Non-ready discovery or absent port is `service_discovery_unavailable`; an unusable heartbeat window is `service_discovery_incomplete`; a future heartbeat is `service_discovery_unknown`; a stale heartbeat is `service_discovery_stale`; and an explicit port conflict is `service_port_mismatch`. Unreachable health is `service_unreachable`; missing, partial, or invalid capacity is `device_capacity_unavailable`; partial quiesce is `service_state_incomplete`; and a valid but unsafe snapshot is `service_not_safe_to_borrow_gpu`. Every error and success retains `authorized: false` and `lease_required: true`.

### required-real-route-proof | high | Existing tests do not exercise reachable identity and authentication refusals

S31 must add CPU-only real production-route coverage for unknown and incomplete discovery, discovery version unreported and mismatch, unreachable health, health identity and version mismatch, authenticated service-state refusal, and successful safe versus unsafe observation. It must also prove bearer pinning with a contended machine-pointer identity and a deliberately different isolated ambient status token: the old ambient route would receive 401, while the explicit discovered bearer succeeds. The proof must not use mocks, patches, source mutation, a local GPU, Qdrant child, model, or daemon lifespan.

The canonical production health route always emits the complete device-capacity mapping and the production service-state route always serializes the complete controller envelope. Partial capacity, partial quiesce, and missing-safe-timestamp mappings therefore cannot be induced through a real production route without a forbidden proxy, hook, patch, or source mutation. `_strict_capacity` and `_strict_quiesce`, including the finite safe-timestamp guard, remain static unexercised defense-in-depth for older services, proxies, and future wire drift; no fabricated malformed-success test seam is permitted.

## Recommendations

- Implement S31 only to the accepted ADR refinement and revised plan row.
- Preserve the existing service-client transport seam; pass the discovered bearer only through its typed `initial_bearer_token` option and never raw headers or a parallel client.
- Keep preflight observation-only. No refusal recovery may start a service, read a local GPU, authorize a borrower, or fall back to local compute.
