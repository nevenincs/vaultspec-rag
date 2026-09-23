---
tags:
  - '#audit'
  - '#status-messages'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:2321c4045654e44e72821d4908af04fa7d5794fcc59366c6279f41541e8f7215'
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

**P02 review (commits `9635adca` to `b6094779`; Steps S09, S04, S10 and S15): PASS.**

The review ran on a clean `git archive HEAD` copy and covered these checks:

- **Gates:** ruff, ruff format and ty pass. 327 unit tests across the touched modules
  pass.
- **Doctor:** the doctor torch-free guard passes.
- **Behaviour parity:** the deleted exit-code mapping is preserved. Codes 3, 4, 5, 6
  and 7 block a start, and a timeout warns and proceeds.
- **`repair-predicate-breadth`:** confirmed closed, because the tool-env repair gates
  on `fixed_by_torch_reinstall`.

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

### client-install-reads-as-not-ready | medium | The readiness torch axis called a torch-free client a defect

`src/vaultspec_rag/_readiness.py`

`_torch_readiness` mapped `NOT_APPLICABLE` to `NOT_READY`, so a client read as not
ready in `server doctor --json`. Resolved in the P02 corrections commit:

- a client reads ready;
- a defect reads not ready;
- an unverified or unknown capability reads unknown.

A mutation-checked test covers it.

### readiness-info-shape-break | medium | Wire shapes changed outside the ADR's declared breaking surface

`src/vaultspec_rag/_readiness.py`, `src/vaultspec_rag/_gpu_admission.py`

- **`/readiness` and `server doctor --json`:** the torch `info` is now the
  `ComputeReport` fields.
- **Device-load admission:** the reasons `no_cuda` and `torch_absent` are now
  `no_device` and `torch_missing`.

No in-repo consumer reads the old keys. Owner: P05.S18 release note.

### gpu-error-classifies-in-process | medium | Two sibling paths answered the same question by different means

`src/vaultspec_rag/cli/_gpu_errors.py`

Resolved in the P02 corrections commit:

- The error handler now classifies the torch its own failed compute path already
  loaded.
- It falls back to the canonical in-process classifier only when none is loaded.
- Its docstring records why it does not ask a child interpreter.

### duplicate-remediation-prose | medium | GPU error messages restated conditions the enum owns

`src/vaultspec_rag/cli/_gpu_errors.py`

Resolved in the P02 corrections commit. The message headlines now come from the
`ComputeCapability` labels. The topology-specific troubleshooting body stays with
the error handler, which is the only place that renders it.

### host-dependent-mps-test | medium | The MPS error-handler test only worked where torch is installed

`src/vaultspec_rag/tests/test_cli_install.py`

Resolved in the P02 corrections commit. The handler classifies the loaded torch
module directly, so the test's substituted module reaches the classifier whatever is
installed on the host.

### probe-low-followups | low | Local-tag, falsy-model, remediation and timeout gaps

Resolved in the P02 corrections commit:

- a `cpu`-prefixed local tag now classifies as CPU-only;
- the compute default uses `is None`;
- a blocking capability without remediation raises instead of rendering `"None"`;
- the probe timeout branch has a mutation-checked test.

`operator_state/_hardware.py` still has no production caller. It is owned by P03.S16
and must not close the plan uncalled.

## Recommendations

- **P04.S06:** decide how a version-mismatched client parses a typed health payload.
  The preferred route is to gate the parse on the existing package-version
  compatibility verdict and fail with that verdict. A tolerant client-side parse would
  change the typed-wire commitment and needs an amendment to
  `2026-09-23-status-messages-adr`.
- **P03.S11:** settle the `DegradationReason` spelling against the ADR text and log it.
- **P05.S08:** gate remediation rendering on `is_defect`, and back it with a test.
- **P05.S18:** the release note covers every wire change: `status --json`,
  `/health`, `/service-state`, `get_index_status`, the `/readiness` torch `info`
  shape, and the admission reason values.
