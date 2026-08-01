---
tags:
  - '#audit'
  - '#service-quiesce'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:83ee58f8956f00cd1cc993d425a7b512839969ee1a9b2b1ec84eaea8002ecc8e'
related:
  - "[[2026-07-24-service-quiesce-adr]]"
  - "[[2026-07-24-service-quiesce-plan]]"
---

# `service-quiesce` audit: `S31 identity-binding acceptance`

## Scope

Acceptance review of S31 after commit `d08edec6`. The review covered discovery version authority, health identity corroboration, authenticated service-state bearer pinning, strict safe-quiesce timestamps, and preflight's non-authorizing output.

## Findings

### implementation-complete | low | S31 is implemented and accepted

Preflight now classifies compatibility from the ready discovery payload before any health request. It requires health to confirm the discovered positive PID, exact port, non-empty token, and exact package version. Only then does it request service state with that discovered token as `initial_bearer_token`; it supplies no ambient fallback or unpinned refresh. A claimed safe snapshot requires finite, non-null `pause_requested_at`, `drain_acknowledged_at`, and `quiesced_at`. Every successful observation still reports `authorized: false` and `lease_required: true`.

### real-route-evidence | low | Reachable refusals and bearer pinning passed without GPU authority

The focused preflight suite passed 18 CPU-only tests. It exercised safe and unsafe observations; stale, future, and incomplete discovery; discovery version absence and skew; unreachable and requested-port mismatch; health PID, port, and token mismatch; zero discovery PID; empty discovery token; authenticated service-state failure; and a contended machine-pointer service whose verified bearer succeeds despite a different isolated ambient status token. The routes used no-lifespan loopback Uvicorn and the contention proof used a real OS-lock child.

### static-fail-closed-boundary | low | Canonical-unreachable malformed successful payloads remain defenses, not fabricated tests

Production health always publishes the complete device-capacity mapping and service state always serializes the complete quiesce envelope. The production runtime also rejects an empty service token before it can serve a route, and discovery and health use the same installed package-version function. Consequently partial capacity or state, missing safe timestamps in an otherwise successful canonical route, matching empty health/discovery tokens, and same-install health-version drift cannot be induced without a forbidden proxy, hook, patch, source mutation, or second install. The corresponding parser and identity guards remain static fail-closed defenses; no artificial seam was introduced.

## Validation

- `uv run --no-sync pytest src/vaultspec_rag/tests/test_service_preflight_cli.py -q`: 18 passed; the only warning was the existing `.pytest_cache` access-denied warning.
- Ruff format/check, Ty, scoped BasedPyright, and `git diff --check` passed for the two S31 files.
- No GPU, Qdrant, model, resident daemon, or daemon lifespan was started.

## Release boundary

S31 implementation is complete. Repository-wide strict type health, the delegated self-hosted GPU-live tier, and the historical S07 execution-record trace are separate release or traceability concerns; none keeps this plan step open.

## Recommendations

- Keep the static malformed-payload guards fail closed; do not introduce a proxy, patch, source mutation, or fabricated route solely to exercise canonical-unreachable branches.
- Resolve the external release and traceability concerns in their own records rather than reopening S31.
