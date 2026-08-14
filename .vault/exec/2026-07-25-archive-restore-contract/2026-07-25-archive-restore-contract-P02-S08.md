---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:f4bf1d4808363275790ac1291de991b24413b5a7633d065e279b986528359187'
step_id: 'S08'
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
     The S08 and 2026-07-25-archive-restore-contract-plan placeholders are machine-filled by
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
     The Refuse a destination holding any existing collection, a non-canonical destination prefix, and any local-mode invocation, each naming its own reason and ## Scope

- `src/vaultspec_rag/storage_ops.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Refuse a destination holding any existing collection, a non-canonical destination prefix, and any local-mode invocation, each naming its own reason

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

All three refusals are delivered in `restore_archive`, each returning its own reason and mutating nothing:

- `local_mode_unsupported` - returned before the archive is read at all, so a local-mode call against a nonexistent archive still refuses rather than raising.
- `invalid_destination_prefix` - the named root does not derive a canonical prefix.
- `destination_exists` - any collection already present under the destination prefix. There is no flag that overrides it.

A fourth refusal the step row did not anticipate is also present: `invalid_archive_collection`, for an archive naming a collection that re-keys onto the bare destination prefix.

One platform refusal is inherited rather than added here: an applied restore on Windows returns `windows_server_archive_restore_unsupported`. On this platform the applied path is therefore unreachable and only the preview and the refusals can be exercised, which is why the round trip in `P03` is the step that has to run elsewhere.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
