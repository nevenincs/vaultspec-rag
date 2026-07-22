---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S47'
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
     The S47 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Derive per-kind membership and content signatures from source profile, ordered routes, targets, ignores, schema, and extractor semantics and ## Scope

- `src/vaultspec_rag/indexer/_config_epoch.py`
- `src/vaultspec_rag/indexer/_resolved_policy.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Derive per-kind membership and content signatures from source profile, ordered routes, targets, ignores, schema, and extractor semantics

## Scope

- `src/vaultspec_rag/indexer/_config_epoch.py`
- `src/vaultspec_rag/indexer/_resolved_policy.py`

## Description

- Derive closed code and document fingerprint projections from one policy snapshot.
- Include source profile, ordered routes, ignores, transform targets, and schema in membership.
- Keep operation-only excludes separate from persistent membership identity.
- Filter extractor semantics by target so content rebuilds remain kind-local.
- Include decoder, parser, raw-chunk, transform, and byte-cap semantics in content identity.
- Keep execution mode outside per-kind membership and content identities.
- Validate extractor changes, target flips, profile changes, excludes, and closed kind lookup.

## Outcome

Code and document consumers now receive independent membership and content identities from
the same immutable snapshot. Ownership moves invalidate both affected memberships, while a
kind-local extractor change cannot force an unrelated kind's content rebuild.

## Notes

No incidents or data loss. Durable generation/checkpoint binding is scheduled for later plan
steps; S47 supplies the normalized per-kind signatures required by that work.
