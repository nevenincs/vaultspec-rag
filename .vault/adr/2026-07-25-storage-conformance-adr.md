---
tags:
  - '#adr'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:fdc874a4aa97be2fb287d1db315926b8b873f6747bb8c8db262e95f46e9c808a'
related:
  - "[[2026-07-25-storage-conformance-research]]"
  - "[[2026-06-26-storage-schema-contract-adr]]"
  - "[[2026-07-24-worktree-index-reuse-adr]]"
---

# `storage-conformance` adr: `prove a collection was built by the models the code expects` | (**status:** `accepted`)

## Problem Statement

The service cannot tell whether a collection it is about to search was produced by
the models and the shape the running code expects. It publishes a conformance
descriptor, but that descriptor is derived from live configuration, so checking it
compares the configuration against itself and always passes. The one complete
comparator in the tree is unreachable from production.

The consequence, grounded in `2026-07-25-storage-conformance-research` F1, is a
class of failure the product cannot currently observe: swap the embedding model
for another of the same width and every search silently scores new-model queries
against old-model vectors. No epoch moves, no run fires, no log line appears, and
the vault index never recovers on its own. A healthy-looking service returns
confidently wrong answers.

A decision is needed now because the gap is no longer hypothetical. The worktree
reuse work wrote identical model identity into its reuse gate and could not
implement it, recording that no per-root model record exists and that creating one
was forbidden by that record's own scope (F10). That prohibition was never adopted
generally. Every later feature that wants to reason about what produced a vector
inherits the same missing fact.

## Considerations

- The comparator already exists, is tested, and needs no redesign; only its input
  is missing (F6).
- The descriptor cannot supply that input by construction - it reports config,
  never storage (F6).
- Payload indexes are already reconciled against a pre-existing collection on the
  ensure path, so reaching an existing collection to inspect and repair it is
  established practice here rather than a new liberty (F4).
- The storage manifest already persists a per-namespace record including a schema
  version, so a home for durable identity exists (F3).
- That manifest's version field is currently self-relabelling: opening a store
  rewrites a stale namespace as current, disarming the only enforcing reader (F3).
  Persisting more identity into a record that overwrites itself would inherit the
  same defect.
- Storage already has a three-way vocabulary for namespace state, including
  `unverifiable`, and the automated-destruction rule requires that an
  unattributable namespace is never acted against destructively.
- The readiness axis is the cheapest mechanical extension point but is bound by
  its own docstring to no live I/O and to not accreting into a health console
  (F8), and its exit code deliberately does not fail. Conformance needs live
  storage reads, so it does not belong there.
- Degradation is authored in exactly one place for the live service, and
  everything downstream - status, start warnings, the MCP surface - derives from
  it (F7).
- An in-flight plan owns the code indexer decomposition and the run ledger. This
  decision must not require changes inside those modules.

## Considered options

**A sentinel point inside each collection.** Identity travels with the data
through copy, archive, and restore for free. Rejected: the sentinel carries a
dense vector and would be a search candidate, so every read path would need a
filter to exclude it - a broad, invasive change to the hottest code in the
product, with a silent wrong-result failure mode of its own if one path forgets.

**Qdrant collection-level metadata.** The natural home if it existed. Rejected:
not available as a general key-value facility on the pinned server, so it would
introduce a version-coupled dependency into the very layer whose version coupling
is already an open problem.

**A new per-collection sidecar file.** Simple and independent. Rejected: it
duplicates the storage manifest, which already exists to answer "what is in this
namespace", and a second source of namespace truth would drift against the first.

**Extend the storage manifest with per-collection identity.** Chosen. Reuses the
existing durable per-namespace record, needs no new file, and puts identity where
the survey and reclamation surfaces already read.

**Refuse every non-conforming read.** Rejected as the general rule: a model swap
would brick all search until a full rebuild completed, and a rebuild is exactly
the window in which a collection is legitimately mixed. Retained for geometry
only, where the vectors cannot be scored at all.

**Report but never act.** Rejected: it reproduces the current failure with better
logging. The point of the decision is that a non-conforming index changes what the
service tells its operator.

## Constraints

- No change inside the code indexer, the run ledger, or the run checkpoint. Those
  modules are mid-refactor under an in-flight plan and a concurrent edit would
  collide. This decision is implementable entirely in the store, the manifest, the
  health author, and the status renderer.
- Verification reads live collection geometry, which is a network call in server
  mode. It must sit behind the existing per-collection ensure cache so it runs
  once per collection per store instance, never per query.
- The manifest is machine-global and shared by every root on the host. A write
  must stay atomic and must not enlarge the lock footprint.
- Local and server backends differ in whether payload indexes exist at all, so
  conformance must not assert on index presence in local mode.
- The decision authorises new persisted state, which the worktree reuse record
  declined to create within its own scope. It does not reopen that record.
- No migration engine. The governing schema decision chose clean reindex over
  in-place migration and that stands; a non-conforming namespace is rebuilt, not
  converted.

## Implementation

**D1 - Effective identity is stamped per collection at create time, in the home
that backend already uses.** When a collection is created, the store records the
identity that produced it: dense model name, sparse model name or its absence,
effective dense width, distance metric, dense and sparse vector names, and the
storage schema generation. It is keyed by collection name, because the three
collections of one namespace are indexed at different times and can genuinely
disagree about what produced them.

The record has two homes, selected by backend, because the manifest covers only
one of them. Server mode stores it in that namespace's manifest entry. Local mode
stores it in a sidecar under that root's own storage directory, which is
per-root and self-contained. This is not two sources of one truth: the manifest is
server-mode-only today and holds no local record to disagree with, so the two
homes are disjoint by construction. One accessor pair dispatches on backend, so
every caller sees a single interface and neither home is reachable directly.

The alternative - extending the manifest to record local roots - was rejected on
safety rather than tidiness. The survey classifies a namespace by matching
manifest entries against live server collections, and reclamation acts on that
classification. Local entries would match nothing, so they would present as
unattributable namespaces to a surface whose governing rule forbids exactly that.
A conformance feature must not hand the reclaimer a new class of namespace it
cannot explain.

**D2 - Verification happens on the ensure path, once per collection.** The
function every read and write already traverses gains a verification step after
the existing index reconcile. It compares the stamped identity, and the live
collection geometry read back from the backend, against what the running code
expects, and feeds the existing comparator rather than growing new comparison
logic. The result is cached with the existing ensured-collection marker.

**D3 - Three verdicts, not two.** A collection is `conforming`, `nonconforming`,
or `unverifiable`. `unverifiable` covers a namespace stamped before identity
existed, or one whose geometry could not be read. It is never treated as a
failure: it does not degrade the service, does not block a read, and never
authorises destruction. It is reported as exactly what it is - an unknown - so
that the absence of evidence is legible instead of being silently scored as pass.

**D4 - Geometry refuses; model identity degrades.** A dense width, distance, or
vector-name disagreement is refused at the ensure step with a message naming the
dimension, because such vectors cannot be scored and the current behaviour buries
the cause under a retry budget and a misattributed hybrid-search log line (F5). A
model-identity disagreement at matching geometry does not refuse: the collection
is readable, a rebuild is the remedy, and refusing would remove search for the
duration of that rebuild. It is surfaced as a degradation instead.

**D5 - The manifest stops relabelling itself.** Recording a root preserves the
stored schema generation and identity rather than overwriting them with current
values. Only creating a collection, or an explicit rebuild, restamps. Without
this, the record a verifier reads is one the act of opening the store has already
falsified.

**D6 - Namespace copy carries identity.** The migrate path that replays a source
collection's vector geometry verbatim also carries its identity record. Copying
shape while dropping provenance manufactures a namespace that claims conformance
it never established.

**D7 - A non-conforming namespace is a service degradation with a remedy.** The
verdict is authored where live-service degradation is already authored, so it
reaches status, start warnings, and the MCP surface without a second renderer, and
it is paired with its remediation command in the existing degraded-family
registry. The per-namespace verdict and stamped identity are added to the storage
survey payload, which today reports point counts and footprint but nothing about
what produced them.

**D8 - Every guard added here carries a recorded failure proof.** The feature is
entirely guards and negative assertions, which the project's guard-test rule
places under an explicit obligation: each is observed failing for its intended
reason before it is trusted, and both directions are recorded in the step record.

## Rationale

The knockout is F6. The product has a correct comparator and a descriptor that
cannot feed it, because the descriptor reads configuration and the question is
about storage. Every other option in the space either rebuilds the comparator or
adds a second source of namespace truth; extending the manifest supplies the one
missing input and changes nothing else.

Choosing the ensure path as the verification site follows the same logic. It is
already the chokepoint for correctness repair on pre-existing collections - the
payload-index reconcile lives there and reaches into collections it did not create
(F4) - so conformance is an additional check at an established seam rather than a
new interception. It is also already cached per collection, which is what keeps a
live geometry read off the query path.

The split in D4 follows the failure modes rather than a uniform policy. F5 shows a
geometry mismatch is already fatal, just slowly and with the wrong explanation;
moving that failure earlier and naming it correctly is a strict improvement with
no availability cost. F1 shows a model mismatch is not fatal to the mechanism at
all - it is fatal to the meaning of the results - and the honest remedy is a
rebuild the operator must be told to run. Refusing there would convert a
wrong-answers problem into an outage during precisely the rebuild that fixes it.

D5 is not incidental. F3 establishes that the existing version gate is disarmed by
ordinary store opens; persisting richer identity into that same record without
fixing the overwrite would produce a conformance check that certifies whatever it
last wrote.

D3 exists because the alternative is worse than it looks. A binary verdict forces
a pre-existing namespace to be scored as either passing or failing on evidence
that does not exist. Scoring it as passing reintroduces the silent failure this
record is written to remove; scoring it as failing degrades every host on first
upgrade. `unverifiable` is the accurate answer and the project already uses the
word for exactly this shape of unknown.

## Consequences

The silent case from F1 becomes observable: a model swap now produces a named
degradation with a rebuild command instead of quietly wrong rankings. The vault
index, which had no recovery path at all, gains one by the same mechanism as code
and document.

The geometry failure in F5 becomes fast and correctly attributed, which also
returns a retry budget currently spent on an error that was never transient.

The reuse gate that the worktree work could not implement becomes implementable:
the fact it needed - what model produced this namespace - now exists durably. That
record is not reopened here, but its residual gap closes as a consequence.

Honest difficulties. Every existing namespace on every developer machine becomes
`unverifiable` on first upgrade, and stays so until it is next rebuilt; the
surfaces must make that state legible without making it look like damage.
Verification adds a live geometry read per collection per store instance, which is
cheap but not free, and it is new I/O on a path that previously did none.
Stamping at create time means a namespace whose collection predates the stamp can
never be retroactively certified - only rebuilt - which is the correct outcome but
will read as friction.

Pathways opened. A durable per-namespace identity is the missing input for a real
migration path keyed on the version, which the governing schema record named and
deliberately did not build. It is also the precondition for the two adjacent links
F9 records and this decision deliberately leaves alone: client-against-daemon
release skew, and the Qdrant binary against the on-disk format, where a
version-incompatible start is currently misdiagnosed as per-collection corruption
and quarantined while the daemon reports healthy. Each needs its own record.
