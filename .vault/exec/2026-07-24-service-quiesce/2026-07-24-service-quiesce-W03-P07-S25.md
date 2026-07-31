---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
step_id: 'S25'
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
     The S25 and 2026-07-24-service-quiesce-plan placeholders are machine-filled by
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
     The Hard-refuse in-process GPU indexing whenever delegation does not succeed and render truthful human and JSON remediation, because neither --allow-fallback nor a quiesced service block authorizes local compute until verified borrower-lease evidence exists and ## Scope

- `src/vaultspec_rag/cli/_index.py`
- `src/vaultspec_rag/cli/_render.py`
- `src/vaultspec_rag/tests/test_cli_index_fallback_refusal.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Hard-refuse in-process GPU indexing whenever delegation does not succeed and render truthful human and JSON remediation, because neither --allow-fallback nor a quiesced service block authorizes local compute until verified borrower-lease evidence exists

## Scope

- `src/vaultspec_rag/cli/_index.py`
- `src/vaultspec_rag/cli/_render.py`
- `src/vaultspec_rag/tests/test_cli_index_fallback_refusal.py`

## Description

Remove delegated indexing's local-compute fallback after an unreachable or
service-owned refusal. Make `--allow-fallback` incapable of authorizing that
path and render service recovery guidance without claiming borrower safety.

## Outcome

Satisfied by `4e9ef7ef` against the clarified renderer scope in `f580b43c`.
Explicit and discovered delegation failures exit non-zero, while dead-port and
quiesced-refusal probes assert that no model, store, or Torch dependency is
initialized and that human and JSON remediation remain truthful.

## Notes

This Step does not create borrower authority and does not alter an intentionally
selected no-service in-process run; W04 owns lease-gated local GPU entry. The
checked-in subprocess guards were inspected but not executed during acceptance.
