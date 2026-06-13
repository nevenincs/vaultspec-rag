---
tags:
  - '#exec'
  - '#install-mcp-dependency-fix'
date: '2026-06-10'
modified: '2026-06-10'
step_id: 'S03'
related:
  - "[[2026-06-10-install-mcp-dependency-fix-plan]]"
---

# Add a packaging-metadata regression test asserting importlib.metadata.requires reports mcp as a core requirement with no extra marker

## Scope

- `src/vaultspec_rag/tests/test_packaging_metadata.py`

## Description

- Add a unit test that reads `importlib.metadata.requires("vaultspec-rag")`.
- Parse each requirement with `packaging.requirements.Requirement` and classify
  a requirement as core when it carries no `extra ==` environment marker.
- Assert `mcp` is among the core requirement names, with a failure message that
  lists the observed core dependencies.

## Outcome

Implemented and shipped out-of-band in commit `4e4af36`. Verified against the
working tree: `test_mcp_is_a_core_dependency` reads real installed distribution
metadata (no mocks, stubs, or skips), makes a substantive assertion, and
**passes** (`1 passed`). `ruff check` passes on the file. The test pins the F1
defect closed at the metadata layer.

## Notes

The test is marked `pytest.mark.unit` and exercises live packaging metadata, so
it guards the declaration in CI without requiring GPU or network.
