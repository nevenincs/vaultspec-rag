---
generated: true
tags:
  - '#index'
  - '#index-backpressure-storage-hygiene'
date: '2026-08-14'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:83c48bd1c0e63866d4b4bb4e4a16e99dcca8eec6ba9d8bd79d090d1f8e8cc715'
related:
  - '[[2026-07-21-index-backpressure-storage-hygiene-P01-S01]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P01-S02]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P01-S03]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P01-S04]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P01-summary]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P02-S05]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P02-S06]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P02-S07]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P02-S08]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P02-summary]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P03-S09]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P03-S10]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P03-S11]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P03-summary]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P04-S12]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P04-S13]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P04-S14]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P04-S15]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P04-summary]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P05-S16]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P05-S17]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P05-S18]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P05-S19]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P05-summary]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P06-S20]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P06-S21]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P06-summary]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P07-S22]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P07-S23]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P07-S24]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P07-S25]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-P07-summary]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-adr]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-audit]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-plan]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-research]]'
---

# `index-backpressure-storage-hygiene` feature index

Auto-generated index of all documents tagged with `#index-backpressure-storage-hygiene`.

## Documents

### adr

- `2026-07-21-index-backpressure-storage-hygiene-adr` - `index-backpressure-storage-hygiene` adr: `fail-loud index write path and ephemeral-namespace hygiene for the shared backend` | (**status:** `accepted`)

### audit

- `2026-07-21-index-backpressure-storage-hygiene-audit` - `index-backpressure-storage-hygiene` audit: `execution review of the fail-loud write path and storage hygiene feature`

### exec

- `2026-07-21-index-backpressure-storage-hygiene-P01-S01` - add a configurable server-mode qdrant client timeout and a write-side classification wrapper around upsert_document_chunks and upsert_code_chunks (typed StorageWriteError with error_kind, bounded retry for transient kinds, disk_full non-retryable)
- `2026-07-21-index-backpressure-storage-hygiene-P01-S02` - bound the CUDA-OOM encode recovery in encode_documents and encode_documents_sparse to a halving ladder with floor batch size 1 that raises the underlying error on persistent failure
- `2026-07-21-index-backpressure-storage-hygiene-P01-S03` - add config knobs for the qdrant client timeout and write retry bounds following existing naming
- `2026-07-21-index-backpressure-storage-hygiene-P01-S04` - add unit tests for write-error classification, disk_full non-retryability, and the bounded encode ladder
- `2026-07-21-index-backpressure-storage-hygiene-P01-summary` - `index-backpressure-storage-hygiene` `P01` summary
- `2026-07-21-index-backpressure-storage-hygiene-P02-S05` - add error_kind to job records with mapping in record_finish, and a computed stalled flag (running, non-waiting, progress age past threshold) on job snapshots
- `2026-07-21-index-backpressure-storage-hygiene-P02-S06` - surface error_kind and stalled through the /jobs route, the server status summary, and /health
- `2026-07-21-index-backpressure-storage-hygiene-P02-S07` - render the shared error_kind and stalled fields in server jobs and server status output via one shared remediation mapping, removing the CLI-local disk-full string match
- `2026-07-21-index-backpressure-storage-hygiene-P02-S08` - add jobs-registry and route tests for error_kind propagation and stall flagging
- `2026-07-21-index-backpressure-storage-hygiene-P02-summary` - `index-backpressure-storage-hygiene` `P02` summary
- `2026-07-21-index-backpressure-storage-hygiene-P03-S09` - add a service-domain disk preflight (free bytes vs floor plus source-byte estimate) wired into start_reindex_codebase and start_reindex_vault, refusing with a structured disk_preflight_failed outcome
- `2026-07-21-index-backpressure-storage-hygiene-P03-S10` - wire the same preflight into the in-process CLI index fallback with a single structured non-zero envelope in --json mode
- `2026-07-21-index-backpressure-storage-hygiene-P03-S11` - add preflight tests covering refusal, pass-through, and envelope shape
- `2026-07-21-index-backpressure-storage-hygiene-P03-summary` - `index-backpressure-storage-hygiene` `P03` summary
- `2026-07-21-index-backpressure-storage-hygiene-P04-S12` - canonicalize Windows device-prefix aliases before hashing in root_collection_prefix so an extended-length alias cannot mint a duplicate namespace
- `2026-07-21-index-backpressure-storage-hygiene-P04-S13` - stamp ephemeral (root under the platform temp dir) and refresh a persisted last_indexed timestamp at manifest registration
- `2026-07-21-index-backpressure-storage-hygiene-P04-S14` - add the ephemeral idle-TTL reclaim tier to evaluate_reclaim and run_maintenance_cycle behind a config knob, reusing the empty/data tiers and destruction gates, and carry the ephemeral flag on survey rows
- `2026-07-21-index-backpressure-storage-hygiene-P04-S15` - add hygiene tests for alias-proof hashing, ephemeral flagging, and TTL-tier reclamation invariants
- `2026-07-21-index-backpressure-storage-hygiene-P04-summary` - `index-backpressure-storage-hygiene` `P04` summary
- `2026-07-21-index-backpressure-storage-hygiene-P05-S16` - pass tuned wal_config and optimizers_config at collection creation to shrink per-namespace preallocation
- `2026-07-21-index-backpressure-storage-hygiene-P05-S17` - diff on-disk collection dirs against live qdrant collections into debris survey entries and add a total-backend-bytes rollup exposed via survey, server status, and /metrics
- `2026-07-21-index-backpressure-storage-hygiene-P05-S18` - add an operator-gated debris removal flag to server storage prune with structured idempotent outcomes
- `2026-07-21-index-backpressure-storage-hygiene-P05-S19` - add tests for tuned collection config, debris detection, and the total-bytes rollup
- `2026-07-21-index-backpressure-storage-hygiene-P05-summary` - `index-backpressure-storage-hygiene` `P05` summary
- `2026-07-21-index-backpressure-storage-hygiene-P06-S20` - document the new job outcomes, preflight, ephemeral TTL, and debris reclaim in the storage and CLI docs
- `2026-07-21-index-backpressure-storage-hygiene-P06-S21` - extend the ADR regression guards for lifecycle inertness of the new hygiene code and the bounded-retry invariant
- `2026-07-21-index-backpressure-storage-hygiene-P06-summary` - `index-backpressure-storage-hygiene` `P06` summary
- `2026-07-21-index-backpressure-storage-hygiene-P07-S22` - add an autouse suite-level isolation guard that points status and qdrant storage dirs at tmp for every test and fails fast if a test observes the machine-global dirs
- `2026-07-21-index-backpressure-storage-hygiene-P07-S23` - add a lifecycle tripwire refusing stop/terminate of the machine-global service when running under pytest without explicitly isolated status dir
- `2026-07-21-index-backpressure-storage-hygiene-P07-S24` - persist an active-jobs snapshot and mark jobs from a prior daemon life as interrupted at startup so killed jobs never vanish from server jobs
- `2026-07-21-index-backpressure-storage-hygiene-P07-S25` - add tests for the isolation guard, the lifecycle tripwire, and interrupted-job visibility across a simulated daemon restart
- `2026-07-21-index-backpressure-storage-hygiene-P07-summary` - `index-backpressure-storage-hygiene` `P07` summary

### plan

- `2026-07-21-index-backpressure-storage-hygiene-plan` - `index-backpressure-storage-hygiene` plan

### research

- `2026-07-21-index-backpressure-storage-hygiene-research` - `index-backpressure-storage-hygiene` research: `silent index wedge under qdrant write failure and unbounded shared-backend degradation`
