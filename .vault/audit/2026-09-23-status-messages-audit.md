---
tags:
  - '#audit'
  - '#status-messages'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:169019ef3308c890008fead395be8e9e787e84e997ff635c376b239079bd16d3'
related:
  - "[[2026-09-23-status-messages-plan]]"
  - "[[2026-09-23-status-messages-adr]]"
---

# `status-messages` audit: `status-messages phase reviews`

## Scope

Phase-close and plan-close reviews of `2026-09-23-status-messages-plan` against
`2026-09-23-status-messages-adr`.

**P01 review (commits `bb31e3a5` to `26529f46`, Steps S01 to S03): PASS.**

The review ran on the committed tree, using `git archive HEAD` into a scratchpad, and
covered these checks:

- **Gates:** ruff, ruff format and ty pass. The operator-state tests pass (80).
- **Guard mutations:** both were proven outside the repository.
  - A module-scope torch import fails the torch-free import guard on its named
    assertion.
  - Relaxing the wire base to `extra="ignore"` fails both unknown-field cases.
- **ADR conformance:**
  - Every ADR enum member is present, and the `blocks_start` column is reproduced
    exactly.
  - `blocks_start` matches the previous probe's blocking behaviour.
  - `HealthReport` and `ServiceStateReport` field names match what the server emits
    today.
  - The exit codes have one home.
  - The code carries no development metadata.

## Findings

### wire-contract-forward-compat | medium | Forbidding extras on parse makes a client hard-fail against a newer service

`src/vaultspec_rag/operator_state/_models.py:36-37`

`extra="forbid"` suits the service's own serialisation. The same models are due to be
parsed by `serviceclient` in P04.S06, though. A client one release behind a daemon that
added a health field would then raise `ValidationError` instead of degrading. That turns
a forward-compatible upgrade into an unreachable service.

Owner: P04.S06.

### degradation-member-spelling | low | DegradationReason member names diverge from the ADR list without a ledger note

`src/vaultspec_rag/operator_state/_service.py:133-140`

The ADR enumerates `JOB_STALLED`, while the code has `JOBS_STALLED`. The addition of
`JOBS_DEGRADED` is logged; the rename is not.

Owner: P03.S11.

### client-remediation-rendering | low | A non-defect carries remediation a renderer may present as a fault

`src/vaultspec_rag/operator_state/_installation.py:111-113`

`NOT_APPLICABLE` is not a defect, yet it carries install advice. A renderer that prints
remediation whenever it is present would show every client user a fix for a healthy
installation.

Owner: P05.S08.

### repair-predicate-breadth | low | is_defect is broader than the torch-reinstall predicate

`src/vaultspec_rag/operator_state/_installation.py`

`is_defect` covers `NO_DEVICE`, `MPS_POLICY_REFUSED` and `INTERPRETER_MISSING`, none of
which a torch reinstall fixes. This is resolved in P02.S09 by the separate
`fixed_by_torch_reinstall` property, which the tool-env repair uses. To be confirmed at
the P02 close.

### residual-lifecycle-strings | low | Lifecycle labels and status tokens still live beside the new enum

- `src/vaultspec_rag/serviceclient/_status.py:40-56` still defines `STATUS_*` and
  `LABEL_*` strings that `ServiceLifecycle` now owns.
- `src/vaultspec_rag/cli/_status_render.py:283-297` still derives the state itself.

Planned for deletion in P04.S13.

## Recommendations

- **P04.S06:** decide how a version-mismatched client parses a typed health payload.
  The preferred route is to gate the parse on the existing package-version
  compatibility verdict and fail with that verdict. A tolerant client-side parse would
  change the typed-wire commitment and needs an amendment to
  `2026-09-23-status-messages-adr`.
- **P03.S11:** settle the `DegradationReason` spelling against the ADR text and log it.
- **P05.S08:** gate remediation rendering on `is_defect`, and back it with a test.
