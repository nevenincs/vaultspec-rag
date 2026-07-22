---
tags:
  - '#adr'
  - '#code-document-index-boundary'
date: '2026-07-21'
modified: '2026-07-22'
related:
  - "[[2026-07-21-code-document-index-boundary-research]]"
  - '[[2026-07-21-code-document-index-boundary-reference]]'
  - '[[2026-06-10-preprocess-hooks-adr]]'
  - '[[2026-07-21-preprocess-batch-hooks-adr]]'
  - '[[2026-07-14-preprocess-sandbox-removal-adr]]'
  - '[[2026-07-13-index-drift-hardening-adr]]'
  - '[[2026-06-26-storage-schema-contract-adr]]'
  - '[[2026-07-21-large-index-resilience-adr]]'
---

# `code-document-index-boundary` adr: `explicit content-kind admission and document isolation` | (**status:** `accepted`)

## Problem Statement

Preprocess-rule matches currently bypass the ordinary extension, size, and binary gates and
are stored in the code collection. Parser support is also used as an admission list. These
contracts conflate three independent questions: whether a format can be parsed, whether a
file belongs in an index, and which content domain owns it.

Consequently, `code` can include extracted documents and ambiguous text formats, dry-run can
report different membership from a real index, and watcher, scoped, and full indexing can
classify the same path differently. The correction must be generic and driven by explicit
caller intent. It must not infer content kind from directory, package, product, or domain
names.

## Considerations

- Preprocessing remains generic caller-supplied extraction infrastructure. Its command
  execution, validation, timeout, caching, failure isolation, and CPU/GPU boundaries remain
  valid.
- A parser's ability to split a format does not establish that the format belongs in the code
  index.
- A preprocess match establishes how to transform a file, not which content domain owns the
  result.
- Ignore rules retain absolute precedence across every content kind.
- Full discovery, scoped discovery, watcher events, dry-run, and service preflight must
  produce the same admission decision and reason.
- One operation must resolve configuration once; admission, extraction, epochs, publication,
  and checkpoints cannot observe different snapshots.
- `code` must remain source-only while extracted documents remain independently searchable.
- Existing mixed points require deterministic, idempotent reconciliation.
- A malformed or unmigrated routing policy must stop index mutation rather than degrade into
  a different admission policy.
- Raw input, extracted output, chunks, queues, host memory, and device memory all need bounded
  budgets for document processing as well as code processing.
- Large-index restart and checkpoint resilience remains necessary, but is independent from
  correcting admission.

## Considered options

**Consumer-managed ignores only.** Rejected because it leaves the upstream content-domain
contract and dry-run divergence unchanged, while making correctness depend on transient
repository layouts.

**Directory or filename heuristics.** Rejected because names such as `data`, `corpus`, package
names, and product-specific paths have no universal meaning and would misclassify valid
source.

**Shared code classifier without a document domain.** This safely prevents document-target
rules from widening code admission, but removes searchable preprocessing output. It is
suitable as an implementation slice, not the complete architecture.

**Shared classifier with an explicit document domain.** Chosen. Caller-authored routing
determines content kind, code stays source-only, and document preprocessing remains a
first-class searchable capability.

## Constraints

- If accepted, this decision narrowly amends the preprocess-hooks storage compromise and the
  D2/D8 implications that any preprocess match widens code admission. It also amends D3's
  degrade behavior for routing defects, D7's clean-cache coupling, D10's unbounded source
  input, and the related batch, kill-switch, drift-epoch, storage-schema, and large-index
  acceptance contracts. Rule matching, ignore precedence, subprocess isolation, validation,
  timeouts, surfaced failures, CPU-only workers, and forward-only GPU locking remain binding.
- Preprocess rules must declare their target content kind explicitly. A missing or unknown
  target must not fall back to code admission.
- The source-admission policy must be separate from the parser/chunker registry and
  independently versioned.
- One path resolves to at most one content kind per policy snapshot. Conflicting explicit
  admission and preprocess targets are configuration errors, not precedence guesses.
- Classification must be implemented once in the service/index domain. CLI, API, watcher,
  and worker adapters may consume its disposition but must not reproduce its rules.
- The document domain requires independent storage, lifecycle, counts, search routing,
  result labels, and reconciliation.
- Migration must handle missing, stale, and partial sidecars, remove legacy document points
  from the code collection without copying stale payloads blindly, and avoid another
  restart-from-zero cycle.
- Content kind and admission-policy version participate in membership, generation, and
  checkpoint identity. Existing source point IDs remain stable; document points use their
  own collection-local identity scheme.
- The preprocessing kill switch disables execution, not policy knowledge. It cannot authorize
  deletion or reclassification merely because hooks are temporarily disabled.
- Unknown public source types are rejected exhaustively and never fall through to code.
- Existing CPU-only worker, single GPU consumer, and GPU-lock contracts remain unchanged.
- The accepted checkpoint and restart work remains authoritative except where its acceptance
  fixtures incorrectly describe mixed document input as code.

## Implementation

**D1 - Explicit routing and source admission.** Introduce a typed `ContentKind` and
`AdmissionDisposition`. A root content-policy contract owns ordered caller-authored routing
rules independently of preprocessing; a preprocess rule is an optional transform with a
required target. Ignore wins first. Explicit targets are compiled next and must agree when
they overlap. Only then may a public, versioned, path-agnostic conventional-source profile
admit source by default; ambiguous parser-only formats require explicit routing. A caller may
select an explicit-only profile. No built-in rule names a consumer directory or package.

One path has one owner in a snapshot. A `document` target overrides default source admission;
a `code` target can admit unconventional source; a raw document rule can route decodable text
without requiring an extractor. Parser selection happens only after admission and remains a
capability registry, never a membership registry.

**D2 - One immutable policy snapshot.** Each index, scan, preflight, or dry-run operation
resolves a `ResolvedIndexPolicy` once. It contains ignore specs, admission rules, preprocess
rules, targets, decoder policy, execution mode, and normalized fingerprints. Full scan,
scoped scan, watcher dispatch confirmation, workers, epochs, checkpoint signatures, and
publication all consume that exact object. Watcher configuration events schedule every
affected kind for unscoped reconciliation; deleted paths use prior ledger membership rather
than current-file inference.

The public path-list scan remains as a compatibility projection. A new structured scan API
returns bounded samples and counts by kind and stable disposition reason. CLI dry-run and
service preflight use the structured API and apply the same preprocessing mode as execution.

**D3 - Versioned migration and failure semantics.** The next preprocess schema requires
`target = "code"` or `target = "document"`. A legacy targetless rule, unknown target,
conflicting route, or otherwise invalid routing policy returns structured
`migration_required`/`admission_config_invalid` before any collection, metadata, ledger, or
cache mutation. The resident service may remain live but exposes the affected index as
degraded. A rejected rule is never treated as absent, so lower-priority/default admission
cannot capture its paths.

The kill switch preserves the resolved policy while suppressing extractor execution. It marks
affected document or code routes disabled/stale and performs no deletion; policy edits and
ignore changes are the mechanisms that alter membership. `skip`, `fail`, and `passthrough`
retain their declared target. Passthrough is allowed only when raw admission and decoding for
that same kind succeed; it never becomes code implicitly.

**D4 - Faithful preprocessing and cache identity.** A versioned invocation envelope delivers
the canonical source identity, normalized rule options, configured extractor version, and
mode to command and entry-point implementations. The host binds output to the invoked input;
an extractor cannot redirect storage by emitting another source path. The document model
preserves title, section, anchor, locator, document metadata, unit metadata, extractor
identity/version, and source identity under explicit payload/index limits.

Successful extraction cache entries are keyed by source-relative path, source hash, output
schema, and a canonical execution fingerprint containing invocation, options, configured
extractor version, and semantics-affecting modes. Cross-path content-addressable reuse is an
explicit path-independent extractor opt-in. Cache lifecycle is independent and partitioned;
cleaning code cannot evict document cache, and collection rebuild is not the extractor-version
invalidation mechanism.

**D5 - Honest per-file convergence.** The durable state distinguishes `indexed`, stable
`policy_rejected`, `extract_retryable`, `extract_terminal`, `decode_failed`, and
`chunk_failed`. Only indexed or stable policy-rejected files are converged. Hash-only failures
do not certify successful metadata. Retryable extraction remains a service-owned convergence
obligation with bounded backoff/circuit behavior; every non-success is surfaced in structured
results, status, and dry-run where it can be determined.

Raw code uses an explicit decoder capability after code admission. Document-target binary or
legacy-encoded input reaches only its extractor. Decoder and chunk failures retain their
reason and never disappear behind an unchanged content hash.

**D6 - Separate document storage and query semantics.** Restore a dedicated document
collection, model, metadata sidecar/ledger source, store lock, and lifecycle. Document chunks
use a collection-local deterministic ID derived from normalized source path, native locator
or unit ordinal, and content fingerprint. Existing source IDs remain unchanged. Document
payloads and results use document-specific fields and labels rather than `CodeChunk` and
`codebase`.

The canonical public type is `document`; the existing `docs` alias retains its current vault
meaning and is not repurposed. Index, search, clean, status, jobs, HTTP, MCP, storage schema,
snapshot/migration, and readiness parse a closed source-type enum and branch exhaustively.
Unknown values are structured errors. `all` indexing and searching include vault, code, and
document domains and return explicit per-domain partial outcomes. Combined search defines
candidate allocation, filtering, reranking, and final top-k across all three collections.

**D7 - Epochs and restart-safe route migration.** Membership fingerprints include the source
profile version, ordered explicit routes, preprocess targets, ignore rules, and policy schema.
Content fingerprints are per kind: document extractor changes do not clean-rebuild code.
Content kind belongs in generation and checkpoint signatures, not existing source point IDs.

Recovery handles points with no sidecar and a partial collection with a stale sidecar by using
the durable generation ledger, a bounded store scan, and fresh classification. A target flip
upserts and checkpoints freshly generated destination points before deleting and checkpointing
the origin. Either phase can replay idempotently. Invalid routing refuses mutation. Publication
certifies collection completeness only after all ingestion, deletion, metadata, and schema
phases finish; an old sidecar can never certify a partial clean rebuild.

**D8 - Bounded document execution and shared authority.** Preprocessed inputs have per-rule and
profile source-byte ceilings; hashing streams instead of reading an unbounded source solely for
identity. Weighted accounting covers input bytes, emitted encoded bytes, chunks, queue items,
payloads, RSS, and CUDA. Batch groups, subprocess output, timeout, no-progress, and cancellation
are bounded and interruptible. Code and document jobs share the established index limiter,
writer authority, one GPU consumer, memory policy, and checkpoint machinery, but keep separate
pending, retry, circuit, generation, and count state. A code-only job launches no document
extractor.

The managed code profile retains its accepted numeric floor but must prove it with comparable
true source. A separately named document profile declares independent aggregate source-byte,
extracted-byte, chunk, queue, RSS, and CUDA limits. The mixed workload is not a code acceptance
fixture.

## Rationale

Explicit caller routing is the only generic boundary that preserves unconventional source,
raw documents, and extracted documents without encoding assumptions about consumer layouts.
A shared immutable policy makes admission observable and consistent, while separate storage
restores the public meaning of `code`.

This decision restores the original separation intended by preprocess-hooks while hardening
the portions of the hook contract that were not actually generic: routing fallback, ignored
options, path-unsafe cache reuse, hash-only failure convergence, and unbounded input reads.
Versioned membership and durable generation identity apply the correction to existing,
missing-sidecar, and partial indexes. Keeping checkpoint resilience independent prevents an
admission defect from weakening legitimate large-index reliability work.

## Consequences

- `code` counts, rebuilds, progress, and search results once again describe source code.
- Extracted documents remain searchable without being embedded during every code rebuild.
- Dry-run becomes a reliable preflight for real indexing behavior.
- Consumers can explicitly classify unconventional source or documents without relying on
  repository names or layouts.
- Existing preprocess configurations require an explicit migration; ambiguous rules block
  affected mutation instead of widening code or silently disappearing.
- A separate document domain increases implementation surface across storage, search,
  lifecycle, CLI, API, watcher, and service status.
- Source IDs remain stable, but adding a collection and payload contract requires storage
  schema/version and direct-consumer compatibility work.
- Admission-policy changes require resumable reconciliation and may cause a one-time rebuild
  or purge only in affected domains.
- Valid extraction caches survive unrelated index cleanup; path-dependent and option-dependent
  results no longer alias.
- Failed extraction/decode/chunk work remains visible and retryable instead of becoming a
  silent hash-only success.
- Large-index recovery remains necessary and must be validated independently for source and
  document workloads.
