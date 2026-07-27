---
tags:
  - '#audit'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-27-lint-defaults-plan]]"
---
# `lint-defaults` audit: indexer rows review

## Scope

Independent review of commits `493f85ba`, `3cfc1266`, `5674c657`, `ecf3fe24`, `4e832828`, `154f1302`, `32c07222`, `5b4fc4c0`, `88512ddc`, `0679f3c5`, `4157358d`, `a140879c`, `0ecb1945`, `d6bbcf43`, `2ac31f1d`, the lint-only part of `10e325fb`, and `e9ec5179`. Reviewed their complete diffs and the current call sites affected by the indexer option interface.

## Findings

### codebase-indexer-threading | high | Resolved before this review completed

The initial review found a missing type-only `threading` import at `CodebaseIndexer.Options.gpu_lock`. Commit `2ac31f1d` restores the import. The current API, service, and test call sites consistently construct `CodebaseIndexer.Options`, so the associated constructor-interface change has no observed stale keyword callers.

### concurrent-search-context-port | low | Corrected undefined helper variable

Commit `e9ec5179` replaces the helper's undefined `port` variable with the supplied concurrent-search context port. The helper constructs and passes that context through its documented call path; the correction is consistent and introduces no additional issue.

### lint-worktree-followups | medium | Current uncommitted work needs its own gate

The reviewed committed lint rows have no remaining critical or high finding. The current dirty worktree separately contains unfinished edits in `cli/_install.py`, `logging_config.py`, and `qdrant_runtime/_provision.py`; a fresh scoped Ruff invocation reports five diagnostics there. Those edits are outside the reviewed commit diffs and need validation by their owner before a whole-worktree green claim.

## Recommendations

Treat the reviewed committed lint rows as approved after their existing focused test evidence. Keep the current uncommitted follow-up edits out of those records until their owner resolves the reported Ruff diagnostics and re-runs its scoped checks.
