---
tags:
  - '#adr'
  - '#qdrant-store-resilience'
date: '2026-06-30'
modified: '2026-06-30'
related:
  - "[[2026-06-30-qdrant-store-resilience-research]]"
---

# `qdrant-store-resilience` adr: `Detect, quarantine, and retry a corrupt collection on supervised start` | (**status:** `accepted`)

## Problem Statement

The managed Qdrant server cold-loads every collection in one shared on-disk store
before answering `/readyz`, so a single corrupt collection aborts startup and
bricks search for every project root on the machine - the blast radius is the
whole machine, not the one affected root. The supervisor already captures the
panic cause but only reports it and gives up. This ADR decides how the service
recovers so one bad collection degrades to one stale root.

## Considerations

The recovery primitive is cheap and Qdrant-independent: each collection is a
self-contained `collections/<name>/` directory, so moving the corrupt one aside
lets the restart succeed and serves every other root again; the quarantined root
re-creates its collection on its next index/search touch. The hard part is
*detection* - mapping a startup abort to the offending collection - because
Qdrant's error text is version-dependent and not a stable contract. The only
high-confidence signal is a collection name from the real on-disk set appearing
in the captured panic tail. Guessing beyond that risks quarantining a healthy
index (silent data loss until re-index), which is worse than a loud failure.

## Considered options

- **Do nothing (status quo):** report the panic, operator manually clears the
  store. Rejected: a one-root defect keeps the whole machine down with no guided
  recovery.
- **Auto-quarantine-and-retry, on by default (chosen):** on a readiness failure
  whose captured tail names an on-disk collection, quarantine that collection and
  retry under a bound; surface the panic and stop when no on-disk collection name
  is found.
- **Manual-only CLI verb:** an operator runs a quarantine command after a failed
  start. Kept as the escape hatch but not as the only path - the common single-
  corrupt case should self-heal.
- **Delete the corrupt collection:** rejected - irreversible; quarantine (move)
  preserves the files for forensics and is reversible.

## Constraints

This builds on the machine-singleton service model and the existing supervised
start (`qdrant_runtime/_supervise.py`), which already captures the child's
combined output and raises with `recent_output_tail()` on a non-ready exit. It
must respect the managed-storage isolation discipline - the storage dir is the
`VAULTSPEC_RAG_QDRANT_STORAGE_DIR` anchor, isolated to a temp path in tests - so
recovery never moves a real collection under test. It must not reintroduce a
dependency on Qdrant's exact error format: detection keys on the on-disk
collection names, not on parsing a specific message shape.

## Implementation

Recovery is expressed as the following decisions.

- **QR1 - Detection keys on the on-disk collection set, not the message format.**
  When the supervised start fails to become ready, scan the captured output tail
  for any collection name that exists on disk under `collections/` and that
  co-occurs with a failure marker (panic / abort / error / segment / load). A
  match from the real on-disk set is the culprit; no on-disk name found means
  detection abstains.

- **QR2 - Quarantine moves, never deletes.** The corrupt collection's directory
  is moved to a sibling `collections/.quarantine/<name>.<timestamp>/`. The move
  is atomic on the same filesystem, reversible, and removes the collection from
  the set Qdrant loads. The quarantined root's collection is re-created on demand
  by the existing `_ensure_collection` path on its next touch.

- **QR3 - Auto-quarantine-and-retry is on by default, bounded.** On a readiness
  failure, if QR1 identifies a culprit, quarantine it (QR2) and retry the start.
  Bound the recovery: at most a small fixed number of quarantines per recovery
  pass and a capped number of restarts, so a pathological store fails loudly
  rather than quarantining the whole store in a loop.

- **QR4 - Abstain rather than guess.** When QR1 finds no on-disk collection name
  in the tail, the system does not quarantine anything; it raises the existing
  ready-failure error carrying the panic tail and points the operator at the
  manual verb. A false-positive quarantine (dropping a healthy index) is treated
  as worse than a loud, accurate failure.

- **QR5 - Operator escape hatch.** A `server qdrant` CLI verb lists collections
  and quarantines a named one, for the case where auto-detection abstains or an
  operator wants to act deliberately. It shares the QR2 quarantine primitive.

## Rationale

The asymmetry is the whole problem: a defect scoped to one root should not deny
service to all roots. Quarantine-and-retry restores that proportionality with a
reversible, Qdrant-independent filesystem move, reusing the panic tail the
supervisor already captures. Keying detection on the on-disk collection set
rather than a parsed message shape makes it robust to Qdrant version drift, and
abstaining when uncertain protects a healthy index from a false positive - the
one outcome worse than the brick it replaces.

## Consequences

The common single-corrupt-collection failure self-heals: the service starts,
serves every healthy root, and the affected root re-indexes on its next touch.
The previously write-only diagnostic (the captured panic) becomes load-bearing
for an automated action, so its capture path now matters to correctness. A
quarantined collection is a silent loss of that one root's index until re-index,
mitigated by the loud log and the reversible move. The retry bound means a store
with many corrupt collections still fails - deliberately - rather than looping.
The `.quarantine/` directory accumulates moved collections; cleaning it is an
operator concern surfaced by the escape-hatch verb.

## Codification candidates

This decision is feature-local recovery behavior, not a cross-feature
constraint; no rule promotion. An empty codification is the expected outcome.
