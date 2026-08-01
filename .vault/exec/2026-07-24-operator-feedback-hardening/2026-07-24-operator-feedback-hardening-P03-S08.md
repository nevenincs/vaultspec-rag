---
tags:
  - '#exec'
  - '#operator-feedback-hardening'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:2fd4051a57f8d788766aedec7d29bd4f20918faab3b43f12b98fab18e96db44d'
step_id: 'S08'
related:
  - "[[2026-07-24-operator-feedback-hardening-plan]]"
---

# Measure the vector store volume in the index disk pre-flight

## Scope

- `src/vaultspec_rag/index_profiles.py`

## Description

- Probe the volume the vector store actually occupies, mirroring the store's own backend selection.
- Add a separately labelled condition for the indexed project's own data directory, and defer it when both land on one volume.
- Report the path, the volume, and the role in the refusal, and stop repeating the error kind.

## Outcome

An index that fits is no longer refused. Verified on the reporting machine, where the previous check measured a volume with 33.67 GiB free while the store's had 276.85 GiB: the same invocation that had been refused was accepted.

## Notes

Volume identity is the filesystem device id, not the rendered path anchor. The first implementation compared anchors, which works on Windows but makes every absolute path compare equal on POSIX, so the second condition would have been silently inert on Linux while passing green. The test caught it. A remote vector service reports unknown and skips the check rather than deciding on an unrelated local volume. The host floor was separately rederived from measured occupancy.
