---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S07'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify real configuration loading, route ordering, one-owner enforcement, and mutation-free migration refusal

## Scope

- `src/vaultspec_rag/tests/test_content_policy.py`
- `src/vaultspec_rag/tests/test_preprocess_config.py`

## Description

- Replace legacy schema-v1 fixtures with real schema-v2 ownership configuration.
- Verify required targets, extractor versions, ordering, matching, options, and pickling.
- Verify migration, unknown-target, newer-schema, and conflicting-owner refusal in every mode.
- Exercise the execution kill switch through a real subprocess without environment mutation.
- Verify root route ordering, closed targets, ignore precedence, and layout independence.
- Verify snapshot conflict rejection, pickle identity, and mutation-free legacy refusal.
- Run focused Ruff, Ty, and real pytest suites without test doubles or skip shortcuts.

## Outcome

The policy boundary is covered by 23 real-behavior tests. Legacy or conflicting ownership
cannot degrade into fallback admission, execution-off retains strict routing knowledge, and
snapshot resolution proves it does not mutate a rejected root.

## Notes

No incidents or data loss. The touched tests use production imports, temporary files, and a
real child process; they contain no mocks, fakes, stubs, patches, monkeypatches, skips, or
expected-failure markers.
