---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S11'
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
     The S11 and 2026-06-27-storage-schema-contract-plan placeholders are machine-filled by
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
     The Add the bounded schema descriptor node to the readiness report to_dict and ## Scope

- `src/vaultspec_rag/_readiness.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the bounded schema descriptor node to the readiness report to_dict

## Scope

- `src/vaultspec_rag/_readiness.py`

## Description

- Added a bounded `schema` node to `ReadinessReport.to_dict` carrying `store_schema.describe_storage_schema()`.
- Used a lazy import of `store_schema` inside `to_dict` to keep the readiness module's import graph minimal; the descriptor is config-derived and torch-free, so it stays inside the no-GPU readiness contract.

## Outcome

`/readiness` now advertises the full storage-schema descriptor (version + per-collection vectors/payload-fields/indexes + models). The CLI `server doctor` and the MCP readiness tool inherit it through the shared `get_readiness`, so no adapter duplicates it (service-domain-owns-operability).

## Notes

Updated the existing `test_readiness` round-trip assertion to include the new `schema` key (a deliberate contract addition).
