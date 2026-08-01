---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
body_hash: 'sha256:14ac7143cbfbed7a0a9d4b5d47f4dfaf06b4e1fc7b51d62fe66c71b6e1346dfa'
step_id: 'S28'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Replace server globals with an immutable app-scoped runtime that owns token registry and port, and prove isolated CPU lifecycle behavior

## Scope

- `src/vaultspec_rag/server/_runtime.py`
- `src/vaultspec_rag/server/_main.py`
- `src/vaultspec_rag/server/_state.py`
- `src/vaultspec_rag/server/_auth.py`
- `src/vaultspec_rag/server/_lifespan.py`
- `src/vaultspec_rag/server/_lifecycle.py`
- `src/vaultspec_rag/server/_routes.py`
- `src/vaultspec_rag/server/_routes_registry.py`
- `src/vaultspec_rag/server/_routes_reindex.py`
- `src/vaultspec_rag/server/_routes_search.py`
- `src/vaultspec_rag/server/_watcher.py`
- `src/vaultspec_rag/tests/test_server.py`
- `src/vaultspec_rag/tests/test_http_search_errors.py`
- `src/vaultspec_rag/tests/test_lifespan_machine_lock.py`
- `src/vaultspec_rag/tests/test_machine_discovery.py`
- `src/vaultspec_rag/tests/test_service_discovery_schema.py`
- `src/vaultspec_rag/tests/test_watcher_start_contract.py`

## Description

- Added the frozen `ServerRouteRuntime` authority and made the production app factory install it.
- Moved token, registry, and validated listen/discovery port ownership from server globals to that runtime.
- Bound Uvicorn and discovery publication to the same runtime port, then migrated lifecycle, health, authentication, request routes, and watcher continuations to the runtime registry.
- Replaced test-owned server-global writes with real isolated app runtimes and added authority guards for port validation, foreign-Qdrant pre-model refusal, and watcher ownership.

## Outcome

Accepted for S28's runtime-authority scope. The reviewed commits from `71b446db` through `3d524e3b` leave no production or test assignments to the removed server token, port, or registry globals. The standalone daemon uses the runtime's validated port for both loopback binding and discovery publication; every request-side registry path inspected resolves the runtime authority.

The current checkout supplied CPU-only proof: 198 focused tests passed, including the real foreign-Qdrant refusal before model loading, machine-lock release, discovery identity, authenticated route hosting, and watcher registry ownership. `ruff check src tools` and `ty check` also passed.

## Notes

No service process, managed Qdrant child, model, Torch, CUDA, or GPU test was started. Live GPU/Qdrant integration remains delegated and unverified.

The repository-wide strict basedpyright gate remains a baseline blocker: it reports 98 missing type stubs for `vaultspec_core.*` outside this S28 change. This record does not treat that unrelated baseline as a green gate or as an S28 source defect.
