---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:b91a5c948a9301dce975e3a14002f644d925e8e8e8c1312e0fcb98df94cf4809'
step_id: 'S10'
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
     The S10 and 2026-07-27-maintainability-remediation-plan placeholders are machine-filled by
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
     The Split pause, cancellation, restart, watcher, and exact-ID control scenarios and ## Scope

- `src/vaultspec_rag/tests/integration/test_service_job_control_e2e.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Split pause, cancellation, restart, watcher, and exact-ID control scenarios

## Scope

- `src/vaultspec_rag/tests/integration/_service_job_control_e2e_support.py`
- `src/vaultspec_rag/tests/integration/test_service_job_control_pause_restart.py`
- `src/vaultspec_rag/tests/integration/test_service_job_control_transport_matrix.py`
- `src/vaultspec_rag/tests/integration/test_service_job_control_watcher.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

Split into the three scenario groups the reference names, over one shared runtime module:

| Module | Lines | MI |
| --- | --- | --- |
| `_service_job_control_e2e_support.py` | 157 | 68.07 |
| `test_service_job_control_transport_matrix.py` | 215 | 39.29 |
| `test_service_job_control_watcher.py` | 289 | 32.20 |
| `test_service_job_control_pause_restart.py` | 597 | 19.03 |

The single module was 1140 lines at MI 0.00.

Each scenario keeps the helpers only it drives - the watcher's coalescing and replacement exercises, the restart seeding and durable-intent assertions, the operator matrix's own loopback server. What is genuinely shared is the real registry/manager runtime fixture and the released-attempt assertion both scenario groups close on; only those moved to the support module.

The transport matrix turned out to share nothing with the other two: it drives no job manager and uses no embedding model, so its server context moved with it rather than into shared scaffolding.

No assertion text changed, no coverage moved to a fake, and all five tests collect.

## Notes

The shared fixture follows the convention the split route modules already use: an explicit `@pytest.fixture(name=...)`, alias-imported into each consumer with an `__all__` entry. Both consumers were checked to register it under `_e2e_runtime`, the name their signatures request.

The support module names the fixture in its own `__all__`. That is what keeps the unused-function diagnostic quiet - it declares the fixture as the module's surface rather than suppressing the report.

Gates run: ruff check, ruff format, ty, and basedpyright all clean over the four modules; pytest collects all five tests. The tests themselves were not executed - they need the resident service, which this session was asked to leave alone.
