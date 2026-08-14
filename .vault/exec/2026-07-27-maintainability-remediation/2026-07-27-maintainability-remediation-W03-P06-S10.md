---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:76a3403f73701164b33fab533fbc6d8eb479d228db6708c95631d245288bae31'
step_id: 'S10'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---

# Split pause, cancellation, restart, watcher, and exact-ID control scenarios

## Scope

- `src/vaultspec_rag/tests/integration/_service_job_control_e2e_support.py`
- `src/vaultspec_rag/tests/integration/test_service_job_control_pause_restart.py`
- `src/vaultspec_rag/tests/integration/test_service_job_control_transport_matrix.py`
- `src/vaultspec_rag/tests/integration/test_service_job_control_watcher.py`

## Description

Split the cross-boundary job-control module into the scenario groups it actually holds: pause and cancellation, restart reconciliation, watcher convergence, and the exact-ID transport matrix.

## Outcome

Split into the three scenario groups the reference names, over one shared runtime module:

| Module | Lines | MI |
| --- | --- | --- |
| `_service_job_control_e2e_support.py` | 157 | 68.07 |
| `test_service_job_control_transport_matrix.py` | 215 | 39.29 |
| `test_service_job_control_watcher.py` | 289 | 32.20 |
| `test_service_job_control_pause_restart.py` | 597 | 19.03 |

The single module was 1140 lines at MI 0.00.

Each scenario keeps the helpers only it drives - the watcher's coalescing and replacement exercises, the restart seeding and durable-intent assertions, the operator matrix's own loopback server. What is genuinely shared is the real registry/manager runtime fixture and the released-attempt assertion both scenario groups close on; only those moved to the support module.

The transport matrix turned out to share nothing with the other two: it drives no job manager and uses no embedding model, so its server context moved with it rather than into shared scaffolding.

No assertion text changed, no coverage moved to a fake, and all five tests collect.

## Notes

The shared fixture follows the convention the split route modules already use: an explicit `@pytest.fixture(name=...)`, alias-imported into each consumer with an `__all__` entry. Both consumers were checked to register it under `_e2e_runtime`, the name their signatures request.

The support module names the fixture in its own `__all__`. That is what keeps the unused-function diagnostic quiet - it declares the fixture as the module's surface rather than suppressing the report.

Gates run: ruff check, ruff format, ty, and basedpyright all clean over the four modules; pytest collects all five tests. The tests themselves were not executed - they need the resident service, which this session was asked to leave alone.
