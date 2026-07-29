---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S09'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# emit per-bucket sub-slice progress and live token-budget state through the forward-entry and forward-exit runtime reporting

## Scope

- `src/vaultspec_rag/indexer/_streaming.py`

## Description

- add the encode telemetry sink protocol and the per-bucket reporter adapter beside the forward-report helpers in `src/vaultspec_rag/indexer/_streaming.py`, threading an optional callback field through the vector-encode, vault-slice, and code-slice request objects into the encoder seam
- bind the adapter at the code path's slice consumption site, mirroring the adjacent forward-callback bindings
- map bucket events onto existing fields only: sub-slice items-done through the forward runtime block, budget and bucket size through the planned-budget seam, one OOM report per rise in the running count; null-safe when no reporter is attached, never raises
- extend the deterministic encoder double with replayed bucket events and add sub-slice progress coverage with a disconnected-adapter guard

## Outcome

Commit `711fe4f7` on branch `encode-batch-adaptivity-s09` (from the two-lane integration merge). Gates each exit 0: ruff check, ruff format --check, ty check, pytest (66 passed on the gate files; 19 on the widened doubles). Guard proven able to fail: with the binding removed the new test fails on its named items-sequence assertion (exit 1); restored it passes (exit 0); the run-restore-run was one uninterrupted scripted sequence with a byte-equality restore check.

## Notes

- Scope grew by a 5-line binding site in `src/vaultspec_rag/indexer/_consumer_pipeline.py`: the reporter reaches the streaming layer only through pre-bound callbacks, so the row's single named file alone would have left the feature dead.
- The sparse encode path is not wired: its encoder method exposes no bucket callback, and adding one would have meant editing the embeddings module owned by another lane; the asymmetry is stated in a comment at the sparse call site.
- Four encoder doubles in other test files widened by the new parameter, mechanically.
- A wider sweep surfaced two failures on the integration branch: the encode-recovery floor guard in the ADR-regression suite (attributed to the bucket lane by A/B against the merge base; fix dispatched) and a jobs-route auth payload assertion that also fails at the merge base (pre-existing on the default branch, not this feature's).
