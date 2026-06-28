---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S14'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-schema-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S14 and 2026-06-27-storage-schema-contract-plan placeholders are machine-filled by
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
     The Add server-route tests asserting the schema descriptor on /readiness and the version echo on /health and /service-state and ## Scope

- `src/vaultspec_rag/tests/test_server_routes.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add server-route tests asserting the schema descriptor on /readiness and the version echo on /health and /service-state

## Scope

- `src/vaultspec_rag/tests/test_server_routes.py`

## Description

- Authored `test_server_routes.py` (unit) with three classes: readiness carries the schema descriptor (and version matches the constant, and round-trips through JSON), `/health` echoes `schema_version` via a Starlette `TestClient`, and `get_service_state` echoes `schema_version` under temp-isolated managed-singleton paths.
- Isolated `VAULTSPEC_RAG_STATUS_DIR` and `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` to a temp dir in the service-state test per the managed-singleton-paths isolation rule, restoring env in `finally`.

## Outcome

5 exposure tests pass; all three runtime surfaces are regression-guarded in the CI unit gate. basedpyright clean.

## Notes

Dropped the unneeded Starlette `lifespan` from the `/health` test app (it caused a lifespan-type mismatch under basedpyright and is not required for the handler).
