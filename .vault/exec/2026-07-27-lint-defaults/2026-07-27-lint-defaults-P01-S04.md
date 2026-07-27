---
tags:
  - '#exec'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S04'
related:
  - "[[2026-07-27-lint-defaults-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace lint-defaults with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S04 and 2026-07-27-lint-defaults-plan placeholders are machine-filled by
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
     The Remediate upstream-default complexity findings and ## Scope

- `src/vaultspec_rag/_operator_commands.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Remediate upstream-default complexity findings

## Scope

- `src/vaultspec_rag/_operator_commands.py`

## Description

- Introduce immutable `IndexCommandOptions` for optional index-command flags.
- Migrate all non-default production and guard-test callers.
- Resolve the review-found caller omission and repeat focused verification.

## Outcome

Operator remediation commands retain their exact flag ordering and values through one
cohesive options value; scoped lint, strict typing, CLI, and guard tests pass.

## Notes

The shared route module retained its unrelated in-progress refactor; only the one
operator-command call site belongs to this step.
