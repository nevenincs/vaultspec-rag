---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-09'
modified: '2026-06-09'
step_id: 'P07.S24'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` P07.S24 - formal code review of deconflation diff

scope: `src/vaultspec_rag/` (commit `671dcd3`)

## Description

Ran the `vaultspec-code-reviewer` persona (read-only) against the P05/P06 deconflation
diff in commit `671dcd3` (the `8154e36` research commit is docs-only and skipped).

## Outcome

**Verdict: APPROVE WITH NITS.** No Critical or High findings. The deconflation is correct,
complete, and shim-free: `mcp/` is a pure protocol adapter (verified import isolation),
identifier renames are total with no dangling references, the `--port` delegation and
`--allow-fallback` semantics are preserved, the genuine MCP surfaces (`cli/_mcp_admin.py`,
`server mcp` commands, `/mcp` endpoint, stdio transport, `vaultspec-search-mcp` binary) are
correctly retained, and the two guard tests are sound and non-tautological.

Findings (all minor):

- **M1 (Medium):** the rule entrypoint source fix (`mcp_server:main -> server:main`) is
  correct and committed in the `.vaultspec/` source, but the generated provider mirror
  `.claude/rules/vaultspec-rag.builtin.md` still shows the stale `mcp:main`. The mirror
  regenerates from source via `vaultspec-core sync`, but committed mirror copies cannot be
  updated by a commit (the `check-provider-artifacts` hook forbids staging them). The
  committed-mirror staleness is pre-existing provider-artifact-tracking debt (the mirror
  was already committed stale); the authoritative source is correct.
- **L1 (Low):** `test_no_mcp_server_conflation.py` docstring still said "expected to fail"
  though the strings were fixed in the same commit and the test passes (33/33).
- **L2 (Low):** the `evict_project` integration assertion compares against
  `str(tmp_path / ...)` rather than `Path(...).resolve()`; equal on Windows, fragile under
  symlinked tmp dirs.
- **N1 (Nit):** `cli/_http_search.py` still routes an (ignored) `project_root` to
  `/projects` after the tool's param was dropped.

## Notes

L1 fixed in this pass (the guard docstring now reads as an enforced invariant). M1 is
provider-artifact-tracking debt, not a code defect (source is correct). L2/N1 are
non-blocking nits left as-is. The review clears the deconflation code for merge.
