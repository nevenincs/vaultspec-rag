---
tags:
  - '#research'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:2e8c03742385ad8ed555a24d7e9045f259cc23244c3eed2c1cfdbcae400cc69d'
related:
  - "[[2026-06-26-storage-schema-contract-adr]]"
  - "[[2026-07-24-worktree-index-reuse-adr]]"
  - "[[2026-07-22-service-health-client-hardening-adr]]"
---

# `storage-conformance` research: `verifying stored data against the code that reads it`

A client, the resident daemon, and the Qdrant data on disk each carry a version
constant, and the chain enforces almost none of them. The question this record
grounds is narrow: before the service searches a collection, can it prove that
collection was produced by the models and the shape the current code expects?

Today it cannot, and the reason is structural rather than an oversight. Every
conformance signal the product publishes is derived from live configuration, so
it describes what the code is configured with and never what the storage holds.
Comparing that description against the code it came from always succeeds. The
missing half is not a comparator - a complete, tested one already exists and is
unreachable from production - but a durable record of what actually produced the
vectors.

The evidence favors persisting an effective-identity record per namespace at
collection-create time and verifying it on the path every read and write already
traverses. What the ADR must settle is where that record lives, whether a
mismatch refuses or degrades, and how a namespace written before the record
existed is treated.

## Findings

### F1 - A same-dimension model swap is undetectable, and the vault index never recovers

The embedding model is not an input to any config epoch. `code_content_epoch`
hashes preprocess rules, `html_strip`, and `max_emitted_bytes`
(`src/vaultspec_rag/indexer/_config_epoch.py:336`); `code_membership_epoch` hashes
ignore patterns (`:314`); `vault_content_epoch` hashes only `vault_chunk_chars`
(`:368`). Swapping `embedding_model` for a different model of the same dimension
therefore leaves `classify_config_drift` returning `ok`
(`src/vaultspec_rag/indexer/_code_meta.py:75`), and `needs_embed_rebuild` compares
an embed-format literal that a model swap does not move (`:101`).

No file changed, so the watcher fires no run. Every search in the interim encodes
queries with the new model and scores them against vectors from the old one.
Cosine scores stay in range and results remain plausibly ordered; nothing errors
and nothing logs.

Code and document indexes recover by accident on the next unrelated edit: a
`RunLedgerCompatibilityError` is caught at
`src/vaultspec_rag/indexer/_codebase_indexer.py:3577` and degrades to a full
reconciliation that re-encodes every path. The recovery is real but incidental,
unbounded in latency, and logged as `No compatible published code manifest`
(`:3578`), which names nothing about the model. The vault index has no run ledger
at all - `_vault_indexer.py` imports none - so it stays mixed-model until an
operator runs `index --rebuild` (`src/vaultspec_rag/cli/_index.py:548`).

This is the highest-severity finding because it is the only one where a healthy
service returns confidently wrong answers with no trace on any surface.

### F2 - The two guards that appear to cover model identity do not

`RunSignature.model_identity` (`src/vaultspec_rag/indexer/_run_ledger.py:226`) does
carry real model names, built at `_codebase_indexer.py:2221`. Its scope is
generation resumability: a mismatch means `start_generation` finds no compatible
parent and raises `RunLedgerCompatibilityError`
(`src/vaultspec_rag/indexer/_run_checkpoint.py:127`). It is per-root, lives in that
root's own directory, and covers code and document only.

`MODEL_IDENTITY_MISMATCH` (`src/vaultspec_rag/indexer/_donor_candidates.py:115`) is
a misnomer. It compares `embed_schema`, a hand-bumped format literal
(`_code_meta.py:36`), not a model name. `ModelIdentity.dense_model` and
`.sparse_model` are constructed at `_donor_candidates.py:228` and never compared,
because both sides read the same live config. The docstring concedes the point at
`:131` and `:490`.

`donor_schema_probe` (`_donor_candidates.py:433`) is the one function that could
read live geometry, and no production caller supplies it - `_reuse.py:280` passes
only candidate, kind, and expected content epoch - so the `VECTOR_LAYOUT_MISMATCH`
gate is unreachable in production.

A plain search is covered by none of them: `src/vaultspec_rag/search/` contains no
reference to `store_schema`, to a dimension, or to model identity.

### F3 - The one enforcing storage-version gate disarms itself on store open

`ManifestEntry.storage_schema_version` is persisted
(`src/vaultspec_rag/storage_manifest.py:117`) and an absent field loads as `1`
(`:257`). But `record_root` (`:329`) and `rekey_prefix` (`:538`) always stamp the
current constant without consulting the stored value. The only in-module
comparison, `:342`, is a write-skip idempotence check: on mismatch it falls
through to `:347` and overwrites a v1 record with v2, with no migration and no
warning. It fires from `src/vaultspec_rag/store.py:745`, so merely opening the
store relabels a stale namespace as current.

The sole enforcing reader is `_donor_candidates.py:472`, and it reads the
manifest's claim rather than the data - a claim any store open has already
refreshed. The gate therefore protects nothing once the namespace has been opened.

### F4 - No production path reads live collection geometry

`_ensure_collection` returns early when the collection exists
(`src/vaultspec_rag/store.py:637`) and sets `size=self._embedding_dim` only on
create (`:656`). Dimension, distance, vector names, and quantization are never
compared against an existing collection. Payload indexes are the exception and are
reconciled on that same path (`:842`), which establishes the precedent that
reaching an existing collection to fix it is acceptable here.

Every `get_collection` call reads optimizer geometry for preallocation reconcile
(`src/vaultspec_rag/storage_ops.py:500`, `:624`) or enumerates names. One inverts
the check outright: `copy_collection` (`:1032`) replays `config.params.vectors`
verbatim into the destination, propagating whatever shape existed rather than
validating it.

`EmbeddingModel.dimension` is set from config, not from the loaded model
(`src/vaultspec_rag/embeddings.py:485`), and the model's real output width is never
asserted - in contrast to the sparse path, which does validate at `:462`. Config
and reality can therefore diverge with no signal at the point of truth.

### F5 - A dimension mismatch is loud, but late and misattributed

Against an existing collection Qdrant rejects the wrong-size vector. On the write
side `classify_write_error` does not treat the 400 as unrecoverable
(`src/vaultspec_rag/_store_writes.py:186`), so the run burns its full retry and
backoff budget logging `transient store operation failure` (`:210`) before
raising. On the search side the hybrid path catches the error and logs
`Hybrid search failed, falling back to dense-only`
(`src/vaultspec_rag/_store_search.py:340`); the dense fallback then raises
uncaught. The operator's first log line blames hybrid search rather than the
dimension.

### F6 - The comparator already exists and is unreachable

`assert_compatible` (`src/vaultspec_rag/store_schema.py:376`) implements the
version, dense-dimension, and vector-name rules completely and is covered by
tests. It has zero production callers. This is deliberate rather than an
oversight: the governing decision scopes the assertion to an out-of-process
consumer and states that rag advertises while the consumer asserts.

What that decision did not settle is whether rag should apply the same rules to
itself on its own read paths. That is the open question, and it is narrow.

The reason the descriptor cannot answer it as published is structural:
`describe_storage_schema` (`:284`) reads the dense dimension from
`cfg.embedding_dimension` (`:266`) and the model names from `cfg.embedding_model`
and `cfg.sparse_model` (`:255`). It reports configuration, never storage, so
feeding it to the comparator compares the config against itself and always passes.
Its only non-test caller is a report field at `src/vaultspec_rag/_readiness.py:169`,
and nothing in `serviceclient/`, `mcp/`, `commands/`, or `cli/` fetches
`/readiness` at all. The descriptor is write-only.

### F7 - Degradation has no conformance input, and cannot distinguish empty from incompatible

`degraded_reasons` is authored in exactly two places, both process-liveness and
job-outcome only: `_service_health_status`
(`src/vaultspec_rag/server/_lifespan.py:873`) reports unloaded models and a dead
vector service, and `_jobs_health` (`:1007`) reports stalled and failed jobs. They
are concatenated at `:1070`. Nothing counts a point, asks whether a collection
exists, or compares anything to `store_schema`.

Index availability is a bare threshold: `status` is `missing` when `count == 0`
(`src/vaultspec_rag/server/_routes.py:277`), which `_empty_search_diagnostics`
(`:287`) maps to a generic run-index remediation. So `never indexed`,
`destroyed`, and `incompatible` are one indistinguishable state.

Observed live during this research: the resident service reported
`Requests: degraded` for a failed job while `search_codebase` against the same
root returned `indexed_count: 0`. The empty index contributed nothing to the
verdict.

### F8 - The readiness axis is a check list with a generic renderer, and is bounded by policy

`ReadinessReport` composes `DependencyReadiness(name, status, detail, info)` nodes
with a `READY / NOT_READY / UNKNOWN` vocabulary
(`src/vaultspec_rag/_readiness.py:76`, `:51`), aggregates `ready` as all-READY
(`:129`), and the CLI renders any node generically
(`src/vaultspec_rag/cli/_service_doctor.py:346`). The check set is a hardcoded
three-element list (`_readiness.py:189`), so adding an axis is one function plus
one list entry.

Two constraints bear on using it. The module is committed by its own docstring
(`:1`) to being torch-free, download-free, mutation-free, and safe to call before
any runtime is up, and it is explicitly bounded against accreting into a general
health console; `_qdrant_readiness` performs no I/O today. And
`_doctor_exit_code` (`_service_doctor.py:81`) deliberately does not raise the exit
code for a not-ready dependency, so a conformance failure surfaced only there
would report but still exit zero.

### F9 - Adjacent links, recorded but out of scope

Neither of these is decided by this record; each is noted so the boundary is
explicit.

Client against daemon: no package version reaches any wire surface. The daemon
publishes `executable`, `prefix`, and `virtual_env`
(`src/vaultspec_rag/server/_lifecycle.py:180`) - exactly the fields that identify a
foreign build - and every client reads them display-only
(`src/vaultspec_rag/cli/_status_render.py:519`). `server start` attaches to a live
daemon on token identity alone (`src/vaultspec_rag/cli/_service_start.py:173`).
`SERVICE_DISCOVERY_VERSION` (`src/vaultspec_rag/serviceclient/_discovery.py:32`) is
stamped by two writers and validated by no reader, though
`docs/service-discovery.md:83` instructs consumers to refuse a file they do not
understand. No route uses a request model, so an unknown request field is dropped
silently (`src/vaultspec_rag/server/_routes.py:1149`).

Qdrant binary against storage format: the pin is coupled to the `qdrant-client`
Python minor line (`src/vaultspec_rag/qdrant_runtime/_constants.py:26`), a wire-API
guard that says nothing about disk format, and nothing stamps a binary version
inside the storage dir. If a new binary panics opening an old store,
`_corrupt_collection_from_output`
(`src/vaultspec_rag/qdrant_runtime/_supervise.py:140`) matches the panic tail
against a collection directory name and quarantines it, up to three times per
start (`:78`); the daemon then comes up healthy while those roots return empty
results. The matcher's docstring states it deliberately avoids Qdrant's
version-dependent message format, so it cannot separate corruption from
incompatibility. This is a silent-data-loss path and deserves its own record.

### F10 - The gap is already documented as blocked, by the team

The worktree index reuse work required identical embedding model identity
including revision as a reuse gate, and its execution record states the
requirement could not be met: configured model names are process-global rather
than persisted per root, model revision is recorded nowhere, and closing the gap
fully would require new persisted state that the governing decision forbade. That
prohibition was scoped to that record's implementation, not adopted globally, so
authorising the state is available to a new decision.

### Not investigated

Whether a same-dimension swap measurably degrades ranking quality was not
quantified - the finding rests on the mechanism, not on a benchmark. Migration of
existing non-conforming namespaces was not designed. The dashboard's consumer-side
adoption is cross-repo and untouched.

## Sources

- `src/vaultspec_rag/store_schema.py:60`, `:255`, `:266`, `:284`, `:376`
- `src/vaultspec_rag/store.py:637`, `:656`, `:745`, `:842`
- `src/vaultspec_rag/storage_manifest.py:117`, `:257`, `:329`, `:342`, `:347`, `:538`
- `src/vaultspec_rag/storage_ops.py:500`, `:624`, `:1032`
- `src/vaultspec_rag/indexer/_config_epoch.py:314`, `:336`, `:368`
- `src/vaultspec_rag/indexer/_code_meta.py:36`, `:75`, `:101`
- `src/vaultspec_rag/indexer/_donor_candidates.py:115`, `:131`, `:228`, `:433`, `:472`, `:490`
- `src/vaultspec_rag/indexer/_run_ledger.py:226`
- `src/vaultspec_rag/indexer/_run_checkpoint.py:127`
- `src/vaultspec_rag/indexer/_codebase_indexer.py:2221`, `:3577`
- `src/vaultspec_rag/indexer/_reuse.py:280`
- `src/vaultspec_rag/embeddings.py:462`, `:485`
- `src/vaultspec_rag/_store_writes.py:186`, `:210`
- `src/vaultspec_rag/_store_search.py:340`
- `src/vaultspec_rag/_readiness.py:1`, `:51`, `:76`, `:129`, `:169`, `:189`
- `src/vaultspec_rag/server/_lifespan.py:873`, `:1007`, `:1070`
- `src/vaultspec_rag/server/_routes.py:277`, `:287`, `:1149`
- `src/vaultspec_rag/server/_lifecycle.py:180`
- `src/vaultspec_rag/serviceclient/_discovery.py:32`
- `src/vaultspec_rag/qdrant_runtime/_constants.py:26`
- `src/vaultspec_rag/qdrant_runtime/_supervise.py:78`, `:140`
- `src/vaultspec_rag/cli/_index.py:548`
- `src/vaultspec_rag/cli/_service_doctor.py:81`, `:346`
- `src/vaultspec_rag/cli/_service_start.py:173`
- `src/vaultspec_rag/cli/_status_render.py:519`
- `docs/service-discovery.md:83`

Live-service observations were taken against `vaultspec-rag@0.3.9` on
`127.0.0.1:8766` on 2026-07-25.

## Context

The compatibility chain from a client, through the resident daemon, to the Qdrant
data on disk carries a version constant at every link and enforces one at almost
none. This record grounds a conformance decision: can the running service prove
that the data it is about to search was produced by the models and the shape the
current code expects?

Scope is the storage link - daemon against on-disk data. The client-against-daemon
link and the Qdrant-binary-against-storage-format link are real and are recorded
here as findings, but each warrants its own decision.

Vocabulary note: `drift` in this project already means content or configuration
staleness of an index against its own inputs, and it is the active vocabulary of
an in-flight plan. This work uses `conformance` throughout for the distinct
question of whether a component's understanding of the schema and the models
matches what is actually stored.
