---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S05'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Thread the registry gate into JobManager and inject it into each RunControlToken built at both dispatch construction sites so every in-flight job shares the one process-global gate, with a unit test asserting a dispatched token observes the shared gate

## Scope

- `src/vaultspec_rag/job_manager.py`

## Description

- Add keyword-only `quiesce_gate: QuiesceGate | None = None` to `JobManager.__init__` and store it (`src/vaultspec_rag/job_manager.py:228-241,261-264`); `None` keeps tokens gateless, preserving every existing constructor call site.
- Pass `gate=self._quiesce_gate` at both dispatch token construction sites, `dispatch` and `dispatch_async` (`src/vaultspec_rag/job_manager.py:451,536`).
- Wire production: `jobs.get_job_manager()` builds the singleton as `JobManager(quiesce_gate=get_registry().quiesce_gate)` so every daemon job token shares the registry's one gate (`src/vaultspec_rag/jobs.py:204`).
- Add `test_dispatched_attempt_token_observes_shared_quiesce_gate` in `src/vaultspec_rag/tests/test_jobs_unit.py`: a real `bind_dispatch` + `dispatch` attempt whose runner checkpoints; pausing the manager-injected gate parks the attempt (bounded negative wait), resuming releases it and the job finishes `succeeded`. CPU-only, no model or GPU.

## Outcome

Every dispatched attempt's `RunControlToken` now carries the one shared registry gate; a single pause quiesces all in-flight jobs at their next unprotected checkpoint, and absorbing cancel/shutdown still latches the gate open. Guard proven both directions in one sequence: mutating both token sites back to gateless `RunControlToken()` turned the test red on the intended assertion ("dispatched attempt did not park at the shared paused gate"); restoring the injection returned it green. Green gate: `ruff check src tools` all checks passed, `ty check` on touched files all checks passed, `test_jobs_unit.py` 57 passed.

## Notes

The registry gate reaches `JobManager` through the lazy singleton in `jobs.get_job_manager()` reading `get_registry().quiesce_gate` (module already imports `get_registry`). A test-only `reset_registry()` builds a fresh gate while an existing `_job_manager` singleton keeps the old one; production never resets the registry mid-life, and tests build managers directly.
