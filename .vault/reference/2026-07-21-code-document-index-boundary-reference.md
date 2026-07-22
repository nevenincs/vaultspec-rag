---
tags:
  - '#reference'
  - '#code-document-index-boundary'
date: '2026-07-21'
modified: '2026-07-22'
related:
  - "[[2026-07-21-code-document-index-boundary-research]]"
  - "[[2026-06-10-preprocess-hooks-adr]]"
  - "[[2026-07-21-large-index-resilience-adr]]"
---

# `code-document-index-boundary` reference: `admission, storage, and recovery seams`

This blueprint audits the real full, incremental, watcher, CLI, storage, and downstream
consumer paths that currently classify extracted documents as code. It identifies the minimum
shared-policy slice and the blast radius of restoring a dedicated document content kind.

## Summary

### Admission epicentre

- `src/vaultspec_rag/indexer/_chunking.py:153-193` defines `LANGUAGE_MAP` and derives
  `SUPPORTED_EXTENSIONS` from it. Split parser capability from default content-domain
  admission; keep the language map available after the split.
- `src/vaultspec_rag/indexer/_codebase_indexer.py:317-398` is the full-tree admission path.
  It applies ignore first, then preprocess widening, then extension/size/binary gates.
- `src/vaultspec_rag/indexer/_codebase_indexer.py:1705-1762` is the scoped-path analogue.
  Both must delegate to the same disposition function rather than mirror gate ordering.
- `src/vaultspec_rag/watcher.py:86-127` mirrors extension and preprocess matching at the
  event boundary. It should ask the shared classifier for a content kind; adapters must not
  recreate policy.
- `src/vaultspec_rag/api.py:584-602` and `src/vaultspec_rag/cli/_index.py:138-181` power
  dry-run. They currently omit preprocess context and are not behaviorally equivalent to a
  real run.

The shared classifier should return a typed disposition such as content kind plus admitted
or rejected reason. Required inputs are project-relative path, file metadata/probe result,
ignore result, matched preprocess rule, and explicit rule target. Full scan, scoped scan,
watcher, dry-run, admission measurement, and service preflight consume that result.

### Preprocess contract and downstream proof

- `src/vaultspec_rag/indexer/_preprocess_config.py` owns the versioned rule schema. An
  explicit target belongs here and must participate in strict validation, list/check/status
  rendering, and the membership/content epoch as appropriate.
- `src/vaultspec_rag/indexer/_chunk_worker.py:96-145` converts `PreprocOutput` to
  `CodeChunk`, hardcoding extracted text into the code model.
- The audited consumer configuration is a real migration case: it matches HTML, PDF, XLS,
  and XLSX corpus sources and currently ignores only duplicate extraction sidecars.

Do not infer document intent from a directory, package, product, or domain name. Parser
capability may be extension-based, but content-kind routing requires explicit rule intent so
schema/tooling repositories can opt XSD or other unconventional source into code while
documents stay separate.

### Storage and query blast radius

Preprocessed units are structurally code throughout the stack:

- `_chunks_from_output` returns `CodeChunk` with `language="text"` and
  `preprocessor_id`.
- `src/vaultspec_rag/indexer/_streaming.py:184-240` sends those chunks through
  `upsert_code_chunks`.
- `src/vaultspec_rag/store_schema.py:55-59` and `:126-151` name and configure the
  `codebase_docs` collection.
- `src/vaultspec_rag/store.py:673-705` performs the code upsert.
- `src/vaultspec_rag/search/_result_shaping.py:151-196` labels results as `codebase`.

A dedicated content kind therefore reaches collection naming and lifecycle, local/server
payload indexes, count/status/clean operations, index jobs and source enums, search routing
and filters, result source labels, CLI/MCP/HTTP contracts, watcher dispatch, and service
health. Keep business rules in the service/store/index domains; CLI and MCP adapt to them.

### Migration and restart contracts

`src/vaultspec_rag/indexer/_config_epoch.py:61-106` currently fingerprints ignore and
preprocess rule patterns/invocations, but not `SUPPORTED_EXTENSIONS` or a versioned admission
policy. Add the content target and policy version to membership identity. Otherwise a deploy
can stop admitting new corpus paths while stale code points survive indefinitely.

The accepted large-index ledger must include content kind in its generation signature and
deterministic identity. A legacy mixed generation is incompatible. Migration must
idempotently remove old document points from `codebase_docs`, preserve already committed
work in each new domain, and never turn the split into a second restart-from-zero loop. The
existing large-index plan's checkpoint and finalization waves remain the correct recovery
foundation.

### One immutable policy snapshot per operation

- `src/vaultspec_rag/indexer/_codebase_indexer.py:190-240` resolves scan inputs and a
  preprocess config for epochs, while `:287-297` independently reloads worker context.
- Full indexing calls both paths separately at `:1398-1407`; incremental resolution and
  worker setup are also separate at `:1604-1626`.
- `src/vaultspec_rag/watcher.py:192-234` maintains another reloadable config instance.

Replace these copies with one immutable `ResolvedIndexPolicy` owned by an index operation.
It contains normalized admission rules, preprocess rules, ignore specs, content targets,
decoder policy, and their fingerprints. Full/scoped discovery, worker execution, watcher
dispatch confirmation, dry-run, epoch calculation, and checkpoints consume that object.
Configuration control events schedule all affected kinds for unscoped reconciliation.

The S06 implementation audit sharpened that boundary. Canonical tuples are authoritative;
compiled ignore and preprocess matchers are derived caches rebuilt after pickling. Preprocess
options require recursively frozen, type-tagged values because a frozen rule containing a
mutable mapping is not an immutable snapshot. Membership identity preserves order-sensitive
ignore semantics and separates persistent policy from operation-only excludes. Content
identity includes explicit policy, parser, and raw-chunk semantics versions; execution mode
has its own identity so switching extraction off preserves ownership and never authorizes
deletion.

### Preprocess schema, cache, and metadata integrity

- `src/vaultspec_rag/indexer/_preprocess_config.py:82-123` declares `options`, and
  `:374-405` parses them, but `src/vaultspec_rag/indexer/_preprocess_runner.py:264-317`
  neither passes them on the command line nor through a versioned input envelope.
- `src/vaultspec_rag/indexer/_preprocess_cache.py:64-82` hashes only source content,
  invocation text, and output schema. `src/vaultspec_rag/indexer/_chunk_worker.py:165-193`
  performs that lookup without a source path or complete execution fingerprint.
- `src/vaultspec_rag/indexer/_preprocess_schema.py:45-86` accepts source identity, title,
  section, and metadata. `src/vaultspec_rag/indexer/_chunk_worker.py:95-144` discards the
  latter fields and does not bind emitted source identity to the invoked input.

The next config/output schema must require an explicit content target and extractor version,
deliver normalized options through a defined JSON input or environment contract, and bind
output to the host-owned source identity. The default cache identity is source-path plus
source hash plus a canonical execution fingerprint (invocation, options, extractor version,
schema, and semantics-affecting modes). Cross-path content-addressable reuse is explicit opt-in.
Document payloads preserve title, section, locator, anchor, document/unit metadata, extractor
identity, and original source path under bounded/indexed-field rules.

### Failure state is not successful metadata

- `src/vaultspec_rag/indexer/_chunk_worker.py:342-414` returns a hash and no chunks for a
  preprocess skip, decode failure, or chunk failure.
- `src/vaultspec_rag/indexer/_codebase_indexer.py:899-904` records those hashes during full
  streaming, and `:1871-1876` writes scoped changed hashes regardless of output success.
- `src/vaultspec_rag/indexer/_chunk_worker.py:522-540` converts passthrough into an ordinary
  raw result and loses the preprocess disposition.

The ledger needs an explicit per-file terminal state. `indexed` and stable `policy_rejected`
are converged; `extract_retryable`, `extract_terminal`, `decode_failed`, and `chunk_failed`
remain visible outcomes, with retryability decided in the service domain. Passthrough retains
its rule target and error record and must satisfy the selected kind's raw decoder/admission
contract. Metadata publication includes only states the generation can prove.

### Resource and cache lifecycle boundaries

- A preprocess match bypasses raw size at
  `src/vaultspec_rag/indexer/_codebase_indexer.py:382-400`.
- `src/vaultspec_rag/indexer/_chunk_worker.py:342-371` reads the entire input before hashing
  and extraction; batch members do the same at `:447-459`.
- `src/vaultspec_rag/indexer/_preprocess_runner.py:116-121` counts characters under a setting
  named in bytes.
- A code clean clears the shared preprocessing cache at
  `src/vaultspec_rag/indexer/_codebase_indexer.py:1419-1423`.

Use streaming source hashing, per-rule and profile source-byte limits, weighted input/output
queue accounting, true encoded-byte measurement, aggregate extracted-byte/chunk ceilings,
and bounded batch groups. Extraction cache is an independently managed optimization,
partitioned by execution fingerprint; cleaning one index kind cannot evict another kind's
cache. Explicit extractor versioning replaces collection rebuild as cache invalidation.

### Public type and exhaustive-routing boundary

- Index and clean types are limited to `vault|code|all` in
  `src/vaultspec_rag/cli/_index.py:515-527`, `:780-790`, and
  `src/vaultspec_rag/api.py:465-516`.
- `docs` is an existing vault-search alias at `src/vaultspec_rag/cli/_search.py:438-460`.
- Server search and reindex use non-vault `else` branches that route unknown values to code at
  `src/vaultspec_rag/server/_routes.py:380-421` and `:568-587`.
- Jobs, transport, results, and status expose only two content domains at
  `src/vaultspec_rag/jobs.py:3220`, `src/vaultspec_rag/serviceclient/_transport.py:47`,
  `src/vaultspec_rag/search/_models.py:88-106`, and
  `src/vaultspec_rag/server/_models.py:104-137`.

Choose one non-conflicting canonical public token for extracted documents; keep the existing
`docs` alias meaning unchanged. Parse to a closed enum once and use exhaustive branches in the
service domain so unknown values are structured errors, never code fallthrough. Add the third
kind to index/search/clean/status/jobs/MCP/HTTP/storage migration and schema advertisement.
Combined search defines candidate allocation, filters, result source, reranking, and top-k
rather than inheriting two-domain assumptions accidentally.

### Both incomplete-sidecar states require ledger recovery

- Fresh-run points without a sidecar trigger another clean rebuild through
  `src/vaultspec_rag/indexer/_code_meta.py:96-110`.
- A clean rebuild drops the collection but retains the old sidecar, streams new points, and
  replaces metadata only at the end (`src/vaultspec_rag/indexer/_codebase_indexer.py:1419-1477`).
  Interruption can therefore leave a partial collection certified by stale complete hashes.
- There is no durable segment ledger; current streaming checkpoints are memory samples, while
  recovery is only `reconcile` (`src/vaultspec_rag/indexer/_streaming.py:184-240` and
  `src/vaultspec_rag/jobs.py:1818-1861`).

Generation publication must make both states explicit. A bounded store scan and fresh policy
classification recover legacy points when sidecar evidence is absent or stale. A target flip
upserts and checkpoints the destination before deleting and checkpointing the origin; replay
between phases is idempotent. Preserve existing source point IDs where possible, give document
points a collection-local identity, and put content kind in generation/checkpoint signatures.

### Required real-behavior tests

- Create a real temporary repository with Python source, valid and invalid UTF-8 XSD, PDF,
  XLSX, Markdown, and JSON plus a real extractor command and configuration. No mocks,
  monkeypatches, fakes, stubs, skips, or expected failures.
- Assert full discovery, scoped discovery, watcher classification, API scan, and CLI dry-run
  return the same code membership and disposition reasons.
- Assert a document-target preprocess rule does not widen code membership; assert an
  explicit code-target rule admits an unconventional source.
- Assert a targetless legacy config returns `migration_required` before any collection,
  metadata, cache, or ledger mutation; a lower-priority/default rule must not capture it.
- Assert the same immutable policy fingerprint governs admission, execution, publication,
  and checkpoint identity even when the config file changes during a run.
- Assert invalid UTF-8 document material never reaches the source decoder.
- Assert byte-identical files at different paths do not share path-dependent cached output;
  options and extractor-version changes invalidate cache deterministically, and all declared
  document metadata survives storage and result shaping.
- Assert preprocess skips and decode failures remain unresolved/visible and are retried under
  service policy; passthrough never changes content kind.
- Assert `.gitignore` and `.vaultragignore` remain inviolable across every content kind.
- Seed the real local store and metadata with a legacy mixed code/document state, change the
  admission epoch, run reconciliation, and verify exact code IDs, document IDs, counts, and
  metadata without mirrored business logic in the test.
- Repeat migration with no sidecar and with a stale sidecar over a partial clean rebuild;
  interrupt a target flip between destination upsert and origin deletion and prove replay.
- Interrupt a multi-segment real-store run, resume it, and prove replay is limited to the
  final unconfirmed unit in each content kind.
- Verify strict unknown-type rejection and stable `code`, explicit document, and `all`
  structured outcomes through in-process, resident-service, and MCP entry points.
- Exercise source-input, extracted-byte, chunk, queue, RSS, and CUDA ceilings independently;
  prove a code-only job launches no document extractor and a code clean preserves document
  cache and storage.

### Related plan correction

`.vault/plan/2026-07-21-large-index-resilience-plan.md:146-179` measures and accepts the
mixed incident corpus as the code profile. Replace that fixture with true source at a
comparable scale, or split the profile and acceptance harness by content kind. Do not relax
the resource ceilings, checkpoint, retry, no-progress, or cooperative-control requirements.
