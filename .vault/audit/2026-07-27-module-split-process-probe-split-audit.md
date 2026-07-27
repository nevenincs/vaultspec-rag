---
tags:
  - '#audit'
  - '#module-split'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-06-01-module-split-plan]]"
---

# `module-split` audit: `process probe split`

## Scope

Audited P07.S07's direct collection split: the former canonical guard module,
the six behavior-domain test modules, and their concrete shared helper. The
review checked guard recovery, collection/import behavior, and the prohibition
on test-only facades or re-exports.

## Findings

### retained-canonical-collector | high | The original test monolith remains directly collected

`test_process_probe_canonical.py` remains a 4,218-line, directly collected
test module while all 116 of its guard tests are present in the six new direct
modules. Focused collection reports 232 tests, which executes each guard
twice. This does not meet P07.S07's direct replacement requirement and keeps
the overlength monolith alive rather than replacing it. The retained file is a
duplicate collector, not a compatibility facade, but has the same practical
result: two homes and two executions for each guard.

Recovery verification found all 48 test classes and all 116 test methods in
the direct modules, with no missing identities. The 15 method-body deltas are
helper extraction, local-import removal, annotations, diagnostics, or
intentional canonical-owner renames; the six modules pass independently
(115 passed, 1 skipped). Their shared module is a concrete helper module, and
the direct modules have no imports of the retained collector. It is therefore
safe for the executor to delete the retained collector without losing the
recovered test content, subject to preserving the verified direct modules.

### retained-canonical-collector-resolution | resolved | The duplicate collector was removed

The verified direct modules now replace the former collector. Focused collection
reports 116 tests, and the focused run passes 115 tests with one platform-gated
skip. Ruff reports no lint or format findings for the seven replacement files.

## Recommendations

- Delete `test_process_probe_canonical.py` after retaining the six verified
  direct modules and `_process_probe_guard_helpers.py`; then rerun focused
  collection to confirm it reports 116 tests rather than 232.
