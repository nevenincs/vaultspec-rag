---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S12'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace managed-log-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S12 and 2026-07-21-managed-log-contract-plan placeholders are machine-filled by
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
     The Replace the legacy activity parser and raw compatibility flag with grouped source rendering and offline fallback and ## Scope

- `src/vaultspec_rag/cli/_service_logs.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Replace the legacy activity parser and raw compatibility flag with grouped source rendering and offline fallback

## Scope

- `src/vaultspec_rag/cli/_service_logs.py`

## Description

- Replace service activity parsing with explicit service, Qdrant, or all-source rendering.
- Use grouped raw plaintext by default and expose the shared JSON shape.
- Fall back to the production local reader only when the service is unavailable.
- Remove the raw compatibility flag and service-only command identity.

## Outcome

One `server logs` command works truthfully while the daemon is live and after it stops.

## Notes

Live structured errors remain errors and do not trigger misleading local success.
