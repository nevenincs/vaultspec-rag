---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
step_id: 'S27'
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
     The S27 and 2026-07-24-service-quiesce-plan placeholders are machine-filled by
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
     The Render controller state, GPU release evidence and borrower safety in the jobs TUI header and status details and ## Scope

- `src/vaultspec_rag/cli/_jobs_tui.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Render controller state, GPU release evidence and borrower safety in the jobs TUI header and status details

## Scope

- `src/vaultspec_rag/cli/_jobs_tui.py`

## Description

Render the controller-owned state, VRAM release evidence, and borrower-safety
observation from the jobs response. Treat absent, invalid, or incomplete
controller evidence as unavailable rather than inferring safety.

## Outcome

Accepted for S27 after merge commit `5dc05814` adopts the controller-derived
`QUIESCE_ENVELOPE_FIELDS` vocabulary and deletes the duplicated local field
sets. `54284415` and `9b1f0410` provide the rendering behavior, and `0576e4f4`
removes the rejected source-mutating probe. The reported CPU-only proof includes
the checked-in real no-lifespan route host: it pauses a real registry, fetches
jobs through authenticated transport, and renders the canonical block in
Textual. A real rejected jobs request renders `quiesce unavailable` and does
not render borrower safety as safe.

## Notes

The current successful `GET /jobs` route always serializes the complete
controller envelope, so it cannot produce a successful partial quiesce block.
The TUI's exact-field rejection for that hypothetical malformed success is
static, unexercised defense-in-depth. No response seam, test hook, proxy,
handcrafted contract, or production-source mutation is permitted to manufacture
it. Exact-set fail-closed behavior now consumes the controller-owned vocabulary;
no response seam, test hook, proxy, handcrafted contract, production-source
mutation, or source-inspection mutation test is used. The reported focused run
started no daemon lifespan, GPU, or Qdrant process.
