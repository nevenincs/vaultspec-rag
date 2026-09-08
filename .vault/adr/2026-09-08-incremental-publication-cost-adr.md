---
tags:
  - '#adr'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:20948d940b361eeec5f26000af5effd8cdd5d6dbc4ac9ab565a2a028e0c36beb'
related:
  - "[[2026-09-08-incremental-publication-cost-research]]"
  - "[[2026-09-08-incremental-publication-cost-reference]]"
  - "[[2026-09-07-explicit-reindex-authority-adr]]"
  - "[[2026-07-25-non-destructive-index-publication-adr]]"
  - "[[2026-09-01-generation-accounting-adr]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
---

# `incremental-publication-cost` adr: `publish exact completeness proofs from committed deltas` | (**status:** `proposed`)

## Problem Statement

Scoped indexing bounds discovery and ingestion to known changes, but publication can
still perform corpus-wide work. We need one exact completeness-proof model whose normal
publication cost is proportional to the committed delta without weakening explicit
full-reindex authority, generation-safe publication, or source isolation. The affected
paths and option space are grounded in `2026-09-08-incremental-publication-cost-research`
and `2026-09-08-incremental-publication-cost-reference`.

## Considerations

- Completeness remains an exact backend-bound claim about one published source generation.
- A cheap proof is exact only when derived from a compatible authoritative parent and
  storage-confirmed mutations; it cannot cheaply rediscover arbitrary backend corruption.
- Storage and the durable ledger lack a shared transaction, so intermediate states must
  be explicit and recoverable.
- The accepted explicit-reindex and pointer-last generation boundaries remain stable.
- Code, document, and vault share proof invariants but retain distinct source semantics.
- Deterministic operation counts are the primary proportionality gate; time budgets support
  rather than replace them.

## Considered options

**Retain full manifests and cache collection breadth.** Rejected. This leaves complete
manifest cloning and serialization and adds another invalidation and rollback contract.

**Keep sidecars authoritative and patch them incrementally.** Rejected. Portable atomic
patching is unavailable, and this leaves duplicate truth beside the ledger.

**Publish immutable full proof snapshots per generation.** Rejected for scoped work. It
copies or rewrites corpus-wide state for each small delta.

**Maintain a normalized ledger-backed proof and publish storage-confirmed deltas through
prepare, apply, and commit receipts.** Chosen. It gives every source one exact proof model,
bounds normal work by changed scope, and makes cross-store interruption recoverable.

**Treat every publication as an authoritative backend scan.** Rejected for normal work and
retained as the exceptional verification path.

## Constraints

- Proof identity includes source kind, root, backend, collection, generation, storage and
  payload schema, embedding or chunking schema, and membership, content, and policy identity.
- The canonical manifest is normalized durable state. Each indexed identity carries its
  content identity and exact retained point identities or an equivalently exact relation.
- Aggregate breadth includes exact point or chunk count and exact distinct indexed identity
  count.
- Each delta names its expected parent revision and complete old-to-new outcomes. Parent or
  old-evidence mismatch fails closed.
- Add, modify, delete, rename, empty, ignored, rejected, and no-op use one delta algebra.
  Rename is atomic remove-plus-add; no-op changes neither rows nor aggregates.
- Proof never leads storage. A prepared or partially applied publication is uncertified and
  must replay, finish, or return a typed unverifiable or rebuild-required outcome.
- Replacement proof commits before the served pointer moves; failure leaves the previous
  generation served.
- Backend mismatch, missing ancestry, incompatible policy or schema, corrupt receipts,
  inexact legacy evidence, and unexplained drift cannot manufacture proof.
- Only explicitly authorized rebuild, migration, recovery, or audit may perform full
  verification.
- Existing explicit-reindex authority, non-destructive publication, generation accounting,
  and source isolation decisions remain stable; this record refines rather than supersedes
  them.
- Legacy consumers migrate to the canonical proof reader. Publication never dual-writes an
  independently authoritative full manifest.
- Fault-injection and architectural guard tests demonstrate their intended failure before
  restoration.

## Implementation

Introduce one publication-proof owner in the durable ledger layer. It stores normalized
per-source manifest rows, exact retained-point relations, aggregate breadth, proof identity
and provenance, the published revision, and prepare/apply/commit receipts. Source adapters
translate code, document, and vault outcomes into one typed delta while retaining their
classification and payload rules.

For each affected identity, validate the authoritative old row and derive aggregate changes
by subtracting old point membership and adding new point membership. Commit normalized rows
and aggregates in one ledger transaction. Incremental generations reference unchanged parent
state without copying it into a new full manifest.

Before external mutation, durably prepare a receipt containing the parent revision, exact
delta, target identity, and deterministic mutation identities. Apply or replay storage
mutations idempotently, record storage confirmation, then commit proof changes, aggregates,
revision, provenance, and receipt status in one transaction. Advance final generation state
only afterward; explicit replacement still moves the served pointer last.

Recovery resumes from receipt state: replay unapplied or partial storage mutations, commit a
storage-confirmed proof, and advance lagging generation bookkeeping idempotently. Refuse a
receipt bound to another backend, collection, parent revision, or policy.

Keep authoritative verification as a separate operation and cost class. It scans backend
point identities and source payloads, reconstructs normalized evidence, and detects missing,
extra, foreign, incompatible, or partial state. Only successful authorized verification may
establish ancestry where none exists.

Report changed identities, proof rows, and backend point operations plus data-apply,
proof-commit, pointer-publication, and writer-lease timings. Full verification additionally
reports its scanned breadth and elapsed cost.

## Rationale

Normalized rows plus exact delta arithmetic are the only evaluated combination that retains
complete hash and point-membership semantics without rediscovering or rewriting unchanged
state. Durable receipts convert the unavoidable storage/ledger transaction gap into a
replayable state machine rather than an ordering assumption.

The design preserves established authority: incremental publication proves only authorized
mutations against evidence it can validate. Untrusted ancestry requests authoritative work
without silently acquiring permission to perform it. Rebuilds keep shadow-generation and
pointer-last publication, while source adapters retain code, document, and vault ownership.

## Consequences

- Normal scoped publication becomes proportional to affected identities and point mutations
  plus bounded fixed overhead.
- Normal publication no longer scrolls a complete collection, clones a parent manifest, or
  serializes a complete metadata map.
- Completeness gains explicit provenance distinguishing verified and delta-derived proofs.
- Receipts and normalized proof state increase ledger schema and recovery complexity.
- The ledger becomes the sole authoritative proof store; full sidecars and readers migrate
  or are removed.
- Cheap publication does not claim to detect arbitrary same-cardinality out-of-band backend
  substitution; exceptional verification remains necessary.
- Full verification stays expensive and operator-authorized, with separately visible cost.
- Shared proof machinery removes duplicate publication behavior while source-scoped adapters
  prevent cross-domain state leakage.
- Operation-count guards can deterministically reject reintroduced full scans, copies, and
  serialization; large-index time budgets cover writer-lease impact.
