---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
body_hash: 'sha256:10fcd24b6de27573660dfdea0d1da59848a04c1380340ca7d414153ee2c9375d'
step_id: 'S24'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-quiesce with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S24 and 2026-07-24-service-quiesce-plan placeholders are machine-filled by
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
     The Render pause and resume as success only when ok is true and the canonical quiesce block carries the requested achieved state, preserving exact unsafe status, error, retryable, message, and quiesce evidence in human and JSON failures and ## Scope

- `src/vaultspec_rag/cli/_service_quiesce.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Render pause and resume as success only when ok is true and the canonical quiesce block carries the requested achieved state, preserving exact unsafe status, error, retryable, message, and quiesce evidence in human and JSON failures

## Scope

- `src/vaultspec_rag/cli/_service_quiesce.py`

## Description

Require the service-owned `ok: true` response to carry the exact achieved
canonical state before the CLI exits successfully. Preserve a complete,
structured service failure verbatim in both human and JSON output.

## Outcome

Accepted for S24 after `de91373f` removes the in-memory source rewrite and AST
inspection. `0e7cce89` makes pause and resume accept only `quiesced` and
`running`, respectively, after decoding the route envelope. The reported
CPU-only proof includes ten focused CLI and adapter tests, with the checked-in
real loopback cases covering achieved and idempotent transitions, a real
transition conflict, and absence of discovery.

## Notes

The successful wrong-state envelope is not emitted by the current truthful
route. Its exact-state condition is static, unexercised defense-in-depth under
the amended W03 rule; do not manufacture a response or inspect mutated source
to prove it. The reported focused test run started no daemon lifespan, GPU, or
Qdrant process.
