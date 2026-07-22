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

# `service-job-control` `W02.P06` summary

Canonical indexing attempts now own and truthfully release their complete
execution lifecycle through the service-domain manager.

- Modified: `src/vaultspec_rag/jobs.py`
- Modified: `src/vaultspec_rag/job_manager.py`
- Created: `.vault/audit/2026-07-22-service-job-control-s16-dispatch-audit.md`

## Description

The compatibility entry points create canonical vault and code jobs, project the
same exact IDs into the legacy activity view, bind production runners, and let
`JobManager` own task, thread, token, limiter, lease, writer, and pipeline
lifetimes. Progress and completion flow back through exact-attempt checks while
public model and manager identities remain stable and imports remain one-way.

Pause and cancellation persist intent before signalling, acknowledge only after
physical release, and never let control mask a real application error. Resume
withdraws an undelivered pause only after running is durable; otherwise it queues
a non-destructive reconciliation attempt under the same logical ID. Completion
is atomic against concurrent desired-state changes, persistence failures retain
truthful cleared ownership and retry, callbacks wait for durability, and bounded
joins never cancel worker-backed tasks. Foreign-thread and foreign-loop resumes
return dispatch to the original event loop.

Focused regression gates passed 84 existing lifecycle cases and 8 static GPU and
import-boundary cases. Real direct probes also passed filesystem failure and
recovery, same-ID reconciliation, forty completion races, error precedence,
owner-loop handoff, and bounded join behavior. Independent re-review approved at
Critical 0 and High 0. One Medium follow-up remains to split the 859-line legacy
`jobs.py` facade before adding further orchestration policy.
