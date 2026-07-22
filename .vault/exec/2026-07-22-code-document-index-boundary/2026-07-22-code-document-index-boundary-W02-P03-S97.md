---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S97'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace code-document-index-boundary with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S97 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Include document collections and metadata in snapshot manifests and ## Scope

- `src/vaultspec_rag/storage_manifest.py`
- `src/vaultspec_rag/storage_ops.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Include document collections and metadata in snapshot manifests

## Scope

- `src/vaultspec_rag/storage_manifest.py`
- `src/vaultspec_rag/storage_ops.py`

## Description

- Define a deterministic namespace snapshot manifest contract.
- Record every archived collection, point count, schema version, and artifact.
- Preserve the independent document metadata sidecar beside the snapshots.

## Outcome

Completed archives now contain enough explicit collection and metadata evidence
to restore the document domain without repository-layout assumptions.

## Notes

Static lint and type checks passed. Real-server archive behavior is verified in S122.
