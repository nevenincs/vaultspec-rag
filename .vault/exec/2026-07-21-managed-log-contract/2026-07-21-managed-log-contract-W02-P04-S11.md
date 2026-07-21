---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S11'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace managed-log-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S11 and 2026-07-21-managed-log-contract-plan placeholders are machine-filled by
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
     The Verify authenticated live responses, bounds, filters, and source-group schema and ## Scope

- `src/vaultspec_rag/tests/integration/test_service_logs.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify authenticated live responses, bounds, filters, and source-group schema

## Scope

- `src/vaultspec_rag/tests/integration/test_service_logs.py`

## Description

- Exercise authenticated ASGI and live Uvicorn requests for plaintext and JSON logs.
- Assert source groups, filters, bounds, malformed-source errors, and transport error preservation.

## Outcome

Integration coverage proves live server and transport parity for the managed-log contract.

## Notes

Tests use real routes, files, sockets, and transport calls.
