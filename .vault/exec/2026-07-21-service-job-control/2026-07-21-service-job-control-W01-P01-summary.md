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

# `service-job-control` `W01.P01` summary

The cooperative run-control contract and its bounded service configuration are complete and
verified against imported production behavior.

- Created: `src/vaultspec_rag/job_control.py`
- Modified: `src/vaultspec_rag/config.py`
- Created: `src/vaultspec_rag/tests/test_job_control_unit.py`

## Description

`RunControlToken` now provides thread-safe pause, resume, cancellation, checkpoints, and
protected spans with explicit delivered-signal semantics. `NullRunControl` keeps existing
callers compatible. The service exposes validated bounds for nonterminal admission and
cooperative shutdown timing, including both environment and public override resolution.

Focused real-thread tests cover protected work, reversible pending pauses, absorbing
cancellation, signal delivery, exception preservation, and invalid configuration values.
Ruff, ty, BasedPyright, and the phase unit suite pass.
