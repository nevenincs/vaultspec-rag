---
tags:
  - '#reference'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-27-maintainability-remediation-research]]"
---

# `maintainability-remediation` reference: `radon module ownership`

## Summary

The health report is the authoritative MI measurement: `report_maintainability`
in `tools/health_report.py:209-224` invokes `mi_visit(source, multi=True)` for
each path returned by `_python_files`. Use `uv run python
tools/health_report.py --fast --top N` to verify it, because the Radon CLI's
TOML configuration loading fails as documented at `tools/health_report.py:26-29`.

The production seams should preserve single ownership without a package-root
facade. `cli/_service_jobs.py` has natural service-adapter, display-projection,
and command-registration regions; the current CLI app and service transport are
its external dependencies. `indexer/_run_ledger.py` has immutable identity and
row-conversion models near its top, durable transaction/schema work near its
end, and generation/unit lifecycle methods on `RunLedger` between them. It has
uncommitted work at the time of this audit around `RunLedger` commit-unit
validation, so do not overwrite or rearrange that hunk.

`job_manager.py` exposes `JobExecutionResult`, `JobShutdownResult`,
`JobAttemptContext`, and `JobManager` in `__all__` at lines 53-59. Its
responsibilities divide into data/context (84-232), dispatch/attempt execution
(374-1065), idempotency and creation/query (1066-1279), progress/resources
(1284-1679), desired-state control and terminal handling (1680-2304), durable
recovery (2339-2470), and persistence/snapshot primitives (2488-2955). A
package conversion must migrate consumers directly to the concrete owner
modules; `jobs.py`, `job_dispatch.py`, `watcher.py`, and `server/_lifespan.py`
are known production consumers in the prior reference. The canonical manager
must remain the only owner of durable identity, runtime handles, transitions,
progress, and service-facing snapshots.

Each reported integration module contains scenario orchestration plus reusable
local helpers. Split `test_index_job_control` into stream/pause-resume,
cancellation/write-gate, and collection-loss/publication scenarios;
`test_install` into fresh/idempotent, dry-run topology, failure/uninstall, and
safety/reporting scenarios; `test_jobs_registry` into basic registry, durable
recovery, and route-to-recorded-job flows; `test_service_job_control_e2e` into
pause/cancel/restart, watcher convergence, and exact-ID transport matrix;
`test_service_jobs` into collection contracts, CLI presentation/watch, HTTP
control, and resilience parity; `test_service_lifecycle` into startup/rollback,
live lifecycle, discovery reconciliation, and orphan reaping; and
`test_service_search_diagnostics` into real-service harness, matching rebuild,
HTTP, MCP, and timeout/log diagnostics.

Extract only helpers that run against the same real process, HTTP endpoint, CLI
invocation, persistence store, or watcher as the scenario; do not introduce
fakes or mirror production logic. `test_jobs_registry.py` has uncommitted
helper extraction at the time of this audit and must be treated as another
worker's change. Scenario test functions should remain directly in the named
test modules so test collection and behaviour coverage remain obvious.
