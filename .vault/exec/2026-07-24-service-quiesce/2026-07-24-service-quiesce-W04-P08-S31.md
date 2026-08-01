---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:f08d05fcd3442621453f6c08228fe37ef50e4b7e31a542062d521585cc00fa91'
step_id: 'S31'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Bind preflight compatibility and authenticated service-state observation to one ready discovered identity

## Scope

- `src/vaultspec_rag/cli/_service_preflight.py`
- `src/vaultspec_rag/tests/test_service_preflight_cli.py`

## Description

- Commit `d08edec6` classified compatibility from the ready discovery payload before any HTTP observation.
- Bound health to the discovered positive PID, exact port, non-empty token, and exact package version before service-state observation.
- Passed only the verified discovery token through `initial_bearer_token`; did not permit an ambient status-file bearer or unpinned refresh.
- Required finite, non-null `pause_requested_at`, `drain_acknowledged_at`, and `quiesced_at` whenever a snapshot claims it is safe to borrow.
- Added CPU-only real-route and real machine-lock coverage for discovery, identity, authenticated-state, and safe-versus-unsafe refusals.

## Outcome

- `uv run --no-sync pytest src/vaultspec_rag/tests/test_service_preflight_cli.py -q`: 18 passed.
- `ruff format --check`, `ruff check`, `ty check`, scoped BasedPyright, and `git diff --check` passed for the two S31 paths.
- Review accepted the source boundary: every preflight result remains observation-only with `authorized: false` and `lease_required: true`.

## Notes

- No GPU, Qdrant, model, resident daemon, or daemon lifespan was started; route proof used loopback Uvicorn and a real OS-lock child only.
- The test run emitted the existing `.pytest_cache` access-denied warning.
- Production routes always emit complete capacity and quiesce envelopes, and `ServerRouteRuntime` refuses an empty runtime token. Malformed complete-shaped payloads, matching empty health/discovery tokens, and same-install health-version drift therefore remain static fail-closed defenses; no proxy, hook, patch, source mutation, or fabricated success seam was added.
