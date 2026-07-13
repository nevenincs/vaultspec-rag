---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-14'
step_id: 'S14'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Prove end-to-end against real backends that a contained hook cannot read outside the staged dir nor open a socket, and that a worktree shipping a hook indexes its corpus through the service with no interaction

## Scope

- `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`

## Description

- Repaired the trust breakage left by P01: dropped the `_preprocess_trust` imports
  (`hash_rule_set`, `record_trust`) and every `EnvVar.PREPROCESS_TRUST_ALL` reference,
  which no longer exist after the trust store was deleted.
- Reworked the autouse fixture to isolate only `VAULTSPEC_RAG_STATUS_DIR` to a per-test
  tmp path; removed the trust-all opt-in and the `_default_mode` fixture, since the
  default mode now resolves and runs a root's rules for any root.
- Removed the two trust-model tests (`test_untrusted_default_executes_nothing_and_names_trust_verb`,
  `test_trusted_root_executes_and_command_edit_reverts_trust`) whose premise no longer
  exists.
- Added `test_hook_runs_contained_through_local_index`: a real command hook runs through
  a full local index under a resolved sandbox backend (asserts the backend is the
  Windows AppContainer on win32), its unit is searchable, and the indexed anchor and
  source path carry no `vsrag-hook-` scratch-dir leak.
- Added `test_untrusted_repo_hook_is_contained_not_refused`: a root with a hook and no
  trust record still runs, contained. The hook tries to read a secret placed OUTSIDE the
  granted project root and to open an outbound socket; the legitimate corpus content
  still extracts and indexes while the sandbox denies both malicious operations, proven
  from the indexed report (`SECRET_READ_BLOCKED`, `NETWORK_BLOCKED`).
- Added `test_off_kill_switch_skips_hooks`: under `VAULTSPEC_RAG_PREPROCESS=off` the hook
  does not run (sentinel absent) and the binary source is not indexed as a preprocessed
  unit.
- Kept the failing-extractor skip-count tests and every other extractor-behavior test;
  the existing binary-pdf assertions still hold because they now run through the sandbox
  and the staged-path remap keeps anchors pointed at the real source.

## Outcome

- `uv run --no-sync pytest src/vaultspec_rag/tests/integration/test_preprocess_integration.py -q -p no:cacheprovider`
  (resident service stopped, real GPU + Qdrant + subprocess): 10 passed in 508.26s. No
  mocks, skips, or test doubles; the containment test exercised the real AppContainer.
- `ruff check` clean and `basedpyright` reports 0 errors, 0 warnings on the test file.

## Notes

- No product code was touched; the runner, sandbox backends, and config were already
  complete from prior phases. No product bug surfaced.
- The containment proof depends on the secret living outside the project root, because
  the runner read-grants the project root to the hook so a project-local extractor can
  import its own module tree. A within-root secret would be readable by design.
