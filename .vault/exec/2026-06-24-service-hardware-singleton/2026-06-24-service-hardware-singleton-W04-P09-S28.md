---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S28'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-hardware-singleton with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S28 and 2026-06-24-service-hardware-singleton-plan placeholders are machine-filled by
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
     The Decide whether in-process lifespan reuse is a supported contract and ## Scope

- `if so`
- `release the machine lock on a pre-yield startup failure (acquire inside the try`
- `or release-on-failure around the qdrant/model startup) - the shipping daemon already self-heals via OS release on process exit`
- `src/vaultspec_rag/server/_lifespan.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Decide whether in-process lifespan reuse is a supported contract

## Scope

- `if so`
- `release the machine lock on a pre-yield startup failure (acquire inside the try`
- `or release-on-failure around the qdrant/model startup) - the shipping daemon already self-heals via OS release on process exit`
- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Make in-process lifespan reuse a supported contract: release the machine
  singleton lock on any pre-yield startup failure.
- Factor the lifespan startup into `_start_components` (returns the heartbeat
  task) and the teardown into `_shutdown_components`, so the whole pre-yield body
  runs under one guard without nesting the yield in a startup-only try.
- Wrap the startup, yield, and shutdown in a try whose `except BaseException`
  calls `release_machine_lock` and re-raises, covering the pre-yield failure (and
  a cancelled startup) that the post-yield finally never reaches.
- Add a regression test that drives the real lifespan with a real foreign HTTP
  holder on the configured qdrant port, forcing a genuine refuse-fast pre-yield
  failure, then asserts a fresh in-process acquire of the machine lock succeeds.

## Outcome

The machine lock no longer leaks on a pre-yield startup failure: a forced
refuse-fast leaves the lock free for a subsequent acquire, and a clean run still
releases exactly once in the post-yield teardown (release is idempotent, so no
double-release hazard). Two unit tests pass; the lifespan modules type-check and
lint clean.

## Notes

The release-on-failure guard re-raises the original exception unchanged, so the
loud, named startup-failure messages the daemon already surfaces are preserved.
The shipping daemon still self-heals via the OS releasing the lock on process
exit; this change only matters for the in-process lifespan REUSE path the
shutdown block's contract claims.
