---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S80'
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
     The S80 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Verify over-budget document workloads are refused at job admission before GPU work and ## Scope

- `src/vaultspec_rag/tests/integration/test_document_resource_bounds.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify over-budget document workloads are refused at job admission before GPU work

## Scope

- `src/vaultspec_rag/tests/integration/test_document_resource_bounds.py`

## Description

- Submit an over-budget document job through the production attempt runner.
- Assert typed admission refusal before registry model load or project lease.
- Assert the configured extractor and durable project state remain untouched.

## Outcome

Document queue ceilings now have direct acceptance evidence at the job boundary.
The rejected attempt loads no model, opens no project, runs no extractor, and
creates no index state.

## Notes

Scoped Ruff and Ty checks passed. The real dispatch-path integration test passed
without using a GPU.
