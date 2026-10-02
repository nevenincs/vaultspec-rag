---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-21'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:2dacc8baad34069bbae7e40b0437b58adfdb569305b8c0193029ea158a927dc2'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# `machine-discovery-recovery` ledger

## Changes

- `S01` `T` `src/vaultspec_rag/tests/conftest.py`
- `S02` `T` `src/vaultspec_rag/`
- `S03` `T` `src/vaultspec_rag/tests/test_managed_singleton_isolation.py`
- `S04` `T` `src/vaultspec_rag/_machine_lock.py`
- `S05` `T` `src/vaultspec_rag/tests/integration/test_machine_singleton.py`
- `S05` `T` `src/vaultspec_rag/_machine_lock.py`
- `S06` `T` `src/vaultspec_rag/server/_lifecycle.py`
- `S06` `T` `src/vaultspec_rag/serviceclient/_discovery.py`
- `S07` `T` `src/vaultspec_rag/server/_lifespan.py`
- `S08` `T` `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`
- `S09` `T` `src/vaultspec_rag/tests/integration/test_machine_singleton.py`
- `S10` `T` `src/vaultspec_rag/serviceclient/_discovery.py`
- `S11` `T` `src/vaultspec_rag/serviceclient/__init__.py`
- `S12` `T` `src/vaultspec_rag/tests/test_machine_discovery_resolution.py`
- `S13` `T` `src/vaultspec_rag/serviceclient/_status.py`
- `S14` `T` `src/vaultspec_rag/cli/_status_render.py`
- `S15` `T` `src/vaultspec_rag/cli/_service_doctor.py`
- `S16` `T` `src/vaultspec_rag/tests/test_cli_status.py`
- `S17` `T` `src/vaultspec_rag/serviceclient/_transport.py`
- `S18` `T` `src/vaultspec_rag/tests/test_http_admin_errors.py`
- `S19` `T` `src/vaultspec_rag/serviceclient/_status.py`
- `S20` `T` `src/vaultspec_rag/cli/_service_reconcile.py`
- `S21` `T` `src/vaultspec_rag/cli/__init__.py`
- `S22` `T` `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`
- `S23` `T` `docs/service-discovery.md`
- `S25` `T` `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`
- `S27` `T` `src/vaultspec_rag/cli/_process.py`
- `S28` `T` `src/vaultspec_rag/store.py`
- `S28` `T` `src/vaultspec_rag/_store_locks.py`
- `S28` `T` `src/vaultspec_rag/service.py`
- `S29` `T` `server/_lifespan.py`
- `S29` `T` `server/_main.py`
- `S29` `T` `server/_state.py`
- `S29` `T` `server/__init__.py`
- `S30` `T` `server/_lifecycle.py`
- `S30` `T` `server/_lifespan.py`
- `S30` `T` `tests/test_machine_discovery.py`
- `S31` `T` `server/_lifecycle.py`
- `S31` `T` `server/_lifespan.py`
- `S31` `T` `tests/test_machine_discovery.py`
- `S32` `T` `src/vaultspec_rag/cli/_service_stop.py`
- `S33` `T` `src/vaultspec_rag/tests/integration/conftest.py`
- `S24` `verify:` `Historical focused discovery status doctor transport lifecycle singleton suites and 32 of 32 lifecycle tests at 61ce0d79 recorded in 2026-07-21-machine-discovery-recovery-W04-P10-summary` -> `pass`
- `S26` `A` `.vault/audit/2026-07-23-machine-discovery-recovery-closing-review-audit.md`

## Notes

- `S24` Retrospective summary attribution preserves its explicit statement that earlier Steps lacked their original execution records. This logs the actual retained focused and lifecycle results, not invented earlier per-agent records or a fresh run.
- `S26` Historical operation attributed from Git commit d4ac5aa3d98b1429f0778eaf6f3b4642e0f924fc. The commit explicitly names the S26 closing review; this is its actual audit addition, without inventing earlier absent per-agent execution records.
