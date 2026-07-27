---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S02'
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
     The S02 and 2026-07-25-archive-restore-contract-plan placeholders are machine-filled by
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
     The Stamp an archive's own completion timestamp into its snapshot manifest so retention has an age that belongs to the archive and ## Scope

- `src/vaultspec_rag/storage_manifest.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Stamp an archive's own completion timestamp into its snapshot manifest so retention has an age that belongs to the archive

## Scope

- `src/vaultspec_rag/storage_manifest.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

- Stamp `completed_at` at snapshot-manifest publication with an aware UTC instant.
- Assert the emitted stamp is UTC and falls inside the real write interval despite an adjacent copied metadata artifact carrying a 31-day-old mtime.
- Mutation-prove the guard by renaming the output key and by backdating the written timestamp; each focused assertion failed for its intended reason, then passed after restoration.

## Outcome

`test_storage_manifest.py` passed 19 tests. Focused format, lint, and type checks passed. The broader storage pair was interrupted by an unrelated shared-WIP `IndentationError` in `job_manager/_persistence.py` while importing the job registry.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

The timestamp is stamped after snapshot artifacts have been moved and immediately before the atomic manifest write, so it cannot inherit copied metadata's source modification time.
