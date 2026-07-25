---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S12'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-conformance with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S12 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
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
     The Author the nonconforming verdict as a live-service degraded reason where degradation is already authored and ## Scope

- `src/vaultspec_rag/server/_lifespan.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Author the nonconforming verdict as a live-service degraded reason where degradation is already authored

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

`ServiceHealth` gains a `nonconforming` list, populated in `ServiceRegistry.health`
from the verdicts the ensure path already recorded, and `_service_health_status`
appends a reason and flips a ready service to degraded when it is non-empty.

No backend call happens on the health path. The registry reads each warm slot's
recorded verdicts under the lock it already holds, so a health poll stays cheap;
a collection nobody has opened contributes nothing rather than a guess, and an
`unverifiable` one contributes nothing either.

The reason names up to three affected collections so an operator can tell which
index to rebuild. Proven by mutation: with the branch removed the service
reports `ready` while returning rankings computed against another model's
vectors (`assert 'ready' == 'degraded'`), and with the collection names dropped
the naming assertion fails.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
