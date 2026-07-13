---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-14'
step_id: 'S15'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Document the sandbox model, the tri-state control, fail-closed behavior, and the removed trust surface across the README and preprocessing docs

## Scope

- `README.md`

## Description

- Rewrote the README preprocessing-hooks section: hooks run by default under OS
  containment (Windows AppContainer, Linux bubblewrap, macOS `sandbox-exec`) with no
  trust step; documented the fail-closed server posture and the `off` /
  `PREPROCESS_UNSANDBOXED` controls.
- Rewrote the security-posture section of the preprocessing-hooks guide to describe the
  filesystem, network, and secret denials, the per-host backend, fail-closed server
  mode, and the two-knob control surface; removed the trust-on-first-use narrative.
- Augmented the failure-visibility section to name the `/jobs`
  `preprocess_skipped`/`preprocess_failures` fields and the `/reindex` `preprocess`
  pre-flight block as a non-interactive client's window into hook outcomes.
- Updated the configuration reference: replaced the `VAULTSPEC_RAG_PREPROCESS_TRUST_ALL`
  row with `VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED`.
- Reworked the CLI reference: removed the `preprocess trust` and `preprocess untrust`
  sections and their TOC entries, swapped `--preprocess-trust-all` for
  `--preprocess-unsandboxed` on `index` and `server start` (including the
  `preprocess_flags_conflict` exit note and the start-time notice text), and rewrote
  `preprocess status` to document the mode, sandbox backend, and JSON fields.

## Outcome

- `uv run --no-sync prek run --files README.md docs/preprocessing-hooks.md docs/configuration.md docs/cli.md`:
  mdformat, pymarkdown, provider-artifacts, spec-check, and sanitize checks all pass
  (after one mdformat reflow pass).
- Grep confirms zero surviving `preprocess trust`/`untrust`, `PREPROCESS_TRUST_ALL`,
  `--preprocess-trust-all`, or trust-on-first-use references in README or docs; the only
  remaining "trust" wording describes the new model (no trust step / no trust state /
  the fully-trusted-host escape hatch).

## Notes

- Documentation-only change; no source touched. No product bug surfaced.
