---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:807c4889eae1f74f75c3401f51b6d5efaf26f9e9953e98d8218485f8a98c92a9'
step_id: 'S13'
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
     The S13 and 2026-07-27-maintainability-remediation-plan placeholders are machine-filled by
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
     The Split matching-rebuild, HTTP, MCP, and timeout diagnostics scenarios and ## Scope

- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Split matching-rebuild, HTTP, MCP, and timeout diagnostics scenarios

## Scope

- `src/vaultspec_rag/tests/integration/_service_search_diagnostics_support.py`
- `src/vaultspec_rag/tests/integration/_service_search_diagnostics_mcp.py`
- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py`
- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py`
- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

Split into the five domains the reference names:

| Module | Lines | MI | Domain |
| --- | --- | --- | --- |
| `_service_search_diagnostics_mcp.py` | 142 | 60.66 | MCP probe |
| `test_service_search_diagnostics_http.py` | 156 | 52.25 | direct HTTP route |
| `test_service_search_diagnostics_reporting.py` | 156 | 48.18 | timeout and log diagnostics |
| `_service_search_diagnostics_support.py` | 449 | 30.01 | real-service harness |
| `test_service_search_diagnostics_rebuild.py` | 794 | 16.67 | matching rebuild |

The single module was 1406 lines at MI 0.00.

The split also closed a seam defect the step did not name: `test_service_search_diagnostics_http.py` was importing four private helpers from the other test module. The harness now has its own module and both test modules import it there, so no test module reaches into another.

Helpers that cross a module boundary are public now that they do. All eight tests - the five from the split module and the three already in the HTTP module - still collect, and no assertion changed.

## Notes

The MCP probe earns its own module rather than sitting in the harness: it is the only surface that spawns a process and completes a session handshake before joining the rebuild's admission barrier, and it is the only one whose disagreement with the HTTP route would be a real defect rather than a transport detail.

The four single-search assertions are grouped by what they have in common - each drives one search against a quiet service and asserts the report it produces - rather than by the transport each happens to use.

Gates run: ruff check, ruff format, ty, and basedpyright all clean over the five modules; pytest collects all eight tests. The tests themselves were not executed - they are `subprocess_gpu` scenarios against a live service this session was asked to leave alone.
