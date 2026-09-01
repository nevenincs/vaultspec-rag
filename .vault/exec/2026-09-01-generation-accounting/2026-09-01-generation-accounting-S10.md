---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:c016b3dddc7630a9902cc64a47f0691bf88b06070e378f0befc46414d049decf'
step_id: 'S10'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace generation-accounting with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S10 and 2026-09-01-generation-accounting-plan placeholders are machine-filled by
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
     The Prove target-scoped code deletion never initializes the served collection and ## Scope

- `src/vaultspec_rag/tests/test_store_codebase.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Prove target-scoped code deletion never initializes the served collection

## Scope

- `src/vaultspec_rag/tests/test_store_codebase.py`

## Description

- Exercise explicit-generation code upsert and deletion through the local store.
- Assert both operations prepare only the generation collection while the served collection remains absent.

## Outcome

The regression pins table preparation to the caller-supplied build target for both
mutating operations.

## Notes

The focused integration test is fail-closed on this host: pytest exits before collection
because no ready compatible machine-pointer service is available. No binary was installed
or bypassed, so the guard-failure demonstration also remains unavailable here.
