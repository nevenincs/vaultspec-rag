---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-quiesce with a kebab-case feature tag, e.g. #foo-bar.
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

# `service-quiesce` `W03.P06` summary

P06 is accepted from commits `0df85c2c`, `04660476`, and `9fc85828`.

- Modified: `src/vaultspec_rag/server/_routes.py`
- Modified: `src/vaultspec_rag/server/_lifespan.py`
- Modified: `src/vaultspec_rag/api.py`
- Modified: `src/vaultspec_rag/tests/test_service_quiesce_routes.py`
- Created: `src/vaultspec_rag/tests/test_quiesce_state_projections.py`
- Created: `src/vaultspec_rag/tests/test_jobs_quiesce_projection.py`

## Description

Authenticated pause and resume now expose one retryable service-owned failure
shape and one achieved shape. Health, jobs, and service-state project the same
twelve-field controller envelope directly from the registry. The checked-in
route proof uses a real persistence writer and filesystem failure to show
closed warming after an unpublished recovery write, followed by a repaired
same-ID attempt and exactly one recovered generation.

This summary closes only P06. P07 adapter acceptance remains incomplete because
S24 does not yet validate that `ok: true` also carries the requested achieved
controller state. S26 through S28 were correctly held until this authoritative
route vocabulary was accepted; they are now eligible as P07 work alongside the
S24 remediation. No W04 borrower work is authorized by this phase.

Acceptance was static. No service process, RAG endpoint, CUDA allocation, GPU
test, CPU test, negative mutation, lint, or type-check gate was run.
