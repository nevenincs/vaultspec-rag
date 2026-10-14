# Resident service, discovery and transport: evidence group s1-0070

Read this part when working with: [src/vaultspec_rag/server/\_routes.py](../../../../src/vaultspec_rag/server/_routes.py), [src/vaultspec_rag/server/\_routes_jobs.py](../../../../src/vaultspec_rag/server/_routes_jobs.py), [src/vaultspec_rag/server/\_routes_operator.py](../../../../src/vaultspec_rag/server/_routes_operator.py), [src/vaultspec_rag/server/\_routes_quiesce.py](../../../../src/vaultspec_rag/server/_routes_quiesce.py), [src/vaultspec_rag/server/\_routes_registry.py](../../../../src/vaultspec_rag/server/_routes_registry.py).

This is static evidence. Implementation observations, documentation claims, and test expectations remain distinct; no tests were run. An imported dependency uninspected within this evidence group may be covered in another capability reference. All listed full-file ranges are covered; report-local dependency boundaries are not inventory gaps.

[Resident service, discovery and transport](service-lifecycle.md) provides module summaries, connections, and reconciled limitations.

## Capability summary

- [src/vaultspec_rag/server/\_routes.py](../../../../src/vaultspec_rag/server/_routes.py): route-table composition and shared job request/admission/response helpers; local handlers for job listing/detail/control, search activity, logs, metrics, readiness/service state, code-file and vault-document reads, and quality probing. It imports search, reindex/audit/clean, storage-survey, runtime-observation, repository, watcher, project and quiesce handlers from sibling modules.
- [src/vaultspec_rag/server/\_routes_jobs.py](../../../../src/vaultspec_rag/server/_routes_jobs.py): job-record normalization, filtering, sorting, summaries and liveness/work projection for the /jobs view. It also reads job telemetry/evidence and watcher-controller snapshots while enriching records. It defines no HTTP routes.
- [src/vaultspec_rag/server/\_routes_operator.py](../../../../src/vaultspec_rag/server/_routes_operator.py): bounded repository inventory from manifest, resident-registry, watcher and Git worktree facts; repository listing and service-owned enrollment with optional watcher setup.
- [src/vaultspec_rag/server/\_routes_quiesce.py](../../../../src/vaultspec_rag/server/_routes_quiesce.py): shared pause/resume handling, including borrower capability parsing and validation, ownership and GPU-loan coordination, transition calls, timeout handling and a common response envelope.
- [src/vaultspec_rag/server/\_routes_registry.py](../../../../src/vaultspec_rag/server/_routes_registry.py): resident-project listing/eviction and per-root watcher state/start/stop/reconfigure handlers.

## Interfaces and data flow

- [src/vaultspec_rag/server/\_routes.py:1107-1142](../../../../src/vaultspec_rag/server/_routes.py#L1107) assembles Starlette routes. Local handlers are GET /jobs; GET and DELETE /jobs/{job_id}; PUT /jobs/{job_id}/desired-state; POST /jobs/{job_id}/retry; GET /search-activity, /logs, /logs/json, /metrics, /readiness and /service-state; POST /code-file, /vault-document and /quality. Other route-table entries are imported from siblings (lines 64-90, 1121-1140).
- Job request helpers parse JSON objects, validate operation/source/mode/authority/project root and initiator, resolve code/document admission preflight, shape preflight data, and activate an accepted index job (lines 170-392, 465-488). Response helpers map typed outcome codes to HTTP statuses and can emit a Location header (lines 395-462). The actual reindex handler that calls the admission helper is in an uninspected module.
- GET /jobs requires a route token, joins canonical job-manager snapshots with legacy-only activity records, normalizes filters, enriches and sorts matches, then applies offset/limit. JSON includes pagination/filter data, job summary, quiesce, GPU and machine pressure, and device-load snapshots (lines 510-624). Detail resolves one ID; desired-state PUT delegates to the manager with optional expected revision; retry revalidates and activates a parent retry; DELETE delegates to job deletion (lines 662-797).
- Search activity returns a ledger snapshot with state/type/root/request/time/query/outcome/page/sort filters (lines 626-659). Log handlers share a bounded query path and return grouped plain text or JSON; invalid sources produce 400 (lines 800-859). Metrics renders Prometheus text; service-state/readiness/quality call service APIs, generally through a worker thread (lines 861-925, 1028-1043).
- The code-file path is resolved beneath a project root, checked for containment and policy admission before opening, then read with a size cap. Vault-document looks up one ID under a registry lease and maps registry/store-lock errors to payloads (lines 927-1025, 1056-1104).
- Repository listing joins persisted manifest entries, live registry slots, watcher roots and Git worktree relationships under limits. Enrollment validates a directory and watch boolean, persists a root record and optionally schedules a watcher (operator lines 135-208, 211-281).
- Project/watcher handlers use the request runtime registry and shared watcher state: list/evict projects; expose filtered controller snapshots/config; start, stop or reconfigure a watcher for a canonical root (registry lines 41-89, 91-152, 155-235).
- Pause/resume parse an optional single-field borrower capability, validate its lease, invoke registry quiesce/resume and return a shared envelope. A successful borrower pause binds ownership and records a GPU loan; successful borrower resume clears the capability (quiesce lines 46-96, 212-382). The routes are registered at /pause and /resume in [src/vaultspec_rag/server/\_routes.py:1135-1136](../../../../src/vaultspec_rag/server/_routes.py#L1135).
- State is reached through imported services: job manager/activity registry, request runtime/project registry, watcher state/controllers, search-activity ledger, storage manifest, Git metadata, store lease, quiesce controller, logs and job telemetry/evidence. Those implementations were not inspected.

## Boundaries and dependencies

- [src/vaultspec_rag/server/\_routes.py](../../../../src/vaultspec_rag/server/_routes.py) imports \_routes_jobs helpers and sibling handler functions. It is the route-table composition point in this slice; app construction, binding and middleware are uninspected.
- [src/vaultspec_rag/server/\_routes_jobs.py](../../../../src/vaultspec_rag/server/_routes_jobs.py) imports job value/progress/evidence readers and job models. It also reads watcher-controller snapshots and activity-registry records; dependency internals are uninspected.
- [src/vaultspec_rag/server/\_routes_operator.py](../../../../src/vaultspec_rag/server/_routes_operator.py) reads manifest, registry/watcher snapshots and Git metadata. Its docstring says inventory avoids opening stores; the shown implementation uses snapshots and manifest/Git reads, while imported helper internals remain uninspected.
- [src/vaultspec_rag/server/\_routes_quiesce.py](../../../../src/vaultspec_rag/server/_routes_quiesce.py) relies on the service registry and quiesce controller for lifecycle transitions, borrower leases and GPU coordination. Their internals are uninspected.
- [src/vaultspec_rag/server/\_routes_registry.py](../../../../src/vaultspec_rag/server/_routes_registry.py) delegates project eviction, root canonicalization, config validation, watcher snapshots and watcher lifecycle to imported components. Their internals are uninspected.
- No tests or external documentation were inspected. Source docstrings are listed as documentation claims below, not independently verified behavior. A test source would not constitute a passing test.

## Evidence

- Route table enumerates path/method pairs and composes sibling handlers | [src/vaultspec_rag/server/\_routes.py:64-90,1107-1142](../../../../src/vaultspec_rag/server/_routes.py#L64) | implementation
- Module describes loopback binding, token gate, /health placement and sibling responsibilities | [src/vaultspec_rag/server/\_routes.py:11-29](../../../../src/vaultspec_rag/server/_routes.py#L11) | documentation claim; app/auth wiring uninspected
- Job payload and index admission validate source/mode/authority/root and code/document preflight | [src/vaultspec_rag/server/\_routes.py:170-392](../../../../src/vaultspec_rag/server/_routes.py#L170) | implementation
- Job listing joins snapshots, filters, sorts, pages, and emits summary/pressure blocks | [src/vaultspec_rag/server/\_routes.py:510-624](../../../../src/vaultspec_rag/server/_routes.py#L510) | implementation
- Search activity, logs, metrics, readiness/state, code-file, vault-document and quality handlers | [src/vaultspec_rag/server/\_routes.py:626-659,800-925,927-1043,1046-1104](../../../../src/vaultspec_rag/server/_routes.py#L626) | implementation
- Job helpers normalize lifecycle/source/trigger and compute liveness, degradation, rate/estimate, and resilience projections | [src/vaultspec_rag/server/\_routes_jobs.py:89-280,287-524,545-768](../../../../src/vaultspec_rag/server/_routes_jobs.py#L89) | implementation
- Job helper module states its scope and describes its sole non-pure step | [src/vaultspec_rag/server/\_routes_jobs.py:1-12](../../../../src/vaultspec_rag/server/_routes_jobs.py#L1) | documentation claim
- Job predicates, summary, machine pressure and sorting | [src/vaultspec_rag/server/\_routes_jobs.py:771-855,860-1034,1037-1102](../../../../src/vaultspec_rag/server/_routes_jobs.py#L771) | implementation
- Repository inventory joins bounded manifest/registry/watcher/Git facts; enrollment persists and optionally starts watching | [src/vaultspec_rag/server/\_routes_operator.py:32-85,135-179,182-281](../../../../src/vaultspec_rag/server/_routes_operator.py#L32) | implementation
- Operator module describes inventory as not opening stores | [src/vaultspec_rag/server/\_routes_operator.py:135-139](../../../../src/vaultspec_rag/server/_routes_operator.py#L135) | documentation claim
- Quiesce envelope, borrower validation/ownership and transition flow | [src/vaultspec_rag/server/\_routes_quiesce.py:46-96,212-382](../../../../src/vaultspec_rag/server/_routes_quiesce.py#L46) | implementation
- Quiesce module states pause/resume are the daemon-wide admission-changing routes | [src/vaultspec_rag/server/\_routes_quiesce.py:1-12](../../../../src/vaultspec_rag/server/_routes_quiesce.py#L1) | documentation claim
- Project list/eviction and watcher state/start/stop/reconfigure | [src/vaultspec_rag/server/\_routes_registry.py:41-89,91-152,155-235](../../../../src/vaultspec_rag/server/_routes_registry.py#L41) | implementation
- No test-source expectations gathered; no tests read or run | assigned slice only | test expectation: none available
- App wiring, external handler behavior and imported dependency internals are not inferred from imports | assigned slice boundary | inference/limitation

## Uncertainty and follow-up

- To verify app wiring and the /health claim, read [src/vaultspec_rag/server/\_main.py](../../../../src/vaultspec_rag/server/_main.py) and the app-construction symbol named by [src/vaultspec_rag/server/\_routes.py](../../../../src/vaultspec_rag/server/_routes.py)'s module docstring.
- To verify callers of canonical admission helpers and how jobs enter execution, read [src/vaultspec_rag/server/\_routes_reindex.py](../../../../src/vaultspec_rag/server/_routes_reindex.py) (reindex handler) and the corresponding jobs activation entry points.
- For imported route-group behavior, read [src/vaultspec_rag/server/\_routes_search.py](../../../../src/vaultspec_rag/server/_routes_search.py), \_routes_storage.py and \_routes_runtime.py; for registry/watcher runtime behavior, read \_runtime.py, \_watcher.py and relevant ServiceRegistry methods.
- No contradictions were observed within the assigned implementation. Source documentation claims above were not checked against external docs or tests.
