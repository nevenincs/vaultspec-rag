---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S05'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace code-document-index-boundary with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S05 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Compile ignore precedence, explicit ownership, source-profile admission, and parser selection into one deterministic classifier and ## Scope

- `src/vaultspec_rag/indexer/_content_policy.py`
- `src/vaultspec_rag/indexer/_ignore_specs.py`
- `src/vaultspec_rag/indexer/_chunking.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Compile ignore precedence, explicit ownership, source-profile admission, and parser selection into one deterministic classifier

## Scope

- `src/vaultspec_rag/indexer/_content_policy.py`
- `src/vaultspec_rag/indexer/_ignore_specs.py`
- `src/vaultspec_rag/indexer/_chunking.py`

## Description

- Separate conventional source admission from parser capability.
- Apply project ignore specifications before all ownership decisions.
- Compile root routes and transform targets into a one-owner decision.
- Admit conventional source only after explicit routing has been resolved.
- Select a structured or generic text parser only after admission.
- Validate lint, typing, and real classification behavior.

## Outcome

One classifier now produces deterministic ownership, admission reason, and parser capability.
Ambiguous formats do not enter the code domain through parser support alone, while
caller-authored routes can assign unconventional source or raw documents explicitly.

## Notes

No incidents or data loss. Concurrent shared-worktree commits temporarily displaced an
unstaged edit; the final implementation was reapplied against the current `main` state and
revalidated before commit.
