---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S10'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-schema-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S10 and 2026-06-27-storage-schema-contract-plan placeholders are machine-filled by
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
     The Add a reindex-parity integration test asserting points serialize byte-for-byte unchanged and ## Scope

- `src/vaultspec_rag/tests/integration/test_store_schema_parity.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add a reindex-parity integration test asserting points serialize byte-for-byte unchanged

## Scope

- `src/vaultspec_rag/tests/integration/test_store_schema_parity.py`

## Description

- Authored `test_store_schema_parity.py` asserting each builder produces the exact golden payload dict for a constructed dataclass: the vault document (10 fields), the vault chunk at a non-zero ordinal (no doc_content), the ordinal-0 chunk (carries doc_content), the ordinal-0 chunk with no doc_content (omits it), and the code chunk (17 fields).
- Marked the test `unit` (pure: no Qdrant, no GPU, no network) so it runs in the CI gate.

## Outcome

The shape-preserving guarantee is regression-guarded: a field added/removed/renamed against the frozen golden shape fails this test. 6 parity tests pass; the full 1136-test unit suite is unchanged.

## Notes

Realised as a unit test over the pure builders rather than a live-store round trip, because the CI gate runs `pytest -m unit` only; the live-collection check is the P04 drift test (S16).
