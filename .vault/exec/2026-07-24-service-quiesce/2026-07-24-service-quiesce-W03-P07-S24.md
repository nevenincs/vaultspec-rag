---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
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

Not accepted yet. `0e7cce89` correctly makes pause and resume accept only
`quiesced` and `running`, respectively, after decoding the route envelope. The
checked-in real loopback route cases cover achieved transitions, idempotent
transitions, a real transition conflict, and absence of discovery.

## Notes

The successful wrong-state envelope is not emitted by the current truthful
route. The added in-memory source-rewrite and AST inspection is a forbidden
source-mutation analogue and non-behavior proof, even though it does not write
the source file. Remove it before accepting this Step. The exact-state condition
then remains static, unexercised defense-in-depth under the amended W03 rule;
do not manufacture a response to prove it. This reconciliation did not run
tests or start a service.
