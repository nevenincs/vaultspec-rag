---
tags:
  - '#exec'
  - '#service-release-compat'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S01'
related:
  - "[[2026-07-25-service-release-compat-plan]]"
---

# Add the shared release-compatibility module owning the verdict type, the wire field name, and the cached local-release lookup

## Scope

- `src/vaultspec_rag/serviceclient/_release.py`

## Description

- Add `src/vaultspec_rag/serviceclient/_release.py` in the import-light client layer,
  which both the CLI fast path and the MCP stdio shell already depend on, so no entry
  point owns or duplicates the verdict.
- Declare the three-value verdict vocabulary and the single wire field name, keeping the
  latter distinct from the two version-shaped fields already travelling those surfaces.
- Expose the frozen verdict type carrying both releases, the comparison, and the payload
  readers.
- Resolve the local release lazily and cache it, since reading installed package metadata
  is the dominant cost of importing this package and every spawn worker re-imports the
  chain.
- Re-export the surface from the client package so adapters import one name.

## Outcome

The module is the single home for the contract. The comparison accepts an explicit client
release, which is what lets the tests exercise every verdict without mutating process
state or stubbing the metadata lookup.

A non-string or empty service release resolves to the unknown verdict rather than a
mismatch: the distinction that matters to an operator is "confirmed different" against
"could not be confirmed", and collapsing the two would report a garbled field in the same
words as a genuine skew.

## Notes

The first draft cached the release in a module global, which needed a lint suppression for
the `global` statement. Replaced with a cached nullary function, which expresses the same
one-time resolution with no suppression - the rule against silencing a linter rather than
fixing its cause applied directly.

A prior search of the tree confirmed no existing cross-process package-version comparison
to reuse or duplicate: the only version comparisons present are the pinned Qdrant binary
string, the storage-schema integers, and the watcher retry marker's schema rejection. The
last of those supplied the reject-an-unknown-schema idiom reused in the next step.
