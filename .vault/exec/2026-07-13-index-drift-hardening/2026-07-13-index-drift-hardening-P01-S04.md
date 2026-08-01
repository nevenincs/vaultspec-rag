---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:8f7c6715d54063932a16261012523ce1b8dadd9f18f68e92e14553678c2a3d47'
step_id: 'S04'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# Unit-test the drift-class escalation matrix over real tmp roots: newly-ignored prune, newly-admitted pickup, preprocess pattern change forcing unscoped, html_strip and command change forcing clean rebuild, legacy sidecar unscoped-once, and scoped-path epoch cost staying rglob-free

## Scope

- `src/vaultspec_rag/tests/test_config_epoch.py`

## Description

- Cover the pure epoch functions over synthetic rule sets: membership stability
  across gitignore reorders, membership sensitivity to gitignore, vaultragignore,
  and preprocess-pattern changes, membership insensitivity to command changes,
  content sensitivity to command, options, on_error, timeout, order, and
  html_strip, content insensitivity to pattern changes, and the vault epoch over
  the chunk-char knob.
- Cover the drift-class escalation matrix over real tmp roots through the
  indexer's classifier: no-drift is a no-op, a newly-ignored file and a
  newly-admitted file each force the unscoped incremental, an html_strip flip
  forces a clean rebuild, and a legacy sidecar missing the keys forces one
  unscoped reconcile.
- Cover preprocess-driven drift at the indexer level by substituting the
  resolved rule set directly: a pattern change forces unscoped, a command change
  forces clean.
- Assert the scoped-path epoch cost: resolving inputs walks the tree exactly
  once, and the scoped scan handed those inputs adds no second walk, while a
  scan without pre-resolved inputs still walks once.

## Outcome

The full escalation matrix from the research holds in fast, GPU-free unit tests
over real tmp roots: ignore edits and preprocess-pattern edits classify as
unscoped, content edits (command, options, html_strip) classify as clean, and a
legacy sidecar classifies as one unscoped reconcile. A spy on the gitignore
collector proves the scoped watcher path performs no extra full-tree walk. All
twenty-two new tests pass alongside the existing indexer unit suite.

## Notes

Preprocess drift is exercised through both the pure hashing functions with
directly-constructed rule objects and the indexer classifier with a substituted
resolved rule set, deliberately bypassing the preprocess loader gate. That gate
is being reshaped by the concurrent tri-state and trust-store work, so binding
these tests to the stable resolved-rule-set surface keeps them valid across that
migration. No test doubles stand in for real behavior - the classifier, the
epoch functions, and the ignore-spec resolution all run for real against tmp
roots.
