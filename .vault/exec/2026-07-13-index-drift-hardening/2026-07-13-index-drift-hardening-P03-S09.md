---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S09'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# Add trust, untrust, and status verbs to the preprocess group: trust prints the resolved command set and confirms (auto-accept with --yes) then persists the record, untrust removes it, status reports mode, hash, and per-root trust state, all with --json envelopes

## Scope

- `src/vaultspec_rag/cli/_preprocess.py`

## Description

- Add the `trust` verb: resolve rules via the strict loader so the tri-state/TOFU gate cannot hide the very rules being trusted, print the reviewable resolved command set (pattern, command/entry_point, timeout, failure handling), `typer.confirm` unless `--yes`, then persist the record via `record_trust` with a CLI-computed UTC ISO `trusted_at`. Refuse with exit 1 when the config is absent or defines zero valid rules, and exit 1 on an invalid config. `--json` requires `--yes` (exit 2) so no prompt corrupts the envelope.
- Add the `untrust` verb: remove the root's record via `remove_trust` and report whether a record existed (`removed` boolean).
- Add the `status` verb: report mode (`get_config().preprocess_mode`), config presence and validity, rule count, current resolved-rule-set hash, trust-record presence, trusted hash/timestamp, a derived `trust_state` (match/mismatch/absent/not_applicable), and a `would_run` effect, as both human text and a `--json` envelope.
- Fix the `run-one` gated-case UX: detect when the non-strict loader returned empty because the mode/TOFU gate skipped rules (config file present, strict load has rules, non-strict empty) and print the actionable untrusted/off message naming the `preprocess trust` verb instead of the misleading "No preprocess rule matches" line.
- Add module helpers: `_gated_rule_state`, `_gated_run_one_message`, `_resolved_command_set`, `_print_command_set`, `_invocation_label`, `_trust_state`, `_would_run`, `_status_effect_line`.

## Outcome

- Three new verbs (`trust`/`untrust`/`status`) and the gated `run-one` fix land in `src/vaultspec_rag/cli/_preprocess.py`.
- `ruff check` clean and `basedpyright` reports 0 errors on the file.
- Behaviour verified through the S11 CliRunner suite (trust yes/confirm/refusal, untrust both outcomes, status JSON, gated-vs-trusted run-one messaging).

## Notes

- Trust decisions are recorded only through the CLI layer; the loader and spawn worker never prompt (ADR D6 constraint), so the clock dependency (`datetime.now(UTC)`) lives in the CLI, matching `record_trust`'s caller-supplied `trusted_at` contract.
- The `trust`/`status` verbs use the strict loader (gate-bypassing) so an operator can review and trust rules that the default gate would otherwise hide; `run-one` keeps the non-strict loader and distinguishes genuine no-match from a gated-off rule set.
