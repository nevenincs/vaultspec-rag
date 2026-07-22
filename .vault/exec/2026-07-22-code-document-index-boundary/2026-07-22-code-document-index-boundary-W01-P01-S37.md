---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S37'
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
     The S37 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Define indexed, policy-rejected, retryable-extraction, terminal-extraction, decode-failed, and chunk-failed file states and ## Scope

- `src/vaultspec_rag/indexer/_file_state.py`
- `src/vaultspec_rag/_job_errors.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Define indexed, policy-rejected, retryable-extraction, terminal-extraction, decode-failed, and chunk-failed file states

## Scope

- `src/vaultspec_rag/indexer/_file_state.py`
- `src/vaultspec_rag/_job_errors.py`

## Description

- Define the closed indexed, policy-rejected, extraction, decode, and chunk states.
- Keep content hashes as evidence without treating failed work as convergence.
- Require every processing failure to retain its content kind, typed error, and detail.
- Mark only indexed and stable policy-rejected outcomes as converged.
- Expose stable reason and retry-obligation projections for service adapters.
- Add operator remediation for each processing-failure error kind.
- Validate every state, invariant, path form, error classification, and remediation.

## Outcome

Per-file outcomes can no longer certify a failed hash as successful metadata. Retryable and
terminal failures remain explicit, kind-owned, structured obligations while policy rejection
stays distinct from processing failure.

## Notes

No incidents or data loss. Worker result wiring and durable ledger persistence are scheduled
for later plan steps; S37 defines the stable state authority those paths will consume.
