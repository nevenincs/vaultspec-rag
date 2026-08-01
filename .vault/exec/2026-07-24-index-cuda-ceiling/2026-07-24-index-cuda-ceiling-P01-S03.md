---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:1036c4fcc96e30fa6eb143c91184aa884371e02e67e3ef6bc1ee05c909ff7e94'
step_id: 'S03'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# add a test asserting document embedding uses the document sub-batch and is independent of the vault and code sub-batches

## Scope

- `src/vaultspec_rag/tests/test_config.py`

## Description

- Added a default/independence test asserting the document sub-batch is `12`
  while vault and code stay `32`, and that document differs from vault.
- Added an env-override test asserting the document knob overrides on its own
  var without perturbing the vault or code sub-batches.

## Outcome

Both tests pass (2 passed). The independence assertion binds the decoupling: a
regression pointing the document path back at `embedding_encode_batch_size` would
fail it.

## Notes

This is a positive test of configuration wiring, not a guard test, so a green run
is sufficient verification; no fail-first proof is required for it.
