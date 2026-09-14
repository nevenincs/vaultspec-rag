---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:62dd11c825b43005b541a458a4bfc52672ecc0a8e1d2f88be0d0d2b8d8f4f633'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# `service-quiesce` ledger

## Changes

- `S01` `T` `src/vaultspec_rag/job_control.py`
- `S02` `T` `src/vaultspec_rag/job_control.py`
- `S03` `T` `src/vaultspec_rag/tests/test_job_control_unit.py`
- `S04` `T` `src/vaultspec_rag/service.py`
- `S05` `T` `src/vaultspec_rag/job_manager.py`
- `S06` `T` `src/vaultspec_rag/search/_searcher.py`
- `S08` `T` `src/vaultspec_rag/cli/_service_quiesce.py`
- `S09` `T` `src/vaultspec_rag/tests/test_service_quiesce_cli.py`
- `S10` `T` `src/vaultspec_rag/service_quiesce.py`
- `S11` `T`
- `S12` `T`
- `S13` `T`
- `S14` `T`
- `S15` `T`
- `S16` `T`
- `S17` `T`
- `S18` `T`
- `S19` `T` `src/vaultspec_rag/server/_routes.py`
- `S20` `T` `src/vaultspec_rag/server/_lifespan.py`
- `S20` `T` `src/vaultspec_rag/server/_routes.py`
- `S21` `T` `src/vaultspec_rag/api.py`
- `S22` `T` `src/vaultspec_rag/tests/test_service_quiesce_routes.py`
- `S23` `T` `src/vaultspec_rag/serviceclient/_transport.py`
- `S24` `T` `src/vaultspec_rag/cli/_service_quiesce.py`
- `S25` `T` `src/vaultspec_rag/cli/_index.py`
- `S25` `T` `src/vaultspec_rag/cli/_render.py`
- `S25` `T` `src/vaultspec_rag/tests/test_cli_index_fallback_refusal.py`
- `S26` `T` `src/vaultspec_rag/mcp/_tools.py`
- `S27` `T` `src/vaultspec_rag/cli/_jobs_tui.py`
- `S28` `T` `src/vaultspec_rag/server/_runtime.py`
- `S28` `T` `src/vaultspec_rag/server/_main.py`
- `S28` `T` `src/vaultspec_rag/server/_state.py`
- `S28` `T` `src/vaultspec_rag/server/_auth.py`
- `S28` `T` `src/vaultspec_rag/server/_lifespan.py`
- `S28` `T` `src/vaultspec_rag/server/_lifecycle.py`
- `S28` `T` `src/vaultspec_rag/server/_routes.py`
- `S28` `T` `src/vaultspec_rag/server/_routes_registry.py`
- `S28` `T` `src/vaultspec_rag/server/_routes_reindex.py`
- `S28` `T` `src/vaultspec_rag/server/_routes_search.py`
- `S28` `T` `src/vaultspec_rag/server/_watcher.py`
- `S28` `T` `src/vaultspec_rag/tests/test_server.py`
- `S28` `T` `src/vaultspec_rag/tests/test_http_search_errors.py`
- `S28` `T` `src/vaultspec_rag/tests/test_lifespan_machine_lock.py`
- `S28` `T` `src/vaultspec_rag/tests/test_machine_discovery.py`
- `S28` `T` `src/vaultspec_rag/tests/test_service_discovery_schema.py`
- `S28` `T` `src/vaultspec_rag/tests/test_watcher_start_contract.py`
- `S29` `T` `src/vaultspec_rag/gpu_borrow_lease.py`
- `S29` `T` `src/vaultspec_rag/_test_isolation.py`
- `S29` `T` `src/vaultspec_rag/_anchor_claim.py`
- `S29` `T` `src/vaultspec_rag/_machine_lock.py`
- `S29` `T` `src/vaultspec_rag/tests/test_gpu_borrow_lease.py`
- `S29` `T` `src/vaultspec_rag/tests/test_existing_anchor_observation.py`
- `S30` `T` `src/vaultspec_rag/cli/_gpu_lease.py`
- `S30` `T` `src/vaultspec_rag/serviceclient/_discovery.py`
- `S30` `T` `src/vaultspec_rag/serviceclient/_transport.py`
- `S30` `T` `src/vaultspec_rag/tests/test_gpu_borrow_captured_target.py`
- `S30` `T` `src/vaultspec_rag/tests/test_gpu_borrow_cli.py`
- `S31` `T` `src/vaultspec_rag/cli/_service_preflight.py`
- `S31` `T` `src/vaultspec_rag/tests/test_service_preflight_cli.py`
- `S32` `T` `conftest.py`
- `S32` `T` `src/vaultspec_rag/tests/test_gpu_session_lock.py`
- `S33` `T` `.github/workflows/ci.yml`
- `S33` `T` `justfile`
