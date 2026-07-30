---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
step_id: 'S26'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-quiesce with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S26 and 2026-07-24-service-quiesce-plan placeholders are machine-filled by
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
     The Expose the service-owned quiesce block through existing MCP service-state delegation without adding public lifecycle mutation tools and ## Scope

- `src/vaultspec_rag/mcp/_tools.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Expose the service-owned quiesce block through existing MCP service-state delegation without adding public lifecycle mutation tools

## Scope

- `src/vaultspec_rag/mcp/_tools.py`

## Description

Return the existing service-state response directly through MCP so the
controller-owned quiesce block is observed without adapter reconstruction or
lifecycle interpretation.

## Outcome

Accepted for S26 from `866f399c`. The MCP status tool returns the same mapping
as the authenticated production service-state route. Its checked-in
fresh-interpreter probe compares the direct and MCP documents exactly and
confirms that neither path imports a model, Torch, or Qdrant dependency.

## Notes

No lifecycle mutation tool was added. This reconciliation inspected the
checked-in CPU-only probe but did not execute it or start a service.
