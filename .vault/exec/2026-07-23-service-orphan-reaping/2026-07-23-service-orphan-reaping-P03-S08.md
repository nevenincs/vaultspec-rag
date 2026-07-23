---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S08'
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
     The S08 and 2026-07-23-service-orphan-reaping-plan placeholders are machine-filled by
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
     The Add guard tests that the reap never targets the singleton, a foreign process, or an isolated-config instance and ## Scope

- `src/vaultspec_rag/tests/test_service_stop_port.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add guard tests that the reap never targets the singleton, a foreign process, or an isolated-config instance

## Scope

- `src/vaultspec_rag/tests/test_service_stop_port.py`

## Description

- Spawn real launcher+worker witness pairs (a venv shim makes each
  `-m vaultspec_rag.server --port <port>` spawn a two-process pair) on isolated
  status/storage dirs and a unique port, then reap OUT-OF-PROCESS via
  `python -m vaultspec_rag server stop --orphans --port <port> --json`.
- Prove the launcher-pointer case: with the launcher recorded as the
  discovery pointer, the whole singleton pair is spared, the whole orphan pair
  is reaped, and a daemon on a different port is never enumerated.
- Prove the worker-pointer case: with the worker (the child that runs the
  lifespan, as production publishes) recorded as the pointer, the shim launcher
  is spared via the protect-parent branch.
- Prove the machine-lock case: a singleton that holds the lease but published
  no pointer is spared by the lock anchor alone (no-pointer recovery scenario).

## Outcome

The reap is proven never to target the live singleton pair, a foreign-port
daemon, or (via the /health-port anchor added in the P04 review) an
isolated-config instance sharing the port. All three anchor sources -
discovery pointer, machine-lock holder, and live port holder - and both lineage
branches are covered. Guard-tests-prove-they-can-fail: the protect-parent,
protect-child, and lock-holder anchors each turn a spare assertion RED when
removed from the reap's anchor set, and restore to green - recorded in the
commit bodies. Ran out-of-process to eliminate the self-anchor confound that an
in-process reap introduces (the reaper would parent the witness daemons). ruff,
basedpyright, and the citation gate clean.

## Notes

The reap MUST run out-of-process in these tests: an in-process reap makes
`os.getpid()` the sentinels' parent, so the self-anchor masks the
pointer/lineage protection and the mutation-proof does not bite. Landed across
commits `98ad4441` (safety restructure + the P04 /health-anchor HIGH fix) and
`0bb27b12` (the machine-lock anchor case).
