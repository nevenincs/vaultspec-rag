---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-27'
body_hash: 'sha256:f95303ff205cbb7dd4873d4b9a8045191e79af1e6eda529f69bce357ff5671e3'
step_id: 'S03'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Stamp the effective dense model, sparse model, dense width, distance, vector names, and schema generation when a collection is created

## Scope

- `src/vaultspec_rag/store.py`

## Description

Stamped the identity at collection creation, inside the lifecycle lock and
immediately after `create_collection` returns, so no other thread in the process
observes the collection before its provenance is recorded.

The width recorded is `self._embedding_dim` - the value the collection was
actually created with - not the config-derived width. The store can be
constructed with an override, and a stamp that recorded config instead would
describe a collection nobody built. This was corrected during the step after
first writing it against `current_identity()` unmodified.

## Outcome

`_stamp_identity` on the store, called from `_ensure_collection` after the
create. Dispatches on `_server_mode` and passes the local storage directory only
in local mode. Best-effort by construction: a stamp failure degrades a later
verdict to `unverifiable` and must never fail the index run that was creating
the collection.

## Notes

Template evidence: intro_commit=bb97c918472220397b2f4b63f5dfbd0549b70a78; template_commit=bb97c918472220397b2f4b63f5dfbd0549b70a78:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
