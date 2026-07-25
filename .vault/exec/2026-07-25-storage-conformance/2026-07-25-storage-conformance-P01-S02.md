---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S02'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-conformance with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S02 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Add the per-collection identity record type and its manifest serialization, defaulting absent identity to unknown rather than to current values and ## Scope

- `src/vaultspec_rag/storage_manifest.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the per-collection identity record type and its manifest serialization, defaulting absent identity to unknown rather than to current values

## Scope

- `src/vaultspec_rag/storage_manifest.py`

## Description

Added the per-collection identity record - dense model, sparse model or its
absence, dense width, distance, both vector names, and the storage schema
generation - together with its JSON round-trip and the manifest fields that
persist it.

The type landed in `store_schema.py` rather than in the manifest as the Step's
scope clause anticipated. The manifest must construct the type, and the
backend-dispatching accessor must import both the manifest and the type; putting
the type in the manifest makes that a cycle. `store_schema.py` is the neutral,
torch-free leaf both already depend on, so it is the only placement that keeps
the accessor importable without one. The manifest fields themselves are in the
Step's declared scope as planned.

## Outcome

`CollectionIdentity` with `to_payload` / `from_payload`, and
`ManifestEntry.collection_identity` keyed by exact collection name, persisted
and reloaded through the existing atomic write.

`from_payload` returns `None` for any malformed or incomplete payload rather
than substituting defaults. Defaulting a missing field would manufacture exactly
the provenance the type exists to prove, and would turn absent evidence into a
silent pass - the failure this feature was written to remove.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
