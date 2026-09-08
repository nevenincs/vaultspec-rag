---
tags:
  - '#adr'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:7641e756df0c2c3524df50b67433d761823bd219890d66ddb5788d50e4270f56'
related:
  - "[[2026-09-08-incremental-publication-cost-research]]"
  - "[[2026-09-08-incremental-publication-cost-reference]]"
  - "[[2026-09-07-explicit-reindex-authority-adr]]"
  - "[[2026-07-25-non-destructive-index-publication-adr]]"
  - "[[2026-09-01-generation-accounting-adr]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
---

# `incremental-publication-cost` adr: `publish exact completeness proofs from committed deltas` | (**status:** `accepted`)

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
- Live readers can straddle that transaction gap, so publication also needs a stable
  revision fence that fails closed while mutation intent is open.
- The accepted explicit-reindex and pointer-last generation boundaries remain stable.
- Code, document, and vault share proof invariants but retain distinct source semantics.
- Old persisted formats are not proof or rebuild inputs. A rebuild reads current source and
  writes fresh target storage; it never decodes, migrates, seeds, or translates old evidence.
- A reader-first hard cutover may make an old index unavailable until rebuild; that typed,
  explicit failure is preferable to a fallback or second authority.
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

**Stage compatibility readers, dual-write sidecars, or seed proof from old evidence.**
Rejected. Each option preserves two interpretations of completeness, obscures which store
is authoritative during transition, and lets an old persisted format influence current
proof. The cutover instead fails old indexes closed until an explicitly authorized rebuild.

**Treat every publication as an authoritative backend scan.** Rejected for normal work and
retained as the exceptional verification path.

## Constraints

- A stable compatibility key includes source kind, root, backend, collection, storage and
  payload schema, embedding or chunking schema, and membership, content, and policy
  identity. Publication generation identifies provenance and is not part of compatibility.
- One bounded current proof projection exists per source, root, backend, and collection.
  Normal reads never traverse an unbounded generation or delta chain.
- The canonical manifest is normalized durable state. Each indexed identity carries its
  content identity and exact retained point identities or an equivalently exact relation.
- Aggregate breadth includes exact point or chunk count and exact distinct indexed identity
  count.
- Each delta names its expected parent revision and complete old-to-new outcomes. Parent or
  old-evidence mismatch fails closed.
- Add, modify, delete, rename, empty, ignored, rejected, and no-op use one delta algebra.
  Modify requires changed evidence, rename is atomic remove-plus-add, and no-op changes no
  storage, proof rows, aggregate, or revision.
- An active generation reads the canonical committed proof projection plus sparse run-local
  overrides and deletion tombstones. Run-local file states are operational checkpoint
  outcomes, never a second manifest authority. Proof commit folds changed heads and
  aggregates atomically; historical generation file states are not a lookup structure.
- Effective path and candidate membership reads are bounded and receipt-bound. They validate
  the active generation, exact proof identity, parent revision, reservation sequence, and
  direct proof parent and return state plus retained membership from one ledger snapshot.
  Destructive callers never compose that authority from separate reads.
- A local override and tombstone for one path cannot coexist. A local outcome shadows the
  committed head, a confirmed deletion tombstone hides it, and an untouched path reads the
  canonical head. Missing, malformed, or mismatched proof is refusal, never an empty set that
  authorizes deletion.
- Proof never leads storage. Reserve a parent-to-target revision before the first mutation;
  prepare each bounded mutation unit before its store call, confirm it after acknowledgement,
  seal complete path outcomes before destructive reconciliation, and commit only when every
  required unit is confirmed.
- Any open receipt makes the current proof uncertifiable for live reads. Readers acquire a
  token containing the revision and absence of an open receipt, query storage, then validate
  the same token. Change yields a typed transient or unverifiable result or a bounded retry.
- Async backend writes are confirmed only after their ingest barrier. Recovery replays a
  deterministic unit or performs an exact authorized rollback; changed source bytes cannot
  silently alter the reserved delta.
- Replacement proof commits before the served pointer moves; failure leaves the previous
  generation served.
- Backend mismatch, missing ancestry, incompatible policy or schema, corrupt receipts,
  pre-proof persisted state, and unexplained drift cannot manufacture proof.
- Only persisted explicit rebuild or audit authority may perform full identity and payload
  work. Audit verification checks an existing canonical proof and never seeds or repairs a
  missing one. Recovery may finish or roll back recorded units but does not silently acquire
  full-scan authority.
- Cheap serve-time integrity may compare an O(1) backend count with the proof aggregate and
  must check pending receipts. Equal-cardinality substitution remains unverifiable until an
  authorized exact verification.
- Existing explicit-reindex authority, non-destructive publication, generation accounting,
  and source isolation decisions remain stable; this record refines rather than supersedes
  them.
- Canonical proof is the only publication reader and writer authority after cutover.
  There is no runtime mode selector, fallback reader, sidecar translation, dual write,
  compatibility alias, deprecated re-export, or migration or seeding path.
- Reader cutover is direct and precedes producer cutover. Missing or old-format proof fails
  with a typed rebuild-required result until an explicitly authorized rebuild writes a fresh
  current-format proof. Once all consumers are direct, producers switch and obsolete
  sidecar code is deleted rather than retained dormant.
- Reader-first and producer-second are implementation order inside one unreleased change.
  No build is released or deployed between them; the release boundary includes every source
  producer, every consumer, and deletion of sidecar and compatibility code.
- Ledger initialization creates the schema only for an empty database or opens the exact
  current schema. Any nonempty older or differently shaped ledger is left untouched and
  fails with a typed rebuild-required result.
- Current proof generations, referenced evidence owners, and open-receipt generations are
  retained. Eligible closed receipt history is bounded before generation deletion; file-state
  ancestry is not a retention reason.
  Cleanup removes proof state before its collection, while archive and restore carry a
  consistent proof export.
- Code, document, and vault use one source-neutral publication coordinator with
  source-specific adapters. Vault gains the same durable receipt and generation lifecycle.
- Scoped routing reconciliation touches only affected identities, and scoped stat evidence
  updates only changed keys. Full route sweeps and complete evidence rewrites require
  explicit authority.
- Fault-injection and architectural guard tests demonstrate their intended failure before
  restoration.

## Implementation

Introduce one source-neutral publication coordinator backed by the durable ledger. It owns
the stable compatibility key, bounded current proof rows, exact retained-point relations,
aggregates, revision tokens, provenance, and streaming mutation receipts. Code, document,
and vault adapters translate their outcomes into the shared contract while retaining their
classification and payload rules.

For each affected identity, validate the authoritative old head and derive aggregate changes
by subtracting old point membership and adding new point membership. During an active run,
sparse run-local overrides and tombstones shadow canonical committed proof. Commit changed
current heads, aggregates, revision, and provenance in one ledger transaction; never copy a
complete parent manifest, consult ancestor `file_states`, or retain recursive ancestry on
the normal read path.

Create the new ledger schema only for an empty database and require its exact version and
shape thereafter. Do not alter old ledgers in place, decode old signature shapes, read old
sidecars, or expose compatibility statuses and aliases. An old or incomplete format yields
the same typed rebuild-required boundary used for missing proof, and the rebuild constructs
new evidence from current source plus fresh target acknowledgements under explicit authority.

Before external mutation, durably reserve the parent and target revisions. Streaming writers
prepare each deterministic mutation unit with its path, content, and point identities before
the store call, then confirm it after acknowledgement and ingest barriers. Seal the complete
delta before stale deletion. Once all units are confirmed, commit proof changes and close the
receipt in one transaction. Advance generation state afterward; replacement still moves the
served pointer last.

Recovery resumes from receipt and unit state: replay prepared deterministic units, confirm
acknowledged units, commit a sealed fully confirmed proof, or perform an exact authorized
rollback. Refuse a receipt bound to another compatibility key or parent revision. Retain open
receipts and evidence owners through compaction, and prune committed history by a bounded
policy only after no exposed proof references it.

Fence live reads around backend access. A reader first verifies no open receipt and captures
the current revision, reads storage, and then validates both conditions again. It retries
within a bounded policy or returns typed transient or unverifiable state on change; it never
accepts mixed proof and storage generations.

Keep authoritative verification as a separate operation and cost class. It scans backend
point identities and source payloads, compares them with canonical evidence, and detects
missing, extra, foreign, incompatible, or partial state. Verification never establishes
ancestry where none exists; only successful explicitly authorized rebuild publication
creates a fresh proof.

Make rebuild admission operational, then move proof consumers directly before removing old
publication writes, including breadth, integrity, donor selection, generation and storage
surveys, reclamation, archive, restore, and cleanup. Consumers never fall back when proof is
absent. After all readers are canonical, switch code, document, and vault producers and
delete their old sidecar implementation and exports in the same source cutover. Route
reconciliation and stat evidence use changed-key operations during scoped work; their
full-corpus forms remain explicit-authority operations.

Report changed identities, proof rows, and backend point operations plus data-apply,
proof-commit, pointer-publication, and writer-lease timings. Full verification additionally
reports its scanned breadth and elapsed cost.

## Rationale

Normalized current heads plus exact delta arithmetic are the only evaluated combination that
retains complete hash and point-membership semantics without rediscovering, recursively
reading, or rewriting unchanged state. Streaming receipts and reader revision fences convert
the storage/ledger transaction gap into a replayable and observable state machine rather than
an ordering assumption; a reader cannot mistake an intermediate store image for certified
publication.

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
- The ledger becomes the sole authoritative proof store; full sidecar readers, writers,
  models, and exports are removed.
- Existing old-format indexes require an explicit rebuild and are never upgraded or seeded
  from their ledgers or sidecars.
- Cheap publication does not claim to detect arbitrary same-cardinality out-of-band backend
  substitution; exceptional verification remains necessary.
- Full verification stays expensive and operator-authorized, with separately visible cost.
- Shared proof machinery removes duplicate publication behavior while source-scoped adapters
  prevent cross-domain state leakage.
- Operation-count guards can deterministically reject reintroduced full scans, copies, and
  serialization; large-index time budgets cover writer-lease impact.
