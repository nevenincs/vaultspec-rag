---
tags:
  - '#plan'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
tier: L2
related:
  - '[[2026-07-21-index-backpressure-storage-hygiene-adr]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-research]]'
---


# `index-backpressure-storage-hygiene` plan

Close issue 242: make index write failures loud and classified, refuse indexing into a full disk, and stop the shared backend degrading through temp namespaces, alias duplicates, fat empty collections, and invisible crash debris.

### Phase `P01` - fail-loud store writes and bounded encode retries

Convert the silent write wedge into a prompt classified job failure: explicit client timeout, typed write-error classification with bounded retry, and a bounded CUDA-OOM encode ladder.

- [x] `P01.S01` - add a configurable server-mode qdrant client timeout and a write-side classification wrapper around upsert_document_chunks and upsert_code_chunks (typed StorageWriteError with error_kind, bounded retry for transient kinds, disk_full non-retryable); `src/vaultspec_rag/store.py`.
- [x] `P01.S02` - verify the CUDA-OOM encode recovery is already floor-bounded (halving ladder raises at batch size 1) and pin that invariant with a regression test so no unbounded retry loop can return between a storage error and job failure; `src/vaultspec_rag/tests/test_embeddings_unit.py`.
- [x] `P01.S03` - add config knobs for the qdrant client timeout and write retry bounds following existing naming; `src/vaultspec_rag/config.py`.
- [x] `P01.S04` - add unit tests for write-error classification, disk_full non-retryability, and the bounded encode ladder; `src/vaultspec_rag/tests/`.

### Phase `P02` - structured job errors and stall surfacing

Give every adapter a shared error taxonomy and stall signal: error_kind on job records, a computed stalled flag, surfaced through /jobs JSON, server status, and /health.

- [x] `P02.S05` - add error_kind to job records with mapping in record_finish, and a computed stalled flag (running, non-waiting, progress age past threshold) on job snapshots; `src/vaultspec_rag/jobs.py`.
- [x] `P02.S06` - surface error_kind and stalled through the /jobs route, the server status summary, and /health; `src/vaultspec_rag/server/`.
- [x] `P02.S07` - render the shared error_kind and stalled fields in server jobs and server status output via one shared remediation mapping, removing the CLI-local disk-full string match; `src/vaultspec_rag/cli/_service_jobs.py`.
- [x] `P02.S08` - add jobs-registry and route tests for error_kind propagation and stall flagging; `src/vaultspec_rag/tests/`.

### Phase `P03` - free-disk preflight

Refuse bulk indexing into a full disk at the job-submission boundary with a structured, remediating outcome.

- [x] `P03.S09` - adopt the PR 246 disk headroom guards (per-write floor and bulk preflights at the vault, code, and pipeline phases) as the preflight implementation; `verify coverage of every bulk entry; `src/vaultspec_rag/jobs.py`.
- [x] `P03.S10` - verify the in-process CLI index path surfaces InsufficientDiskSpaceError as one structured non-zero envelope in --json mode, adding handling only where missing; `src/vaultspec_rag/cli/_index.py`.
- [x] `P03.S11` - confirm the PR 246 preflight tests cover refusal, pass-through, and remote-storage skip; `extend only where gaps remain; `src/vaultspec_rag/tests/`.

### Phase `P04` - namespace hygiene

Stop the shared backend degrading: alias-proof prefix hashing, ephemeral flagging of temp roots at registration, and a persisted idle-TTL reclaim tier through the existing destruction gates.

- [x] `P04.S12` - verify the upstream extended-length alias normalization in root_collection_prefix (landed on main via PR 245) covers registration, teardown, and rekey call sites, extending alias tests only where gaps remain; `src/vaultspec_rag/_store_models.py`.
- [x] `P04.S13` - persist a last_indexed activity stamp per prefix at manifest registration and refresh it on every index write, reusing the upstream temp-rooted classifier for ephemerality; `src/vaultspec_rag/storage_manifest.py`.
- [x] `P04.S14` - add the ephemeral idle-TTL reclaim tier to evaluate_reclaim and run_maintenance_cycle behind a config knob, reusing the empty/data tiers and destruction gates, and carry the ephemeral flag on survey rows; `src/vaultspec_rag/storage_ops.py`.
- [x] `P04.S15` - add hygiene tests for alias-proof hashing, ephemeral flagging, and TTL-tier reclamation invariants; `src/vaultspec_rag/tests/`.

### Phase `P05` - cheap collections and debris visibility

Cut empty-namespace preallocation via tuned collection config and make crash debris and total backend size visible and operator-reclaimable.

- [x] `P05.S16` - measure empty-namespace on-disk footprint under the isolated qdrant harness and pass tuned wal_config and optimizers_config at collection creation only if preallocation is confirmed as the driver; `src/vaultspec_rag/store.py`.
- [x] `P05.S17` - diff on-disk collection dirs against live qdrant collections into debris survey entries and add a total-backend-bytes rollup exposed via survey, server status, and /metrics; `src/vaultspec_rag/storage_ops.py`.
- [x] `P05.S18` - add an operator-gated debris removal flag to server storage prune with structured idempotent outcomes; `src/vaultspec_rag/cli/`.
- [x] `P05.S19` - add tests for tuned collection config, debris detection, and the total-bytes rollup; `src/vaultspec_rag/tests/`.

### Phase `P06` - docs and closeout

Document the new outcomes, knobs, and hygiene behavior and extend the ADR regression guards.

- [x] `P06.S20` - document the new job outcomes, preflight, ephemeral TTL, and debris reclaim in the storage and CLI docs; `docs/`.
- [x] `P06.S21` - extend the ADR regression guards for lifecycle inertness of the new hygiene code and the bounded-retry invariant; `src/vaultspec_rag/tests/test_adr_regression.py`.

### Phase `P07` - shared-service protection from test runs

Close defect 3: a pytest run must never terminate or mutate the operator's machine-global service, and jobs killed by a daemon death must remain visible as interrupted instead of vanishing.

- [x] `P07.S22` - add an autouse suite-level isolation guard that points status and qdrant storage dirs at tmp for every test and fails fast if a test observes the machine-global dirs; `src/vaultspec_rag/tests/conftest.py`.
- [x] `P07.S23` - add a lifecycle tripwire refusing stop/terminate of the machine-global service when running under pytest without explicitly isolated status dir; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P07.S24` - persist an active-jobs snapshot and mark jobs from a prior daemon life as interrupted at startup so killed jobs never vanish from server jobs; `src/vaultspec_rag/jobs.py`.
- [x] `P07.S25` - add tests for the isolation guard, the lifecycle tripwire, and interrupted-job visibility across a simulated daemon restart; `src/vaultspec_rag/tests/`.

## Description

Implements the accepted ADR for this feature (see `related:`), grounded in the
2026-07-21 research with file-level evidence. The incident behind issue 242
proved the job-failure machinery works only for raised exceptions; P01 makes
every persistent storage failure raise (client timeout, typed classification,
bounded encode ladder), P02 makes failures and stalls visible on every adapter
surface from one shared taxonomy, P03 refuses bulk work that cannot land, P04
closes the namespace leak (alias-proof hashing, ephemeral flag plus persisted
idle-TTL tier through the unchanged destruction gates), P05 shrinks empty
namespaces and surfaces crash debris plus total backend size, and P06
documents and regression-guards the whole. All maintenance-adjacent work must
stay lifecycle-inert and every test isolates both storage env dirs.

## Steps

## Parallelization

P01 and P04 are independent and may run in parallel. P02 depends on P01
(error_kind originates from the typed write error); P03 depends on P02 (the
refusal reuses the structured outcome shape). P05 touches `store.py` and
`storage_ops.py` and should follow P01/P04 to avoid merge friction. P06 is
last. Within a phase, the test step follows its implementation steps; other
steps within a phase may proceed in order listed.

## Verification

- A simulated persistent upsert failure fails the index job within the
  bounded retry budget with `error_kind` attached, and a simulated
  disk-full error fails without retry (unit test proves both).
- A running job past the stall threshold reports `stalled` in `/jobs` JSON
  and the `server status` summary (test proves the service-domain flag).
- Preflight refusal emits exactly one structured `disk_preflight_failed`
  envelope and a non-zero exit in `--json` mode.
- A device-prefix alias of a registered root resolves to the same namespace
  prefix (unit test with the verified alias forms).
- An ephemeral-flagged namespace reclaims only after the persisted idle TTL,
  through `delete_prefix`/`archive_prefix`, never when unknown or
  unverifiable; grace clocks never shorten across restarts.
- The lifecycle-inertness import-graph regression test still passes with the
  new hygiene code in scope.
- Full unit suite, lint (prek), and type gates green locally; GPU
  integration tests run locally before merge (no GPU CI).
- The plan is complete when every Step row is closed and the
  vaultspec-code-review audit records its verdict.
