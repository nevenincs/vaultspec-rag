---
tags:
  - '#audit'
  - '#status-messages'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:ac9b8044f44514fb840dd486e2292d4ec11a325e6802041a8ed5f080d7dbab64'
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

**P03 review (commits `09404a9e` to `33f87848`; Steps S11, S05, S12 and S16):
revision required.**

The review ran on a clean `git archive HEAD` copy:

- ruff and ruff format pass.
- `ty check src` failed. This was the high finding, and it reopened S11.
- 460 tests across the touched modules pass.

The four named risks were checked and found clean:

- `/health` stays lightweight, and none of its inputs can raise into a 500.
- `service_installation` is unreachable from CLI and MCP paths.
- `degradation_findings` behaviour is preserved.
- `hook_state` is the only derivation of whether hooks run.

After the corrections below, the phase gate passes.

**P04 review (commits `db62e1b7` to `df1a6831`; Steps S06, S13 and S07, plus the S16
corrections): revision required.**

- ruff, ruff format and `ty check src` pass on HEAD.
- 238 tests pass across the touched modules.

These were confirmed clean:

- The discovery file is still deleted only on a confirmed-dead PID.
- The release-mismatch refusal emits one envelope and exits 1 in both modes.
- The MCP path stays torch-free.

After the S13 correction and the S17 changes below, the phase gate passes.

**Final integrated review (P05 close and plan close; commits `799b4dc3` to `e1d656df`):
revision required.**

- ruff, ruff format and `ty check src` pass.
- `docs/cli.md` is current.
- 858 of 859 tests pass.

Confirmed clean:

- The deleted derivations are gone from `src`: `TorchDiagnosis`, the CLI
  `_compute_state`, the `/health` `cuda` flag, and substring degradation matching.
- `InstallRole` has one derivation.
- Remediation is gated on `is_defect`.
- A stopped service renders as one plain line.
- `health_answered` rejects both synthetic probe bodies.
- The torch-free guards exist and name their mutations.
- No development metadata appears in added lines.
- The breaking-change footer covers every wire change.
- The documentation tokens match the code.

After commit `89c799ff`, 1807 tests pass across the touched modules, and the
hooks-predicate guard passes.

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

### gate-type-check-fails | high | `ty check src` failed at the phase close on a stale health key

`src/vaultspec_rag/tests/test_serving_verdict_parity.py:41`

Test fixtures still set the `cuda` key that S11 removed from `ServiceHealth`. The tests
passed, but the tree's type check failed, because each Step had type-checked only its
own touched files.

Resolved: S11 was reopened, and commit `db62e1b7` removed the key from both fixtures.
From S13 onwards, `ty check src` runs over the whole tree at every Step.

### client-older-daemon-skew | medium | A new CLI against an older service reported "index busy" instead of the skew

`src/vaultspec_rag/cli/_status.py`

When a service answers but its state does not parse, `status` fell back to the local
store. The service holds that store, so the fallback reported the index as busy.

Resolved in the S16 corrections commit:

- `status` now refuses with the release-mismatch verdict and its restart remediation.
- It exits 1 in both human and JSON mode.

A mutation-checked test covers it.

### preprocess-service-mode-untested | medium | The service-mode read on `preprocess status` had no test

`src/vaultspec_rag/cli/_preprocess.py`

Resolved in the S16 corrections commit, with tests for three cases against a real
loopback stub:

- a running service's `off` mode is read;
- an unparseable health payload gives no mode;
- with no service answering, the local mode applies.

The service-read guard is mutation-checked.

### health-lightweight-guard | low | Nothing held `/health` off the installation and hardware probes

`src/vaultspec_rag/tests/test_status_service_skew.py`

Resolved: a runtime guard now asserts that a `/health` request leaves the installation
and hardware caches empty. It is mutation-checked.

### port-health-sentinel-reads-running | high | A hung or 5xx service reported running and exited 0

`src/vaultspec_rag/cli/_status_render.py`

The port-only lifecycle accepted any health body carrying a `status` string. That
included the transport's synthetic probe-timeout and HTTP-error bodies, so a wedged or
erroring service read as running.

Resolved: S13 was reopened, and commit `2c9bd93d` fixed it.
`serviceclient/_transport.health_answered` now lives beside the transport that makes
those bodies, and rejects both. Each sentinel has a mutation-checked test.

### error-health-exits-zero | medium | A service whose own verdict is `error` exits 0

`src/vaultspec_rag/cli/_status_render.py`

A genuine `HealthVerdict.ERROR` body maps to `ServiceLifecycle.RUNNING`, so it exits 0.
The accepted decision only requires that paused and degraded no longer read as
unreachable.

Owner: the plan-close amendment to `2026-09-23-status-messages-adr`. It decides
whether the health verdict can raise the broker exit code, or whether lifecycle alone
owns the exit code.

### doctor-starting-exit-weight | medium | A starting daemon changed `server doctor` from exit 1 to exit 0

`src/vaultspec_rag/cli/_service_doctor.py`

Liveness now comes from `ServiceLifecycle.is_live`, which includes `STARTING`. The
envelope reports `ok: false` with status `starting`, but the exit code dropped to 0.

Resolved in part: S17 pinned the status and label with a mutation-checked test. The
exit-code change is recorded for the same plan-close amendment.

### residual-stopped-literals | medium | The stopped branch hand-spelled the lifecycle

`src/vaultspec_rag/cli/_status_render.py`

Resolved in S17 (`56201736`): the stopped branch's error, state, label and exit code now
all come from `ServiceLifecycle.STOPPED`.

### docs-state-tokens-stale | medium | Published state-token tables contradict the wire

These pages still document the old tokens:

- `docs/service-discovery.md` (its state and exit-code table);
- `docs/cli.md`;
- `docs/service-mode.md`;
- `docs/automation.md`.

Owner: P05.S18.

### doctor-live-word-contradiction | low | The doctor rendered "running (starting ...)"

Resolved in S17: the live-service axis prints the lifecycle's sentence, and the overall
label names a starting service.

### doctor-duplicate-import | low | ServiceLifecycle was imported twice in the doctor

Resolved in S17.

### toolerror-branch-untested | low | The MCP unreadable-state refusal has no test

`src/vaultspec_rag/mcp/_tools.py`

The refusal shares `parse_report`'s tested fail-closed behaviour, but no test drives the
tool's `ToolError` branch. Recorded, not yet addressed.

### tui-lifecycle-vocab | low | The TUI holds its own "unreachable" vocabulary

Owner: P05.S14. Its scope has been widened to the TUI header and cells.

### hooks-predicate-guard-red | high | A committed guard test failed at HEAD

`src/vaultspec_rag/cli/_status_labels.py`

S17's `preprocess_mode_label` compared the reported mode against `"off"`. That
re-derived whether hooks run, and the single-derivation guard caught it after the P04
close.

Resolved in `89c799ff`: the label is now a table keyed by mode over the parsed
`ServiceFeatures`, and the guard passes.

### adr-verbose-full-probe | high | `status --verbose` never ran the verifying probe

`src/vaultspec_rag/cli/_status.py`

Resolved in `89c799ff`:

- `--verbose` now probes the daemon interpreter at the verify depth, and its help says
  so.
- A mutation-checked test asserts that the verbose view never reports the unverified
  `build_present` state.

### duplicate-feature-label-derivations | high | Feature labels were produced twice, once typed and once from raw dicts

`src/vaultspec_rag/cli/_status_labels.py`, `src/vaultspec_rag/cli/_status.py`

Resolved in `89c799ff`. Server status parses the health payload's feature section into
`ServiceFeatures`, and one producer per feature renders it. Project status calls the
same producers. A section this build cannot read renders as not reported.

### tui-condition-vocabulary | medium | The jobs view's condition pill keeps its own words

`src/vaultspec_rag/cli/_jobs_tui_header.py`, `src/vaultspec_rag/cli/_jobs_tui_cells.py`

The header's `healthy`, `degraded` and `stalled` pill summarises the job set's
degradation tallies, which is a different concept from the service's `HealthVerdict`.
Its `unreachable` names a failed fetch, not a lifecycle state. Mapping it onto the
service vocabulary would describe jobs with words about the service. S14 already moved
the service-health tones onto `HealthVerdict`.

Recorded and not changed. A later change could give job health its own enum.

### benchmark-docstring-alias-key | low | A docstring named a deleted key

Resolved in `89c799ff`.

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
- **Plan close:** amend the accepted decision's `DegradationReason` member list to the
  emitted codes: `JOBS_STALLED` (plural) and the added `JOBS_DEGRADED`. The accepted
  record should match the wire.
- **P05.S18:** the release note states that the service reads its installation once
  per process lifetime. A torch or driver change shows only after a restart.
- **Plan close:** the same amendment to `2026-09-23-status-messages-adr` should record
  two exit-code decisions:
  - whether an `error` health verdict or a health-probe failure raises the broker exit
    code;
  - that `server doctor` exits 0 for a starting daemon.
- **Plan completion:** all 18 Steps are closed, and every critical and high finding is
  resolved. The only open items are decision-level and need authorization. They are
  covered by the proposed amendment `2026-09-23-status-messages-exit-codes-adr`:
  - the `DegradationReason` member list;
  - the broker exit code for an `error` health verdict;
  - `server doctor`'s exit code for a starting daemon.
