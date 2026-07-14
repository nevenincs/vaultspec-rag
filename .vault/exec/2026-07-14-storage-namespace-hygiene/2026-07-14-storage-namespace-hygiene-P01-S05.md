---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S05'
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
     The S05 and 2026-07-14-storage-namespace-hygiene-plan placeholders are machine-filled by
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
     The Pass a --fresh flag through the CLI survey verb and the transport query builder in serviceclient/\_transport.py and ## Scope

- `src/vaultspec_rag/cli/_service_storage.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Pass a --fresh flag through the CLI survey verb and the transport query builder in serviceclient/\_transport.py

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

- Add `fresh` to `_STORAGE_SURVEY_PARAMS` in `src/vaultspec_rag/serviceclient/_transport.py` so the admin route builder forwards it
- Add `--fresh` to `server storage survey` and pass it through `_survey_from_service` (`src/vaultspec_rag/cli/_service_storage.py`)

## Outcome

CLI, MCP, and HTTP consumers share one freshness semantic through the same transport. Commit 7ae79ca.

## Notes

The CLI-direct fallback always computes live, so `--fresh` only needs to reach the service path.
