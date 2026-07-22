---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
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

# `service-job-control` `W02.P07` summary

Production-facade integration now proves indexing control acknowledgement is a
real resource boundary rather than a state-only promise.

- Modified: `src/vaultspec_rag/tests/integration/test_index_job_control.py`
- Created: `.vault/audit/2026-07-22-service-job-control-s17-execution-audit.md`

## Description

Vault and code attempts run through the public compatibility facade, canonical
manager, production registry, cached CUDA model, embedded local Qdrant, real
indexers, dedicated limiter, spawn workers, and sole code GPU consumer. Pause is
acknowledged only after task, worker, limiter, lease, writer, pipeline, process,
and consumer ownership has cleared. Resume keeps the logical job ID, creates a
fresh reconcile attempt, and converges real collection payloads and metadata.

Cancellation is absorbing and produces no later canonical progress, Qdrant
point, payload, or metadata writes after acknowledgement. A real Qdrant schema
failure remains `failed` when cancellation is pending and still releases the
complete attempt lifecycle. Test teardown follows the same safety contract: it
fails closed and refuses to close stores or reset ownership after a bounded join
failure.

All seven prior target cases, four new managed-facade cases, and ten focused
worker/GPU/registry/facade boundary regressions passed. Ruff, ty, BasedPyright,
formatting, collection, and diff hygiene passed. Independent review approved at
Critical 0 and High 0 with no remaining findings.
