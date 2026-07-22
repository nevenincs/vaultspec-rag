---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S06'
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
     The S06 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Resolve one immutable policy snapshot containing routing, preprocessing, decoding, execution mode, and normalized fingerprints and ## Scope

- `src/vaultspec_rag/indexer/_resolved_policy.py`
- `src/vaultspec_rag/indexer/_config_epoch.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Resolve one immutable policy snapshot containing routing, preprocessing, decoding, execution mode, and normalized fingerprints

## Scope

- `src/vaultspec_rag/indexer/_resolved_policy.py`
- `src/vaultspec_rag/indexer/_config_epoch.py`

## Description

- Resolve routing, ignores, transforms, decoding, and execution mode once per operation.
- Freeze preprocess options recursively into typed, picklable canonical values.
- Rebuild derived ignore and transform matchers from immutable tuple authority.
- Separate persistent and operation-only membership identities.
- Version policy, parser, chunk, decoder, transform, content, and execution semantics.
- Compile raw caller routes into closed target and source-profile vocabularies.
- Validate static checks, route behavior, identity boundaries, and pickle reconstruction.

## Outcome

`ResolvedIndexPolicy` now provides one reconstructible value for discovery, worker,
fingerprint, checkpoint, and publication consumers. Execution-mode changes retain ownership,
operation-only excludes do not contaminate persistent epochs, and mutable option materialized
for a worker cannot mutate the active snapshot.

## Notes

No incidents or data loss. Entry-point gating and exact snapshot threading remain scheduled
for S88 and S90; S06 establishes the immutable authority they will consume.
