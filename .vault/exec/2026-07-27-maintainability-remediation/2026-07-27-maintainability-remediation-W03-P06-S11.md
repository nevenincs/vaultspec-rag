---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:2ee9f8e525da7abac79fcf557f161b8617cd6f18f0cd1832716bc1a33619c094'
step_id: 'S11'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace maintainability-remediation with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S11 and 2026-07-27-maintainability-remediation-plan placeholders are machine-filled by
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
     The Split service-job collection, CLI, HTTP control, and resilience scenarios and ## Scope

- `src/vaultspec_rag/tests/integration/test_service_jobs.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Split service-job collection, CLI, HTTP control, and resilience scenarios

## Scope

- `src/vaultspec_rag/tests/integration/test_service_jobs.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

Delivered. `test_service_jobs.py` no longer exists. All four domains the step names have their own modules, with two shared support modules:

- collection contracts: `test_service_jobs_routes_collection.py`, `test_service_jobs_progress.py`
- CLI presentation and watch: `test_service_jobs_cli_basics.py`, `_cli_detail.py`, `_cli_feed.py`, `_cli_filters.py`
- HTTP control: `test_service_jobs_routes_auth.py`, `_routes_controls.py`, `_routes_mutations.py`
- resilience parity: `test_service_jobs_resilience.py`
- MCP surface: `test_service_jobs_mcp.py`
- support: `_service_jobs_support.py`, `_service_jobs_route_helpers.py`

Thirteen modules, 90 to 411 lines, MI 21.64 to 58.82. None at the floor, none near the module ceiling.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
