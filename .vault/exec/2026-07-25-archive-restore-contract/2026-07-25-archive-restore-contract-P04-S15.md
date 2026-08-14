---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:446d0b9e5ecfe71cf4e08e81215e1d542fd5e11d62882831effd0124e0f60166'
step_id: 'S15'
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
     The S15 and 2026-07-25-archive-restore-contract-plan placeholders are machine-filled by
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
     The Add the restore verb to the storage command group as a thin adapter over the storage operation, carrying the group's dry-run preview, confirmation, and unreachable-server exit codes and ## Scope

- `src/vaultspec_rag/cli/_service_storage.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the restore verb to the storage command group as a thin adapter over the storage operation, carrying the group's dry-run preview, confirmation, and unreachable-server exit codes

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

Delivered as `storage_restore` in `src/vaultspec_rag/cli/_service_storage.py`, registered as `vaultspec-rag server storage restore`.

A thin adapter, as the phase requires: every refusal, the destination derivation, and the provenance carry stay in the storage operation. The verb supplies only what the group already owns - the dry-run preview, the `--yes` confirmation with `--json` requiring it, and the exit-3 unreachable-server path through the shared `_run_storage_op`.

It adds one check of its own: a missing archive directory exits 2 with `archive_not_found` before any client opens, so an operator typo is answered as a typo rather than as a service-health question.

Exit codes: 0 on `restored` and on an explicit `--dry-run` preview; 1 on any refusal and on an unrequested preview, since neither achieved the requested state; 2 on a missing archive and on `--json` without `--yes`; 3 when the server is unreachable.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
