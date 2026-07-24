---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S04'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Give ServiceRegistry one process-global QuiesceGate constructed beside its GPU lock and expose it through an accessor mirroring the existing gpu_lock property so a single gate governs the whole daemon process

## Scope

- `src/vaultspec_rag/service.py`

## Description

- Import the torch-free gate into the registry module at module scope beside the existing graph-cache import (`src/vaultspec_rag/service.py:31`).
- Construct `self._quiesce_gate = QuiesceGate()` in `ServiceRegistry.__init__` directly beside `self._gpu_lock` (`src/vaultspec_rag/service.py:147-151`).
- Expose a read-only `quiesce_gate` property mirroring the existing `gpu_lock` property (`src/vaultspec_rag/service.py:246-249`).

## Outcome

One process-global `QuiesceGate` now lives on the registry beside the one GPU lock, reachable through `ServiceRegistry.quiesce_gate` for job-token injection and search-admission wiring. No torch import was added; the gate module is pure `threading`. Green gate: `ruff check src tools` all checks passed, `ty check` on `service.py` all checks passed, and the touched test modules pass 80/80 (`test_jobs_unit.py`, `test_search_quiesce_admission.py`, `test_job_control_unit.py`).

## Notes

None.
