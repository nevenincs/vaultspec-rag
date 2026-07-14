---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S18'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Update operator docs to the trust-based framing that preprocess config is code execution with operator privileges, removing sandbox/unsandboxed knob references

## Scope

- `docs/preprocessing-hooks.md`

## Description

- Rewrite the security posture of the preprocessing guide to the trust-based framing: a root's preprocess config IS code execution with the operator's privileges; do not index a repo you would not build.
- Keep rule authoring, `on_error`, caps, timeout, cache, and entry_point documentation; drop fail-closed/UNSANDBOXED text.

## Outcome

`docs/preprocessing-hooks.md` states the trust model plainly; bounds documented as hygiene, not a security boundary.

## Notes

Executed by the dispatched low-executor; supervisor verified results.
