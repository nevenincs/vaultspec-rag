---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S24'
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
     The S24 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
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
     The Cover the local sidecar round-trip and confirm a local root records no manifest entry and ## Scope

- `src/vaultspec_rag/tests/test_storage_identity.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Cover the local sidecar round-trip and confirm a local root records no manifest entry

## Scope

- `src/vaultspec_rag/tests/test_storage_identity.py`

## Description

Covered the local sidecar round-trip, the sibling-preserving merge, and the
negative assertion that a local root stays out of the manifest.

## Outcome

Three tests in the shared identity module, all proved to fail against their
named mutations - see the table in the `S05` record, which carries the proofs
for every guard this Phase added rather than splitting them across two
records.

The absent-evidence test asserts two distinct things that are easy to conflate:
that an unwritten sidecar reads as `None`, and that a partial payload also reads
as `None` rather than being completed with defaults. The second is the one that
matters - defaulting a missing field is how absent provenance would quietly
become a passing verdict.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
