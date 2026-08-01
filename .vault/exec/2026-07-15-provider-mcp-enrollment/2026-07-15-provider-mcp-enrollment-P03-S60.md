---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
body_hash: 'sha256:765586a8dd01eb356755f01343310d19dce1ee1dadc119eeeecba1dc7403d822'
step_id: 'S60'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Repair locked Windows scikit-learn wheel payload

## Scope

- `.venv scikit-learn 1.9.0 installation`
- `uv cache and public wheel evidence`
- `installed msvcp140.dll and vcomp140.dll hashes`
- `direct sklearn import`
- `exact failed intent selector`
- `six-item S56 model group`
- `and S60 formal review`

## Description

- Compare the incomplete worktree installation with its installed `RECORD`.
- Verify one uv cached extraction and one fresh no-cache public-wheel extraction.
- Reinstall only scikit-learn 1.9.0 from the locked dependency graph.
- Verify the installed runtime payload by size and SHA-256 digest.
- Import scikit-learn directly from the repaired worktree environment.
- Run the exact failed intent-ranking selector and the six-test S56 model group.

## Outcome

- Confirmed that the lock and uv cache were complete. Both cached and freshly downloaded
  wheel extractions contained the two package-local runtime DLLs with hashes matching
  `RECORD`.
- Repaired only the disposable `.venv` with
  `uv sync --locked --reinstall-package scikit-learn`.
- Passed `uv sync --frozen`, `uv pip check`, and `uv lock --check`.
- Imported scikit-learn 1.9.0 directly from the repaired worktree environment.
- Verified `msvcp140.dll` at 642,720 bytes with digest
  `sha256=Y5NC6ppnwACRIiOM4HCoJX4uBNNn1idQn-wp-EQq-0I`.
- Verified `vcomp140.dll` at 213,072 bytes with digest
  `sha256=-W86FNiNiEbzHzqzikkDBM59bk9w-uQwTGPlnHrqLTA`.
- Passed the exact S59 intent selector: one test in 218.70 seconds.
- Passed the complete six-test S56 model group in 117.41 seconds.
- Passed formal review with no actionable findings.

## Notes

The original worktree installation contained matching package metadata but no
`sklearn/.libs` directory. The cached extraction and a fresh public wheel were complete,
so no cache eviction or lock change was required. No product, test, lock, or package
source changed.

This environment repair and focused verification receive no release-campaign credit.
They do not authorize a pull request, merge, approval, publication, or release.
