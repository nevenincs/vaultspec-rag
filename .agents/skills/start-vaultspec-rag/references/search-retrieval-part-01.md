# Search, ranking and availability: evidence group s1-0010

Read this part when working with: [docs/architecture.md](../../../../docs/architecture.md), [docs/automatic-convergence.md](../../../../docs/automatic-convergence.md), [docs/automation.md](../../../../docs/automation.md), [docs/backends.md](../../../../docs/backends.md), [docs/cli.md](../../../../docs/cli.md).

This is static evidence. Implementation observations, documentation claims, and test expectations remain distinct; no tests were run. An imported dependency uninspected within this evidence group may be covered in another capability reference. All listed full-file ranges are covered; report-local dependency boundaries are not inventory gaps.

[Search, ranking and availability](search-retrieval.md) provides module summaries, connections, and reconciled limitations.

## Capability summary

### Implementation

No implementation modules were in scope. All behaviors below are documentation claims, not independently verified implementation findings.

### Documentation claims

- [docs/architecture.md](../../../../docs/architecture.md) describes the product as retrieval for vaultspec-core projects: it indexes decision records, source code, and extracted documents, and returns ranked locations/passages for an AI assistant or other client to read (lines 3-17). It documents dense and sparse vectors, reranking, optional Typesafe reweighting, GPU-only execution, a resident service, and managed-server versus project-local storage (lines 19-68).
- [docs/automatic-convergence.md](../../../../docs/automatic-convergence.md) specifies the watcher/controller contract. One controller owns a canonical project root and source (`code`, `vault`, or `document`); operator-visible states, reason codes, measurements, backpressure, retry/circuit state, and remediation are documented (lines 29-107, 174-188). Policy keys cover coalescing, cooling, freshness, measurements, scope capacity, retry, and circuit behavior (lines 109-156). Fair admission, generation-scoped batches, persistence, and stale-attempt fencing are stated invariants (lines 158-172).
- [docs/automation.md](../../../../docs/automation.md) documents JSON envelopes and scripting practices: parse `ok`, `error`, exit code, and per-item results; account for command-specific envelope differences, service versus local execution, queued indexing, job polling, and status-based health gates (lines 3-53, 79-106, 138-209). It also lists exit codes and automatic re-indexing behavior (lines 247-279).
- [docs/backends.md](../../../../docs/backends.md) documents the default managed Qdrant server and embedded local-only option, their storage locations and provisioning differences, switching and migration guidance, and status/doctor interpretation (lines 8-40, 52-67, 71-107).
- [docs/cli.md](../../../../docs/cli.md) is a generated command-surface reference. Root commands are `search`, `index`, `clean`, `install`, `uninstall`, and `status` (lines 22-29, 78-259). Server commands cover doctor, inventory, warmup, jobs, logs, preflight, pause/resume, status, reconcile, start/stop, job show/pause/resume/stop/retry/delete, projects list/unload, updates status/start/stop/timing, Qdrant install/status/clean/quarantine, and storage survey/delete/prune/reconcile/migrate/restore (lines 30-69, 260-1018). Preprocess commands cover list/check/approve/revoke/run-one/status (lines 70-76, 1020-1128). Global options and each command's documented arguments/options are at lines 7-20 and under each command entry.

### Test expectations

No test source or test result was in scope. The docs contain examples and operator expectations, but these do not establish that tests exist, pass, or cover the described behaviors.

### Inference

The documented surfaces suggest a service-centered architecture: CLI clients discover or accept a service port, submit work or query state, and use local execution only for explicitly described cases. This is an inference from the docs, not an inspected call graph.

## Interfaces and data flow

- **Documented indexing/search flow:** `.vault/` records, source files, and documents admitted by preprocessing are split into chunks; dense and sparse vectors are stored in a local vector database. A query is encoded both ways, the signals are fused, and a reranker reorders leading candidates. Search returns ranked passages/locations; the caller consumes them (architecture lines 5-17). Optional Typesafe classification can reweight/drop candidates when the service environment has its key (lines 21-25).
- **Documented service/storage flow:** a resident, machine-level service holds models and watches files; project indexes remain separately namespaced. Managed mode supervises Qdrant in shared home-directory storage; local-only mode embeds storage under the project data directory (architecture lines 54-68; backends lines 10-20). Backend switches do not migrate indexes automatically (backends lines 38-42).
- **CLI inputs and outputs:** `search` takes query text and supports source/domain and result filters, service port, fallback, JSON, timeout, and freshness options (CLI lines 78-122). `index` selects domains and rebuild/dry-run or explicit GPU borrowing (lines 124-151). The remaining root/server/storage/preprocess operations and options are enumerated at lines 153-1128. The automation guide says JSON generally returns `{ok, command, data}` on success or `{ok, command, error, message}` on failure, with exceptions and optional fields described there (automation lines 36-53).
- **Jobs and automatic updates:** indexing through the service is documented as returning on job admission; callers inspect job state/progress and later index counts (automation lines 182-209). Update controllers are exposed through CLI, `GET /watcher`, job controller objects, `GET /service-state`, and a Python admin client (automatic-convergence lines 10-27). The docs define controller identity, filters, timestamps, policy and state information (lines 29-59).
- **Backend administration:** documented interfaces include Qdrant provisioning/status/cleanup/quarantine and storage survey/delete/prune/reconcile/migrate/restore. These are CLI contracts only in this slice (CLI lines 802-1018). Preprocessing commands expose resolved rules, validation, approval state, one-file execution, and status (CLI lines 1020-1128).

## Boundaries and dependencies

- The docs place model loading, indexing, file watching, admission/retry, and publication in the resident service; clients use CLI or MCP for retrieval (architecture lines 5-9, 54-58; automatic-convergence lines 3-8). Exact code ownership and call paths were not inspected.
- Document preprocessing is described as a source of indexed documents, with its own CLI approval/configuration surface. The referenced preprocessing-hook guide was not read (architecture lines 9, 66; CLI lines 1020-1128).
- Managed storage depends on the pinned Qdrant executable and service supervision; operator-supplied binaries require a declared path and digest. Local-only storage avoids the server binary, but still needs models/GPU runtime (backends lines 20-36, 52-67). These are documentation claims; provisioning code was not inspected.
- Linked material including [docs/mcp.md](../../../../docs/mcp.md), [docs/indexing.md](../../../../docs/indexing.md), [docs/preprocessing-hooks.md](../../../../docs/preprocessing-hooks.md), [docs/query-craft.md](../../../../docs/query-craft.md), [docs/configuration.md](../../../../docs/configuration.md), [docs/glossary.md](../../../../docs/glossary.md), [docs/installation.md](../../../../docs/installation.md), [docs/service-mode.md](../../../../docs/service-mode.md), [docs/service-discovery.md](../../../../docs/service-discovery.md), [docs/storage-maintenance.md](../../../../docs/storage-maintenance.md), [docs/provisioning.md](../../../../docs/provisioning.md), [docs/getting-started.md](../../../../docs/getting-started.md), [docs/search-and-index.md](../../../../docs/search-and-index.md), and [README.md](../../../../README.md) was not read. Any details delegated to those documents remain outside this slice.

## Evidence

| Claim                                                                                             | Project-relative file:line-range                                                                                                              | Kind                |
| ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- |
| Retrieval indexes vault, code, and preprocessed documents and returns ranked passages to a client | [docs/architecture.md:3-17](../../../../docs/architecture.md#L3)                                                                              | documentation claim |
| GPU-only model execution and two documented storage arrangements                                  | [docs/architecture.md:27-68](../../../../docs/architecture.md#L27); [docs/backends.md:8-20](../../../../docs/backends.md#L8)                  | documentation claim |
| Automatic convergence exposes root/source controllers, states, stable reasons, and bounded policy | [docs/automatic-convergence.md:10-59,61-156](../../../../docs/automatic-convergence.md#L10)                                                   | documentation claim |
| Fair admission and generation-scoped completion are stated convergence invariants                 | [docs/automatic-convergence.md:158-172](../../../../docs/automatic-convergence.md#L158)                                                       | documentation claim |
| Automation consumers should distinguish admission from completed indexing and inspect jobs/status | [docs/automation.md:182-245](../../../../docs/automation.md#L182)                                                                             | documentation claim |
| JSON envelope and exit-code guidance for scripts                                                  | [docs/automation.md:36-53,138-180,247-269](../../../../docs/automation.md#L36)                                                                | documentation claim |
| CLI command inventory and arguments/options                                                       | [docs/cli.md:7-76,78-1128](../../../../docs/cli.md#L7)                                                                                        | documentation claim |
| No implementation or test result can be established from this assigned slice                      | all assigned documentation ranges                                                                                                             | scope limitation    |
| Service-centered call flow inferred from documented client/service boundaries                     | [docs/architecture.md:5-9,54-58](../../../../docs/architecture.md#L5); [docs/automation.md:26-34,182-209](../../../../docs/automation.md#L26) | inference           |

## Uncertainty and follow-up

- The report maps documented capabilities only. To validate behavior, inspect the corresponding implementation and tests for CLI dispatch, service APIs, indexing/search, watcher/controller persistence, backend lifecycle, and preprocessing. Their exact files and symbols cannot be identified from the assigned docs alone, so no follow-up paths are asserted here.
- No contradiction was resolved because implementation and linked documents were outside scope.
