---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-job-control with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- PHASE SUMMARY:
     This file rolls up every <Step Record> belonging to one Phase
     of the originating plan. Each Step (S##) in the Phase produces
     one <Step Record> in `.vault/exec/`; this summary aggregates
     them, lists modified / created files across the Phase, and
     reports verification status. -->

# `service-job-control` `W01.P18` summary

The canonical job domain is split into focused model, persistence, and manager
modules while `jobs` remains an identity-compatible legacy registry and dispatch
facade.

- Created: `src/vaultspec_rag/job_models.py`
- Created: `src/vaultspec_rag/job_persistence.py`
- Created: `src/vaultspec_rag/job_manager.py`
- Modified: `src/vaultspec_rag/jobs.py`
- Modified: `src/vaultspec_rag/tests/test_jobs_unit.py`
- Modified: `src/vaultspec_rag/tests/integration/test_jobs_registry.py`

## Description

S38 established dependency-light immutable resources, lifecycle vocabulary,
serialization, validation, work identity, and capabilities. S39 established the
strict v1 state codec and durable atomic filesystem store, including phase-aware
publication failures and narrow legacy start-paused migration. S40 moved canonical
ownership, strong runtime handles, transitions, retention, idempotency, recovery,
and dirty-persistence policy into `JobManager`.

Compatibility imports from `jobs` retain exact object identity, the legacy ring
and manager share one history bound, and manager persistence errors retain the
established logger name. Dependencies now flow from the manager to models,
persistence, configuration, and control typing without a reverse import from the
new domain modules into the compatibility facade.

Every phase review ended PASS after its High findings were resolved. Ruff, ty,
strict BasedPyright, imported-production regressions, job-control/jobs units,
real filesystem persistence tests, and all non-GPU registry integrations passed.
GPU index refresh was not repeated in S40 because the preceding phase had already
recorded the environment's existing CUDA out-of-memory condition.
