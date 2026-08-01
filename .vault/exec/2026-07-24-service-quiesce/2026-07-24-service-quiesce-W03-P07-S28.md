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

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-quiesce with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S28 and 2026-07-24-service-quiesce-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Replace module-global route token, service listen/discovery port, and registry assignment with one immutable app-scoped production route runtime and ## Scope

- `make the standalone daemon bind Uvicorn and publish discovery from that runtime's one validated port`
- `migrate daemon authentication`
- `lifecycle publication`
- `every route-side registry consumer`
- `and every test caller of the removed globals to that runtime`
- `and prove CLI`
- `MCP and TUI adapters preserve one controller vocabulary through authenticated real routes plus CPU-only pre-model lifecycle refusal without starting the service process`
- `managed Qdrant`
- `models`
- `Torch or CUDA`
- `src/vaultspec_rag/server/_runtime.py`
- `src/vaultspec_rag/server/_main.py`
- `src/vaultspec_rag/server/_state.py`
- `src/vaultspec_rag/server/__init__.py`
- `src/vaultspec_rag/server/_auth.py`
- `src/vaultspec_rag/server/_lifespan.py`
- `src/vaultspec_rag/server/_lifecycle.py`
- `src/vaultspec_rag/server/_routes.py`
- `src/vaultspec_rag/server/_routes_registry.py`
- `src/vaultspec_rag/server/_routes_search.py`
- `src/vaultspec_rag/server/_utils.py`
- `src/vaultspec_rag/tests/integration/_service_jobs_route_helpers.py`
- `src/vaultspec_rag/tests/integration/_service_jobs_support.py`
- `src/vaultspec_rag/tests/integration/_service_lifecycle_helpers.py`
- `src/vaultspec_rag/tests/integration/test_index_support_admission.py`
- `src/vaultspec_rag/tests/integration/test_server_doctor_route.py`
- `src/vaultspec_rag/tests/integration/test_service_job_control.py`
- `src/vaultspec_rag/tests/integration/test_service_job_control_e2e.py`
- `src/vaultspec_rag/tests/integration/test_service_jobs_routes_mutations.py`
- `src/vaultspec_rag/tests/integration/test_service_lifecycle_startup.py`
- `src/vaultspec_rag/tests/integration/test_service_logs.py`
- `src/vaultspec_rag/tests/integration/test_service_metrics.py`
- `src/vaultspec_rag/tests/integration/test_service_source_type_contract.py`
- `src/vaultspec_rag/tests/test_cli_status.py`
- `src/vaultspec_rag/tests/test_http_search_errors.py`
- `src/vaultspec_rag/tests/test_jobs_degradation.py`
- `src/vaultspec_rag/tests/test_jobs_device_load.py`
- `src/vaultspec_rag/tests/test_jobs_quiesce_projection.py`
- `src/vaultspec_rag/tests/test_lifespan_machine_lock.py`
- `src/vaultspec_rag/tests/test_machine_discovery.py`
- `src/vaultspec_rag/tests/test_machine_pressure.py`
- `src/vaultspec_rag/tests/test_mcp_conformance_surface.py`
- `src/vaultspec_rag/tests/test_quiesce_state_projections.py`
- `src/vaultspec_rag/tests/test_search_quiesce_admission.py`
- `src/vaultspec_rag/tests/test_server.py`
- `src/vaultspec_rag/tests/test_service_discovery_schema.py`
- `src/vaultspec_rag/tests/test_service_quiesce_adapters.py`
- `src/vaultspec_rag/tests/test_service_quiesce_cli.py`
- `src/vaultspec_rag/tests/test_service_quiesce_routes.py`
- `src/vaultspec_rag/tests/test_watcher_start_contract.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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
