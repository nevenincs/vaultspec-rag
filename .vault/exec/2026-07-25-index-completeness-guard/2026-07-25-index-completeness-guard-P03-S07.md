---
tags:
  - '#exec'
  - '#index-completeness-guard'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S07'
related:
  - "[[2026-07-25-index-completeness-guard-plan]]"
---

# Run the lint, type, citation, complexity, and full test gates and record actual output rather than asserting success

## Scope

- `gates only`
- `no source changes`

## Description

- Run every gate and record its actual output.
- Attribute each failure to the change that caused it rather than reporting a
  pass rate.

## Outcome

Gates were invoked explicitly because the commit-hook runner was removed from
this repository mid-execution; commits no longer gate themselves, so each gate
below was run by hand against the landed state.

| Gate       | Command                                         | Result                                                                                      |
| ---------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Lint       | `ruff check` over this feature's files          | `All checks passed!`                                                                        |
| Format     | `ruff format --check` over this feature's files | `13 files already formatted`                                                                |
| Type       | `ty check` over this feature's files            | `All checks passed!`                                                                        |
| Citation   | `tools/citation_gate.py`                        | `clean - no active development-record citations or workstation-identity path leaks`, exit 0 |
| Complexity | `tools/complexity_gate.py`                      | `PASS - all complexity gates green` (cognitive \<= 20, xenon absolute \<= C, nesting \<= 6) |
| Tests      | full unit suite                                 | 2193 passed, 2 failed, 558 deselected, 13m15s                                               |
| Tests      | this feature's five files                       | 179 passed                                                                                  |

Repository-wide, three gate results are not green, and none is caused by this
change:

- `ruff check src/` reports one undefined name in the storage-operations
  module, from another worker's uncommitted refactor.
- `ruff format --check` reports one stray blank line in the code indexer,
  introduced by another worker's commit that landed after the hook runner was
  removed and so was never formatted. It sits in the block that worker is
  currently extracting, and this Step deliberately left it alone rather than
  edit a region under active refactor.
- `ty check` reports diagnostics in the searcher, the service doctor, the
  service client compatibility shim and four test modules, all from other
  workers' in-flight edits.

The two suite failures are both attributable to other commits:

- The commit-gate regression test asserts the hook configuration file exists.
  The commit that removed the hook runner deleted that file and left the test
  behind.
- The daemon status writer test asserts an exact key set, and a later commit
  added a package-version key to the payload without updating it.

Both were reproduced alone to confirm the attribution, and both were reported
to the coordinator rather than fixed here: neither is in this feature's scope,
and editing another worker's test to make a suite green is how a real
regression gets buried.

## Notes

A per-file gate run is the honest unit here rather than a repository-wide one.
Roughly sixty files were being edited concurrently by other workers throughout,
so a whole-repository red result says nothing about this change. Every gate was
therefore also run scoped to this feature's files, and both readings are
recorded above rather than only the flattering one.
