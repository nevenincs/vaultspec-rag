---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S08'
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
     The S08 and 2026-07-14-storage-namespace-hygiene-plan placeholders are machine-filled by
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
     The Add --root to the storage delete verb: normalize the root exactly as registration does, resolve via root_collection_prefix, dispatch through delete_prefix, and make an absent namespace an idempotent exit-0 already_absent success in both human and json modes with resolved prefix and queried root in the envelope and ## Scope

- `src/vaultspec_rag/cli/_service_storage.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add --root to the storage delete verb: normalize the root exactly as registration does, resolve via root_collection_prefix, dispatch through delete_prefix, and make an absent namespace an idempotent exit-0 already_absent success in both human and json modes with resolved prefix and queried root in the envelope

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

- Make the `PREFIX` argument optional and add `--root` to `server storage delete` (`src/vaultspec_rag/cli/_service_storage.py`), enforcing exactly-one addressing with a structured `bad_request` (exit 2)
- Resolve the root against the operator's cwd and derive the prefix through `root_collection_prefix` - the same normalization indexing uses
- Map `skipped`/`no_such_namespace` to an `already_absent` success (exit 0, both modes) via `dataclasses.replace`; echo the resolved root and derived prefix as `queried_root` in the envelope and human output

## Outcome

Harnesses get a sanctioned, idempotent one-verb per-root teardown; `delete_prefix` safety gates (canonical-prefix regex, unknown refusal) are untouched. Commit 7ae79ca.

## Notes

The status mapping lives in the CLI adapter, not `delete_prefix`, so the maintenance cycle's failed/removed accounting is unaffected.
