---
tags:
  - '#exec'
  - '#install-mcp-dependency-fix'
date: '2026-06-10'
modified: '2026-06-30'
step_id: 'S04'
related:
  - "[[2026-06-10-install-mcp-dependency-fix-plan]]"
---

# Run uv sync, ruff, basedpyright and the unit suite, verify the server entry import path is clean, file the upstream mcp 2233 version-floor follow-up issue, then commit

## Scope

- `pyproject.toml`

## Description

- Verify the resolved environment: `mcp` present as a core dependency (the
  `0.2.19` release synced `uv.lock` in commit `dbd89c2`).
- Run `ruff check` and `basedpyright` on the changed files; run the new
  packaging-metadata unit test.
- Smoke-test the server entry import path without loading GPU or models.
- File the upstream `mcp` #2233 version-floor follow-up issue.
- Land the change on a commit referencing #182.

## Outcome

All gates green against the working tree:

- `ruff check` on `src/vaultspec_rag/server/_main.py` and
  `src/vaultspec_rag/tests/test_packaging_metadata.py`: clean.
- `basedpyright` on both files: `0 errors, 0 warnings, 0 notes`.
- `test_mcp_is_a_core_dependency`: `1 passed`.
- Import smoke: `import vaultspec_rag.server` and `from vaultspec_rag.mcp import mcp` both succeed (`mcp` resolves to `FastMCP`).

Delivered out-of-band: the code landed in commit `4e4af36`, was released as
vaultspec-rag `0.2.19` (release commit `302e80a`, lockfile sync `dbd89c2`), and
the version-floor follow-up was filed as issue #184
(`Add mcp version floor once upstream pywin32 eager-import fix ships`).

## Notes

The implementation, release, and follow-up issue were all completed before this
execution trail was committed. No duplicate issue was filed (issue #184 already
tracks the deferred `mcp>=<fixed>` floor). This Step Record verifies and
documents the delivered work rather than re-performing it.
