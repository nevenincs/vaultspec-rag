---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S09'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-namespace-hygiene with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S09 and 2026-07-14-storage-namespace-hygiene-plan placeholders are machine-filled by
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
     The Test the delete --root matrix: resolution parity with registration, removed, already_absent exit 0, unknown refusal, and json envelope shape and ## Scope

- `src/vaultspec_rag/tests/test_storage_safety.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Test the delete --root matrix: resolution parity with registration, removed, already_absent exit 0, unknown refusal, and json envelope shape

## Scope

- `src/vaultspec_rag/tests/test_storage_safety.py`

## Description

- Add `TestDeleteRootAddressing` to `src/vaultspec_rag/tests/test_storage_adversarial.py`: both/neither addressing rejected (exit 2, structured envelope), root resolution parity with `root_collection_prefix`, `already_absent` success in json and human modes, unknown-namespace refusal preserved, prefix form unchanged
- Bypass the client with a typed `_run_storage_op` stand-in and a recording `delete_prefix` fake

## Outcome

7 new CLI tests covering the addressing matrix and outcome mapping; all pass. Commit 7ae79ca.

## Notes

Tests were placed in the adversarial suite (the destructive-verb guard module) rather than `test_storage_safety.py` (path containment only); the plan step scope was updated accordingly.
