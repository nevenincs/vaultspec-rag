---
tags:
  - '#exec'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S02'
related:
  - "[[2026-07-13-control-plane-affordances-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace control-plane-affordances with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S02 and 2026-07-13-control-plane-affordances-plan placeholders are machine-filled by
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
     The Admit root into the survey transport params and thread the optional root argument through the MCP survey client and the get_storage_survey tool surface and ## Scope

- `src/vaultspec_rag/serviceclient/_transport.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Admit root into the survey transport params and thread the optional root argument through the MCP survey client and the get_storage_survey tool surface

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Description

- Admit `root` into `_STORAGE_SURVEY_PARAMS` so the `get_storage_survey`
  admin tool encodes it onto the `/storage/survey` route path.
- Add the optional `root` argument to `survey_storage` in
  `src/vaultspec_rag/mcp/_admin_client.py`, documenting that the service
  computes the prefix and callers never derive the hash.

## Outcome

Both client adapters pass the parameter through to the one route; neither
computes anything. Ruff and basedpyright clean on the touched modules.

## Notes

The MCP server's narrowed 5-tool surface does not expose the survey as a
standalone MCP tool; the `get_storage_survey` tool name lives in the
serviceclient admin resolver, which is the surface the plan row names.
