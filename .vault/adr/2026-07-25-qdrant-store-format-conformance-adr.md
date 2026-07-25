---
tags:
  - '#adr'
  - '#qdrant-store-format-conformance'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - "[[2026-06-30-qdrant-store-resilience-adr]]"
  - "[[2026-07-25-storage-conformance-adr]]"
---

# `qdrant-store-format-conformance` adr: `refuse to quarantine on an unproven store format` | (**status:** `accepted`)

## Problem Statement

The auto-quarantine recovery accepted in `2026-06-30-qdrant-store-resilience-adr`
attributes a failed supervised start to a single collection whenever the captured
panic tail names a real on-disk collection beside a load-failure marker. A Qdrant
server binary whose on-disk format the store predates aborts with exactly that
shape: it names the collection it choked on first. The recovery therefore
misdiagnoses one whole-store incompatibility as up to three separate
per-collection corruptions, moves three healthy indexes out of the load set, and

- because the retry loop is bounded rather than fatal - can still bring the
  daemon up. `/readyz` answers, the health payload reports ready, and the only
  trace is a warning in the daemon log. The affected roots return nothing.

Nothing today can tell the two apart. The pinned server version is coupled to the
locked client's minor line, which is a wire-API guard and says nothing about
on-disk format compatibility. No version is recorded inside the storage directory
at all: the identity sidecar is a sibling of that directory, describes the
running process rather than the data, and is written only after the store is
already open and serving. The pre-spawn decision reaches its version-aware gate
only when a managed server is already listening - which is never the case
immediately after a binary change, the exact moment the misdiagnosis fires.

`2026-07-25-storage-conformance-adr` closes the model-and-geometry half of this
question and explicitly leaves the binary-against-on-disk-format half to its own
record. This is that record.

## Considerations

- The recovery's own governing condition (QR4 in
  `2026-06-30-qdrant-store-resilience-adr`) already says a false-positive
  quarantine is worse than a loud, accurate failure. The defect is not that the
  condition is wrong; it is that the detector has no input capable of
  distinguishing the two causes.
- Qdrant's panic text is version-dependent and not a stable contract, so no
  additional marker or message parsing can supply that input.
- Every store in existence today predates any such record, so whatever is
  adopted has to be safe on its very first encounter with an unstamped store.
- `2026-07-25-storage-conformance-adr` settled the vocabulary for evidence that
  is absent rather than contrary: unverifiable is a third verdict, never a pass
  and never a service failure.
- The health surface already has exactly one place where live degradation is
  authored, and one registry pairing a reason with the verb that inspects it. A
  second renderer is the thing to avoid, not a missing channel.

## Considered options

**Widen or narrow the panic-text matcher.** Rejected: the message format is
version-dependent by the prior record's own finding, so any discrimination built
on it fails on precisely the version transitions this decision exists to survive.

**Pin the storage format to the client-coupled server version and refuse any
change.** Rejected: the coupling is a wire-API guard. Refusing every patch bump
would brick routine upgrades to buy a compatibility guarantee the pin never made.

**Compare against the identity sidecar.** Rejected: it is a sibling of the
storage directory and describes the process, not the data. A store that was
moved, copied, or restored carries no sidecar of its own, and the record is
written after the open it would have to gate.

**Record the server version inside the storage directory and gate the recovery
on it (chosen).** The store carries its own evidence, so the comparison is
available before anything is spawned and survives the store being relocated.

**Refuse to start on any recorded-version change.** Rejected as the primary
behaviour: Qdrant does carry stores forward across versions, so refusing outright
converts a legitimate upgrade into an outage. Refusal is the right outcome only
once the new binary has actually failed to open the store.

## Constraints

- The runtime package is stdlib-only by design because the CLI imports it at
  startup, so the record and its comparison may not reach for the client, torch,
  or the conformance machinery in the store layer.
- The record must live where no collection enumeration can mistake it for a
  collection, and where the server itself ignores it.
- An operator-supplied or PATH-resolved binary carries no verified version, so
  the design must have an honest answer for a comparison it cannot make.
- Recording must not be able to fail a start: a store that cannot be stamped is
  merely unverifiable, and unverifiable already withholds the only thing at risk.

## Implementation

A store-format record is written inside the storage directory, naming the server
version that opened it. It is written only once the server has answered ready, so
the recorded version provably read the on-disk format, and an unknown version is
never recorded - an empty stamp would read back as no record and a placeholder
one would assert a match that was never proven. Reading is total: absent,
unreadable, and malformed all mean no record.

Before the child is spawned, the recorded version is judged against the version
about to run, yielding one of four verdicts. A match means this exact binary
wrote this store. A skew means it did not. Unverifiable covers both an unstamped
store and a binary carrying no known version. Migrated is the post-open
relabelling of a skew whose store then opened successfully.

Only a match earns the recovery. Under every other verdict a panic naming a
collection is equally explained by the whole store being unreadable, so the start
fails loudly with a message naming both versions, stating that the collection is
deliberately not being quarantined, and pairing the manual quarantine verb for a
genuinely corrupt collection. The liveness guard, the abstention on an unnamed
fault, and the per-start bound are all unchanged; the format verdict is an
additional gate in front of them, never a replacement.

The supervisor carries the verdict and the list of collections it moved on its
runtime-state snapshot, which the health payload already publishes. The single
health author turns both into degradation reasons - a quarantine, and a store
carried across a version change - and two entries in the existing remediation
registry pair each reason with the verb that inspects it. Unverifiable authors
nothing, because every store predating the record is unverifiable and reporting
them all as permanently degraded would be noise no operator could act on.

## Rationale

The knockout criterion is that this is the only option that supplies the
detector with an input capable of separating the two causes, and it does so
before anything is spawned rather than only when a server already happens to be
listening. The prior record already decided which way to fail when the cause is
uncertain; it simply had no way to know that it was uncertain.

Making a match the sole licence for quarantine, rather than making a skew fatal,
is what keeps a legitimate upgrade working: the store is carried forward, the
record is rewritten, and the recovery is licensed again on the next start. The
cost is that a genuinely corrupt collection in an unstamped store no longer
self-heals on the one start before that store is first stamped. That is the right
side to err on - the loud failure names the manual verb, and the alternative is
the silent loss this record exists to remove.

Riding the existing degradation author and remediation registry rather than
adding a channel follows the surfacing precedent set by
`2026-07-25-storage-conformance-adr`, and keeps one vocabulary across the CLI,
the start warnings, and the MCP surface.

## Consequences

- A binary/storage-format skew can no longer consume a healthy store one
  collection at a time. It fails loudly, naming both versions and the remedy.
- A quarantine, whatever caused it, now reaches the operator on the health and
  status surfaces instead of only the daemon log. This is a behaviour change for
  genuine single-collection corruption too: that start now reports degraded.
- A store carried across a server version change is reported once, for that
  daemon generation, because the older binary can no longer read it - a fact an
  operator needs before attempting a downgrade.
- The first start of every existing store is unverifiable, so the automatic
  recovery is withheld exactly once per store, until a successful open stamps it.
- The record travels with the data, so a copied or restored store carries an
  honest claim about what wrote it rather than inheriting the local sidecar's.
- Left open: the record proves which version wrote the store, not whether two
  versions are format-compatible. Establishing that would need an upstream
  compatibility matrix, and is deliberately out of scope here.
