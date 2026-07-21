---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S11'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-job-control with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S11 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Add checkpoints around vault phases and batches while protecting collection drop through valid publication using vaultspec-high-executor and ## Scope

- `src/vaultspec_rag/indexer/_vault_indexer.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add checkpoints around vault phases and batches while protecting collection drop through valid publication using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/indexer/_vault_indexer.py`

## Description

- Add no-op-default run control to public, locked, scoped, and helper vault
  indexing seams.
- Check control at writer-lock, phase, per-file batch, storage mutation, and
  atomic metadata boundaries while balancing progress phases on every unwind.
- Forward the same token through all streaming embedding calls.
- Protect clean collection drop, replacement streaming, stale cleanup, and
  metadata publication as one indivisible cooperative-control span.
- Bound document preparation work, poll control while waiting, and cancel
  queued futures before releasing the writer lock on unwind.
- Verify static types, formatting, real control primitives, real-file parsing,
  atomic publication, and architecture invariants through independent review.

## Outcome

Vault indexing can now cooperatively unwind between safe phases and bounded
batches without changing unmanaged callers. Non-clean work remains interruptible
between convergent mutations. Clean rebuild requests are refused before collection
drop or deferred until a complete replacement and its metadata are published.

Ruff, Ruff formatting, ty, strict BasedPyright, and `git diff --check` passed.
All 18 focused production tests passed. A fresh-process production probe verified
torch-free imports, exact no-control defaults, real bounded parsing, pre-mutation
pause delivery, and deferred pause delivery after atomic metadata publication.
Independent re-review found no remaining Critical or High issues.

## Notes

The initial review found one High issue: `ThreadPoolExecutor` context shutdown
would have drained a corpus-sized queued parse set after control delivery. The
revision caps in-flight work at twice the worker count, polls every 100 ms,
cancels pending futures on unwind, and waits only for already-running tasks.

Semantic discovery reported no indexed source sections, so full-file inspection
and targeted source search grounded the change. The recorded CUDA OOM refresh was
not retried; real streaming/rebuild interruption coverage remains assigned to S12.
