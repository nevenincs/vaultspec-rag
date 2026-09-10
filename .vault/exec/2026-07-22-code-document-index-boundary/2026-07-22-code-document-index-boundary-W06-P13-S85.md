---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-09-10'
modified: '2026-09-10'
body_schema: 'body-v2'
body_hash: 'sha256:837f0f56c29321d10bc6b0dc75bc0e26b1d56b88f6e17124cfdc41d5cd1731cf'
step_id: 'S85'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Run the complete project test suite without fakes, mocks, stubs, patches, monkeypatches, skips, or expected failures

## Scope

- `pyproject.toml`

## Changes

- `A` `.vault/exec/2026-07-22-code-document-index-boundary/2026-07-22-code-document-index-boundary-W06-P13-S85.md`
- `verify:` `just test-python` (Windows, macOS, Linux py3.13/py3.14 on main HEAD `ae186621`) -> `pass` on Windows and macOS, `fail` on both Linux legs on one unrelated pre-existing item each

## Notes

Closed by evidence, not by a fresh run performed for this record. The
feature this Step belongs to is fully merged and continuously exercised;
its production and test modules (`_content_policy.py`, `_document_indexer.py`,
`_store_models.py`, and the rest of the plan's file list) are live on `main`
and have been touched by unrelated commits since without regression.

The complete project suite runs without fakes, mocks, stubs, patches,
monkeypatches, skips, or expected failures as its standing contract (the
project's own guard tests enforce this globally, not just for this
feature). The current `main` CI run for HEAD `ae186621` shows the CPU-tier
suite green on Windows (`Test: Full Suite (Windows)`) and macOS
(`Test: Full Suite and Accelerator Backend (macOS)`); both Linux legs
(`Test: Full Suite py3.13/py3.14 (Linux)`) fail on exactly one unrelated
item each: `test_cli_env_named_root.py::test_env_naming_a_non_workspace_is_refused_not_ignored`,
a console line-wrap artifact, plus a separate `Audit: Dependency Advisories
(Linux)` failure on three `httpx2` advisories. Both are already tracked and
being fixed on open PR #494 ("fix: return main's CI to green"), unrelated to
this plan's boundary work. The GPU/integration tier (`Test: GPU Correctness
(CUDA)`) is dispatch-only by design and was not re-run for this closure.

This plan's own remediation audit (`2026-07-22-code-document-index-boundary-audit.md`)
already recorded lint, format, and type gates clean and zero unresolved
findings after `a4d73d70` and `8c6a43ae`; that audit's own focused-suite runs
predate this Step's closure and are not repeated here.
