---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S10'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-namespace-hygiene with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S10 and 2026-07-14-storage-namespace-hygiene-plan placeholders are machine-filled by
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
     The Document delete --root harness-teardown recipe and the survey freshness semantics across docs/cli.md and docs/storage-maintenance.md and ## Scope

- `docs/cli.md` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Document delete --root harness-teardown recipe and the survey freshness semantics across docs/cli.md and docs/storage-maintenance.md

## Scope

- `docs/cli.md`

## Description

- Document the snapshot cache, `computed_at`/`source` metadata, eventual consistency, and `--fresh`/`?fresh=true` in `docs/storage-maintenance.md` and the `server storage survey` reference in `docs/cli.md`
- Document `--root` addressing, the `already_absent` idempotent success, and the harness-teardown recipe in both files; extend the delete exit-code table

## Outcome

The docs describe the shipped behavior of both phases, including the reply the dashboard team needs (HTTP stays read-only; `delete --root --json` is the sanctioned teardown). Commit 7ae79ca.

## Notes

None.
