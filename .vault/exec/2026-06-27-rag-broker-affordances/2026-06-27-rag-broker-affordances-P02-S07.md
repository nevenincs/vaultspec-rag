---
tags:
  - '#exec'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S07'
related:
  - "[[2026-06-27-rag-broker-affordances-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace rag-broker-affordances with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S07 and 2026-06-27-rag-broker-affordances-plan placeholders are machine-filled by
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
     The Unit-test the pointer path, the heartbeat write beside the lock, the shutdown cleanup, and the tolerant reader with an isolated temp storage dir and ## Scope

- `src/vaultspec_rag/tests/test_machine_discovery.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Unit-test the pointer path, the heartbeat write beside the lock, the shutdown cleanup, and the tolerant reader with an isolated temp storage dir

## Scope

- `src/vaultspec_rag/tests/test_machine_discovery.py`

## Description

- Authored `test_machine_discovery.py` (unit, isolated singleton paths): the pointer sits beside the lock and is named `service.json`; `read_machine_discovery` is `None` when absent; a write/read round-trips the payload; the reader tolerates garbage and a non-object JSON array as `None`; and `_unlink_status_file_silently` removes the pointer.

## Outcome

5 discovery tests pass with no mocks (real files at a temp-isolated machine-global path); basedpyright and ruff clean.

## Notes

Tests both `_machine_lock` (path + reader) and the daemon `_lifecycle` write/cleanup directly, so the contract is covered without standing up a full daemon.
