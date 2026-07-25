---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S17'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Carry the source identity through a namespace copy instead of stamping current values onto the destination

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

Add `carry_migrated_identity` to the storage domain, and call it from the
migrate verb before the manifest re-key.

## Outcome

The hole was not the one the Step row names, and that matters for what the
guards assert. Nothing stamps current values onto a migrate destination: the
stamp fires only inside a genuine collection create, and the copy path builds
its target through the raw client, so no stamp happens at all. The destination
therefore landed with no identity and read `unverifiable`, while the source's
provenance was known and sitting in the other home.

The manifest re-key looked like it already covered this and does not. It carries
the identity map verbatim, keyed by the *source* collection names, and a migrate
remaps every name - so the record survived under a key nothing would ever look
up. That is the precise failure the carry closes, and the integration guard
asserts it against real remapped names rather than a synthetic pair.

The carry loads through the backend-dispatching accessor and records through it
too, so neither home is reached directly and the local-versus-server keying stays
in one place. Three properties are deliberate: only a `migrated` result is
carried, so a skipped or failed copy never gains provenance; an unstamped source
carries nothing rather than falling back to current values; and the returned
target list is confirmed by reading the record back, because the stamp itself is
best-effort and swallows its own failures.

Ordering is load-bearing. The carry runs before the re-key, because the re-key
rewrites the manifest entry the carry reads as its source.

## Notes

A residue the Step does not own: a server-to-local migrate leaves the old
server-keyed identity map on a now-local manifest entry. It is inert - local
reads consult the sidecar, and the survey builds from live server collection
names, which a local entry never matches - and a later migrate back overwrites
it through this same carry. Left alone rather than widened into the re-key.
