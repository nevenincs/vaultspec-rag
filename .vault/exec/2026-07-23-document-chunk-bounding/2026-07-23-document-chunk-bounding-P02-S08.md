---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-27'
body_hash: 'sha256:021b5f6206392d7b570ee1fd5ec806262dba709edb95b7aa739b039fa76ab26a'
step_id: 'S08'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# pass the fragment discriminator from chunk construction into point identity derivation

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

- Pass the enumerated fragment ordinal from the units-branch fragment loop into `document_point_id` in `src/vaultspec_rag/indexer/_chunk_worker.py`.

## Outcome

Chunk construction and identity derivation agree on the discriminator; enumeration order is deterministic so unchanged files replay to identical ids.

## Notes

Template evidence: intro_commit=2b44d249d2461916216580e2c02d7162013b3ccd; template_commit=2b44d249d2461916216580e2c02d7162013b3ccd:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
