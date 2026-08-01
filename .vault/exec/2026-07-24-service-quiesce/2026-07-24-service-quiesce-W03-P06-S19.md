---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
body_hash: 'sha256:103fc1ca61b9704b5f6b42eb30a01f98f548036e7a2cba1ebb634a81ff0c43d8'
step_id: 'S19'
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
     The S19 and 2026-07-24-service-quiesce-plan placeholders are machine-filled by
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
     The Map typed resume recovery failure to the canonical authenticated retryable lifecycle envelope while warming admission remains closed, and return a repaired retry as running without changing the logical job identity and ## Scope

- `src/vaultspec_rag/server/_routes.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Map typed resume recovery failure to the canonical authenticated retryable lifecycle envelope while warming admission remains closed, and return a repaired retry as running without changing the logical job identity

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

Map every unachieved lifecycle transition to the canonical HTTP 200 body with
`error` equal to `status`, an operator message, `retryable: true`, and the exact
controller snapshot. Preserve the typed `resume_recovery_failed` state while
admission remains closed in `warming`.

## Outcome

Satisfied by `0df85c2c`. The authenticated production resume route exposes an
unpublished persistence failure as retryable `resume_recovery_failed`, and a
repaired retry returns `running` without replacing the logical job identity.

## Notes

This acceptance is based on static inspection of the named commit and its
checked-in real-registry and real-filesystem proof. No test, service, RAG, CUDA,
GPU, lint, or type-check command was run during reconciliation.
