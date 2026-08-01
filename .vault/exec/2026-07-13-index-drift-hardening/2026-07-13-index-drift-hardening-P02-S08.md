---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:44275fd5fb4cc6768d61185aabb58b3b28445b98d07d2ac6659f43aad29a53cf'
step_id: 'S08'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# Rework unit tests off the removed env knob onto the tri-state and trust store: loader enforcement per mode, hash stability across benign edits, hash change on command edits, corrupt-store degradation, status-dir isolation

## Scope

- `src/vaultspec_rag/tests/test_preprocess_config.py`

## Description

- Replace the removed `PREPROCESS_ENABLED` fixture with an autouse fixture that isolates `VAULTSPEC_RAG_STATUS_DIR` to a per-test tmp dir (the trust store writes there) and defaults the resolved mode to `trust_all` so the rule-resolution tests exercise parsing without threading trust plumbing.
- Keep the full rule-resolution suite (ordering, matching, options, entry-point, error policy, strict raises, picklability) running under the trust-all default.
- Add tri-state enforcement tests: `off` yields empty with a debug log, `off` wins over `trust_all`, `trust_all` loads without a record and warns, `default` untrusted yields empty with a verb-naming warning, `default` trusted loads, and a command edit reverts a trusted root to untrusted.
- Add rule-set hashing tests: stable across a comment/whitespace edit, changed on a command edit, changed on an options edit.
- Add trust-store durability tests: corrupt store degrades to untrusted without raising, a record round-trips and is removable, and the store isolates under the status dir (never written into the repo).

## Outcome

29 tests pass. Assertions are real: the mode tests drive the actual loader and assert on returned rules and captured log messages; the hash tests derive expected behaviour from the specification (benign edits equal, command/options edits differ) rather than hardcoding digests; the trust-store tests exercise real disk writes under the isolated status dir. No mocks, skips, or tautologies. A helper obtains the resolved rule set for hashing via `strict=True`, which bypasses the gate and returns the resolved rules regardless of mode.

## Notes

The intentional loud warnings and the corrupt-store degradation warning surface in the captured log output during the run; they are asserted on, not incidental. Sibling test modules that still import the removed enum member are out of scope here and are expected to fail until P03/P04 rework them.
