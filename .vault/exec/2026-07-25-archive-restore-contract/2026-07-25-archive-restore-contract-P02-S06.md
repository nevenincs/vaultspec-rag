---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:d16ec710b488c068b55af560f0d11facaf459309fd1072cb47a97c07b94837db'
step_id: 'S06'
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
     The S06 and 2026-07-25-archive-restore-contract-plan placeholders are machine-filled by
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
     The Add the archive reader that parses a snapshot manifest and refuses an absent, unparseable, or incomplete archive whole, mutating nothing and ## Scope

- `src/vaultspec_rag/storage_ops.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the archive reader that parses a snapshot manifest and refuses an absent, unparseable, or incomplete archive whole, mutating nothing

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

Delivered as `read_archive` in `src/vaultspec_rag/storage_restore.py`. It parses the snapshot manifest and refuses the archive whole - never a partial read - on an unreadable or non-object manifest, a non-canonical prefix, a missing or non-integer schema generation, an empty or absent collection list, an unparseable completion stamp, an invalid per-collection record, a snapshot filename that is not a bare basename, a repeated collection, an invalid identity payload, and a missing or zero-length snapshot artifact.

Nothing is created and nothing is written: the reader only stats and reads.

The module lives at `storage_restore.py` rather than the `storage_ops.py` the step row names. That module was divided into `storage_survey_ops.py` and siblings before this step ran, and restore is its own responsibility rather than a survey operation.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
