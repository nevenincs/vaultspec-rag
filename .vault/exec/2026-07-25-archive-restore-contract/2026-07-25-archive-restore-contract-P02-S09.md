---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:c94afdfcff693550faa36721832da1d8086ccf71cfdde8e3d0d259aab21eff0a'
step_id: 'S09'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace archive-restore-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S09 and 2026-07-25-archive-restore-contract-plan placeholders are machine-filled by
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
     The Write the destination manifest entry from the archived per-collection identity and archived schema generation rather than current values, leaving an identity-less archive unverifiable and ## Scope

- `src/vaultspec_rag/storage_manifest.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Write the destination manifest entry from the archived per-collection identity and archived schema generation rather than current values, leaving an identity-less archive unverifiable

## Scope

- `src/vaultspec_rag/storage_manifest.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

Delivered as `record_restored_archive` in `src/vaultspec_rag/storage_manifest.py`. The destination entry is written from the archived schema generation and the archived per-collection identities, never from current process values.

An identity-less archive - which is every archive written so far - leaves the identity mapping empty rather than having one invented, so the existing survey path continues to report the namespace `unverifiable`. That is the honest answer: a restore creates no vectors and therefore knows nothing about what produced them.

Guarded by `TestRestoreCarriesArchivedProvenance` in `src/vaultspec_rag/tests/test_storage_restore.py`, both directions proved.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
