---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
modified: '2026-06-30'
step_id: 'S02'
related:
  - "[[2026-06-09-operability-hardening-plan]]"
---

# interpreter version guard

## Scope

- `src/vaultspec_rag/store.py`
- `src/vaultspec_rag/tests/test_store.py`

## Description

- Add `_interpreter_is_supported(version_info)` pure helper that returns `True` only for CPython 3.13.x.
- Move `Sequence` import under `TYPE_CHECKING` block to satisfy ruff TC003 and keep annotation-only imports lazy.
- Extend `_check_rag_deps()` with an interpreter version guard that fires before `import qdrant_client`; raises `RuntimeError` with the running `sys.version` and a remediation hint.
- Add `TestInterpreterIsSupported` class (6 unit tests, `pytestmark = unit`) exercising `True`/`False` branches with plain tuples — no monkeypatching.

## Outcome

- `ruff check` and `ty check` both clean on modified files.
- 6/6 new unit tests pass (`TestInterpreterIsSupported`).
- CPython 3.14+ callers now receive a descriptive `RuntimeError` before the protobuf metaclass `TypeError` is triggered.

## Notes

None.
