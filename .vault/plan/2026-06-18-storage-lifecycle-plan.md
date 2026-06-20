---
tags:
  - '#plan'
  - '#storage-lifecycle'
date: '2026-06-18'
tier: L3
related:
  - '[[2026-06-18-storage-lifecycle-adr]]'
  - '[[2026-06-18-storage-lifecycle-research]]'
---

# `storage-lifecycle` plan

Deliver a server-authoritative storage lifecycle surface - survey, prune, delete, and migrate - that lets operators see and safely reclaim per-worktree RAG index storage and evicts deleted files in server mode, closing issues 192 and 193 without a full rebuild and without ever destroying out-of-scope data.

## Wave `W01` - deleted-file eviction fix and server-mode coverage

Close issue 192 first to de-risk the feature: reproduce the server-mode deleted-file leak with a real-backend test, apply the minimal durability fix, and leave behind the server-mode test scaffolding the destructive verbs reuse. No downstream Wave depends on this beyond inheriting its test fixtures. Authorized by the storage-lifecycle ADR and research.

### Phase `W01.P01` - reproduce and fix server-mode deleted-file eviction

Add real server-mode regression coverage that reproduces the issue-192 leak, then apply the minimal durability fix the test demands.

- [ ] `W01.P01.S01` - Add a server-mode integration test that indexes two code files, deletes one, runs a scoped incremental index, and asserts the deleted file chunks are gone from the store; `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`.
- [ ] `W01.P01.S02` - Extend the server-mode test to assert a real hybrid search no longer returns the deleted file; `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`.
- [ ] `W01.P01.S03` - Add a vault-side twin test deleting a vault document, running the scoped incremental index, and asserting document eviction and search absence in server mode; `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`.
- [ ] `W01.P01.S04` - Diagnose the reproduced server-mode leak and apply the minimal durability fix to the delete path; `src/vaultspec_rag/store.py`.
- [ ] `W01.P01.S05` - Add an explicit watcher delete-carry-forward assertion covering the pending-set batching path; `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`.

## Wave `W02` - prefix-to-root manifest and survey foundation

Introduce the persisted prefix-to-root manifest that makes namespace attribution safe, the service-domain storage core, and the read-only survey surface. This Wave is the foundation every destructive verb depends on; it must land before Waves 3 to 5. Authorized by the storage-lifecycle ADR.

### Phase `W02.P02` - persisted prefix-to-root manifest

Introduce a durable manifest mapping each collection prefix to its resolved root so namespaces can be attributed and classified safely.

- [x] `W02.P02.S06` - Define the prefix-to-root manifest schema and its on-disk location under the managed service directory; `src/vaultspec_rag/registry.py`.
- [x] `W02.P02.S07` - Write and update the manifest entry whenever a root is indexed; `src/vaultspec_rag/api.py`.
- [x] `W02.P02.S08` - Add a manifest read and reverse-map helper resolving a collection prefix to its root; `src/vaultspec_rag/registry.py`.
- [ ] `W02.P02.S09` - Reconcile the manifest on service start and on root rename or move; `src/vaultspec_rag/server/_lifespan.py`.
- [ ] `W02.P02.S10` - Add unit and real-backend tests for manifest write, read, and reverse-map; `src/vaultspec_rag/tests/integration/test_storage_manifest.py`.

### Phase `W02.P03` - service-domain survey surface

Expose a bounded, filterable read-only survey of stored namespaces over a service endpoint, the CLI, and a read-only MCP tool.

- [x] `W02.P03.S11` - Implement a service-domain survey function that enumerates namespaces, joins the manifest, and classifies live, orphaned, and unknown; `src/vaultspec_rag/service.py`.
- [x] `W02.P03.S12` - Compute daemon-side byte footprint for each namespace from the server storage tree; `src/vaultspec_rag/service.py`.
- [ ] `W02.P03.S13` - Add a gated GET storage route, bounded and filterable, and register it in the route table; `src/vaultspec_rag/server/_routes.py`.
- [x] `W02.P03.S14` - Create the storage CLI group and a survey command with bounded filters and json output; `src/vaultspec_rag/cli/_service_storage.py`.
- [ ] `W02.P03.S15` - Wire the storage group into the CLI app and import registration; `src/vaultspec_rag/cli/_app.py`.
- [ ] `W02.P03.S16` - Add the CLI-to-service survey HTTP adapter handling the not-running case; `src/vaultspec_rag/cli/_http_search.py`.
- [ ] `W02.P03.S17` - Add a single-root in-process survey path for local mode; `src/vaultspec_rag/cli/_service_storage.py`.
- [ ] `W02.P03.S18` - Add a read-only survey MCP tool delegating to the service; `src/vaultspec_rag/mcp/_admin_tools.py`.
- [x] `W02.P03.S19` - Add real-backend survey tests for server and local classifying live, orphaned, and unknown; `src/vaultspec_rag/tests/integration/test_storage_survey.py`.

## Wave `W03` - prune and delete destructive verbs

Add the destructive control-plane verbs: per-root delete and orphaned-namespace prune, each releasing the in-memory slot before dropping data and gated by dry-run and confirmation. Depends on the Wave 2 manifest and survey. Authorized by the storage-lifecycle ADR.

### Phase `W03.P04` - delete a root index

Add a per-root delete that releases the in-memory slot, then drops the root namespaced collections or local store, gated by dry-run and confirmation.

- [x] `W03.P04.S20` - Implement a service-domain delete that releases the in-memory slot before dropping data and returns busy when the root is in use; `src/vaultspec_rag/service.py`.
- [x] `W03.P04.S21` - Drop the root namespaced collections in server mode and remove the local store tree only when the store is confirmed closed; `src/vaultspec_rag/store.py`.
- [ ] `W03.P04.S22` - Add a gated POST storage delete route and register it; `src/vaultspec_rag/server/_routes.py`.
- [x] `W03.P04.S23` - Add a storage delete CLI command with a required explicit target, dry-run preview, confirmation, and json; `src/vaultspec_rag/cli/_service_storage.py`.
- [ ] `W03.P04.S24` - Add the CLI-to-service delete HTTP adapter; `src/vaultspec_rag/cli/_http_search.py`.
- [x] `W03.P04.S25` - Drop the manifest entry on delete; `src/vaultspec_rag/registry.py`.
- [x] `W03.P04.S26` - Add real-backend delete tests for server and local including the busy-root path; `src/vaultspec_rag/tests/integration/test_storage_delete.py`.

### Phase `W03.P05` - prune orphaned namespaces

Add a server-mode prune that reclaims namespaces whose manifest root has vanished, never touching unattributable unknown namespaces.

- [x] `W03.P05.S27` - Implement a service-domain prune that selects orphaned namespaces from the manifest and never targets unknown namespaces; `src/vaultspec_rag/service.py`.
- [ ] `W03.P05.S28` - Add a gated POST storage prune route and register it; `src/vaultspec_rag/server/_routes.py`.
- [x] `W03.P05.S29` - Add a storage prune CLI command with a dry-run preview of exact targets, confirmation, and json; `src/vaultspec_rag/cli/_service_storage.py`.
- [ ] `W03.P05.S30` - Add the CLI-to-service prune HTTP adapter; `src/vaultspec_rag/cli/_http_search.py`.
- [x] `W03.P05.S31` - Add a real-backend prune test that creates an orphaned namespace and asserts it is reclaimed while unknown namespaces are untouched; `src/vaultspec_rag/tests/integration/test_storage_prune.py`.

## Wave `W04` - adversarial and data-safety hardening

Harden every destructive path against out-of-scope destruction, path traversal, symlink escape, unknown-namespace deletion, live-data races, and auth bypass, with an adversarial test suite. Depends on Wave 3 verbs existing. Authorized by the storage-lifecycle ADR data-safety decision.

### Phase `W04.P06` - threat-model hardening

Harden every destructive path against out-of-scope deletion, traversal, symlink escape, unknown-namespace deletion, live-data races, and auth bypass, with adversarial tests.

- [x] `W04.P06.S32` - Enforce that every destructive op operates only on the resolved root namespaces or managed storage tree and rejects roots outside the allowed base; `src/vaultspec_rag/service.py`.
- [x] `W04.P06.S33` - Reject path traversal and symlink escape in any path the surface deletes; `src/vaultspec_rag/service.py`.
- [x] `W04.P06.S34` - Guarantee prune and delete never remove unattributable unknown namespaces without an explicit separate gate; `src/vaultspec_rag/service.py`.
- [ ] `W04.P06.S35` - Verify refcount and store-lock checks run before any drop and that no deletion touches a live server storage file; `src/vaultspec_rag/store.py`.
- [ ] `W04.P06.S36` - Confirm destructive routes are loopback and token gated and that control-plane verbs are absent from MCP; `src/vaultspec_rag/server/_routes.py`.
- [x] `W04.P06.S37` - Add an adversarial test suite covering out-of-scope deletion, traversal and symlink payloads, unknown-namespace, busy-root, and json-without-confirmation; `src/vaultspec_rag/tests/integration/test_storage_adversarial.py`.

## Wave `W05` - migrate

Implement migrate last: a bounded research spike selects the fastest C-backed Python tooling for bulk vector and payload movement, then migrate relocates and converts a root index between backends. Depends on Waves 2 and 3 and on its own research spike. Authorized by the storage-lifecycle ADR.

### Phase `W05.P07` - fast-tooling research spike

Run a bounded research spike to select the most capable C-backed Python tooling for ultrafast bulk vector and payload movement, recorded as a reference.

- [x] `W05.P07.S38` - Research and select the most capable C-backed Python tooling for ultrafast bulk vector and payload movement and record a reference document; `.vault/reference/2026-06-18-storage-lifecycle-migrate-tooling-reference.md`.

### Phase `W05.P08` - migrate implementation

Implement migrate to relocate and convert a root index between backends using the selected tooling, reusing the single GPU consumer when re-embedding.

- [x] `W05.P08.S39` - Implement a service-domain migrate that relocates and converts a root index between local and server backends using the selected tooling; `src/vaultspec_rag/service.py`.
- [ ] `W05.P08.S40` - Reuse the single GPU consumer pipeline when migrate must re-embed and keep all storage IO outside the GPU lock; `src/vaultspec_rag/service.py`.
- [ ] `W05.P08.S41` - Add a gated POST storage migrate route and register it; `src/vaultspec_rag/server/_routes.py`.
- [x] `W05.P08.S42` - Add a storage migrate CLI command with dry-run, confirmation, and json; `src/vaultspec_rag/cli/_service_storage.py`.
- [ ] `W05.P08.S43` - Add the CLI-to-service migrate HTTP adapter; `src/vaultspec_rag/cli/_http_search.py`.
- [ ] `W05.P08.S44` - Re-key the manifest prefix, root, and backend on migrate; `src/vaultspec_rag/registry.py`.
- [x] `W05.P08.S45` - Add a real-backend migrate round-trip test between local and server with an integrity check; `src/vaultspec_rag/tests/integration/test_storage_migrate.py`.

## Description

This plan implements the server-authoritative storage lifecycle surface decided in the storage-lifecycle ADR and grounded in the storage-lifecycle research. The service daemon is the authority on stored data: a new service-domain storage module owns survey, prune, delete, and migrate, exposed as gated HTTP endpoints, with the CLI `server storage` group and a read-only MCP survey tool as thin adapters. Local mode is supported only as the single-root, in-process degenerate case.

Wave 1 closes issue 192 by adding real server-mode regression coverage for deleted-file eviction and applying the minimal durability fix it demands. Wave 2 lays the foundation every destructive verb depends on: a persisted prefix-to-root manifest that makes namespace attribution safe given the one-way namespacing hash, and the read-only survey that classifies each namespace as live, orphaned, or unknown. Wave 3 adds the destructive verbs (per-root delete and orphaned-namespace prune), each releasing the in-memory slot before dropping data. Wave 4 is a dedicated adversarial and data-safety pass over every destructive path. Wave 5 implements migrate last, after a bounded research spike selects the fastest C-backed Python tooling for bulk movement.

All tests exercise the real GPU, real Qdrant, and real models in both server and local backends, per the project test mandate; no mocks, fakes, or skips. Authorizing documents are carried in this plan's `related:` frontmatter.

## Parallelization

Waves are sequenced and land in order: W01 first (de-risks and produces the server-mode test scaffolding), then W02 (foundation), W03 (destructive verbs), W04 (data-safety hardening over those verbs), and W05 last. W04 must follow W03 because it hardens verbs that must already exist; W05 depends on both its own research spike (P07 before P08) and the W02 manifest.

Within waves, phases that share no hard interdependency may run in parallel: in W02, the manifest phase (P02) must precede the survey phase (P03), since survey reverse-maps through the manifest; in W03, delete (P04) and prune (P05) are independent and may proceed in parallel once W02 lands. Within any phase, the service-domain function is implemented before its route, CLI adapter, and tests, which may then proceed together.

## Verification

The plan is complete when every Step is closed and these criteria hold:

- A real server-mode regression test reproduces issue 192 (deleted file still returned by search) before the fix and passes after it; the vault-side twin passes too.
- After deleting a file and running a scoped incremental index in server mode, the store returns no chunks for that file and a real hybrid search does not surface it, with no full rebuild.
- `server storage survey` lists every namespace with its live, orphaned, or unknown classification and point counts in both backends, and daemon-side byte footprint in server mode; output is bounded and filterable.
- `server storage delete` and `server storage prune` remove only their explicit or orphaned targets, never an unknown namespace, never out-of-scope data; both refuse without `--yes`, preview exactly under `--dry-run`, require `--yes` with `--json`, and exit 3 when the service is not running.
- A busy root returns busy and is never deleted out from under a live store.
- The adversarial suite passes: out-of-scope deletion, path traversal, symlink escape, unknown-namespace, busy-root, and json-without-confirmation are all rejected.
- `server storage migrate` round-trips a root index between local and server backends with an integrity check, reusing the single GPU consumer when re-embedding and holding the GPU lock over forward passes only.
- The full real-backend test suite passes on the GPU host, ruff and basedpyright are clean, and the code reviewer signs off.
