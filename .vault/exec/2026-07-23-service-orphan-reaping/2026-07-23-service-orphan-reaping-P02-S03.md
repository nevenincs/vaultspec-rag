---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S03'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-orphan-reaping with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S03 and 2026-07-23-service-orphan-reaping-plan placeholders are machine-filled by
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
     The Make the release-on-failure teardown tolerate a claim that produced no lease and ## Scope

- `src/vaultspec_rag/server/_lifespan.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Make the release-on-failure teardown tolerate a claim that produced no lease

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Guard the failure-branch `_shutdown_components` call with
  `discovery is not None`, so a claim that lost the race (no discovery built)
  skips a teardown that has nothing to release.

## Outcome

The failure path now falls straight through to `_exit_standalone_daemon(1)` when
the claim itself lost, and still runs full component teardown when a later
startup step failed after the lease was held. Type-checkers accept the
`_DiscoveryPublisher | None` narrowing across the guard and the post-yield
finally. ruff, ty, basedpyright clean. Landed with S01 in commit `57bdee8f`.

## Notes

Necessarily coupled with S01: moving the claim inside the guard is only correct
once the teardown tolerates a no-lease claim.
