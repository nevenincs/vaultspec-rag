---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-14'
body_hash: 'sha256:a5eb07c5af55e1c7e6b783f8cbbf7e910fdc7da384b385bbfc2cdd6729d47342'
step_id: 'S11'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# Cover the new verbs and flags: trust confirm and --yes flows, untrust, status JSON envelope, flag-to-env forwarding, and the reworked \_enable_preprocess fixtures across the CLI test modules

## Scope

- `src/vaultspec_rag/tests/test_cli_preprocess.py`

## Description

- Rework the removed-knob autouse fixture onto the tri-state: isolate `VAULTSPEC_RAG_STATUS_DIR` to a per-test tmp dir (the trust store writes there) and default to `trust_all` so the inspection verbs see rules without a per-root trust act - the equivalent of the deleted enable knob. Add `_default_mode`/`_off_mode` helpers so trust/status tests override to the default (TOFU) or off modes.
- Cover `trust`: `--yes --json` persistence plus a status re-read asserting `trust_state == "match"`; the interactive confirm accept (`input="y"`) and decline (`input="n"`, non-persisting); refusal on an empty config; and `--json` requiring `--yes`.
- Cover the trust-then-run integration: an untrusted root reports `run-one` gated, and after `trust --yes` the same file preprocesses.
- Cover `run-one` gated messaging in both default (untrusted, names the trust verb) and off modes.
- Cover `untrust` both outcomes (removed true / false) and `status` JSON envelopes for untrusted-default, no-config, and off modes.
- Cover the `server start` flag mutual-exclusion error and the flag-to-env forwarding by asserting the `_service_child_env` dict directly (no live daemon): `off` sets `PREPROCESS=off` and drops `TRUST_ALL`, `trust_all` sets `TRUST_ALL=1` and drops `PREPROCESS`, `None` leaves an operator-set var intact.
- Cover the `index` verb flags: the mutual-exclusion error (`preprocess_flags_conflict`), the loud delegating-warning when a service `--port` is targeted (the run proceeds and the flag-ignored warning is emitted), and `_apply_preprocess_env` selecting the resolved `preprocess_mode` (off/trust_all) via a live config read.
- Add a guard test asserting the removed `PREPROCESS_ENABLED` env knob no longer exists on the enum.

## Outcome

- 35 tests pass (`pytest src/vaultspec_rag/tests/test_cli_preprocess.py -q`).
- `ruff check` clean; `basedpyright` reports 0 errors on the file.
- Adjacent CLI suites unaffected: `test_cli_server_start.py` and `test_cli_service_watch.py` (24 tests) stay green after the `service_start` signature change.

## Notes

- One pre-existing test (`test_run_one_human_output_uses_plain_result_language`) asserts exact human-field equality; under the `trust_all` default the loader emits a loud bypass warning that CliRunner mixes into output, so that test was moved to trusted-default mode (trust first, then run-one) where no warning is emitted - a faithful representation of real trusted usage, not a masking change.
- All tests use the real `CliRunner`, a real `.vaultragpreprocess.toml`, and a real extractor script; no mocks of project code, no skips.
