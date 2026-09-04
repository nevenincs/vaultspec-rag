---
tags:
  - '#plan'
  - '#cuda-provisioning'
date: '2026-09-04'
tier: L3
related:
  - '[[2026-09-04-cuda-provisioning-adr]]'
  - '[[2026-09-04-cuda-provisioning-research]]'
  - '[[2026-07-14-tool-env-gpu-continuity-adr]]'
modified: '2026-09-04'
body_schema: body-v2
body_hash: 'sha256:8ad0fd6bce75f37e11e9f218188839cb9510f12ab6baf7056a229c0c0a2ea497'
---

# `cuda-provisioning` plan

## Description

This plan executes `2026-09-04-cuda-provisioning-adr`, grounded in
`2026-09-04-cuda-provisioning-research`. It closes a field failure in which the durable
CUDA pin destroyed a tool environment, and the proof gap that let the shape ship: the
repair transaction replaces an environment from inside it, the guard in front of it
watches the machine service rather than the environment's holders, and no test has ever
observed real uv acting on a held environment.

The work moves in four beats. Holder detection answers who holds an environment, by image
path and working directory, failing closed. The proof harness stages hostile conditions
against real uv without touching a live installation. The repair transaction then loses
its destructive in-environment invocation and gains a refusal that names holders and hands
over the command, along with consent and scope that match what it actually does. The
remaining waves correct defect classification, collapse the duplicated pin version, report
holders in readiness, give the Windows proofs a pull-request home, and correct the
operator-facing account.

Two Steps, `W03.P03.S07` and `W03.P03.S08`, are absorbed from the `tool-mode-cuda` plan,
whose earlier Steps landed in commit `bb5f0532` and remain recorded there.

## Steps

## Wave `W01` - holder detection

Answer which live processes hold a target environment, by image path and working directory, failing closed on any observation that cannot be made.

### Phase `W01.P01` - enumeration

Add the holder query and prove it against real holders.

- [x] `W01.P01.S01` - Add a fail-closed holder query returning the live processes whose image path or working directory resolves under a given environment root; `src/vaultspec_rag/_process_probe.py`.
- [x] `W01.P01.S02` - Prove the holder query against real image-path, working-directory and uninspectable holders; `src/vaultspec_rag/tests/test_env_holders.py`.

## Wave `W02` - proof harness

Stage hostile provisioning conditions against real uv without touching a live installation.

### Phase `W02.P02` - hostile fixtures

Build the redirected environment, the loopback wheel index, and the holder subprocess helper, then prove they reproduce the real failures.

- [x] `W02.P02.S03` - Add the redirected uv environment fixture, a loopback wheel index serving stand-in distributions, and a holder subprocess helper; `src/vaultspec_rag/tests/_uv_env_harness.py`.
- [x] `W02.P02.S04` - Prove the harness reproduces the held-environment destruction, the resolve-stage safe failure, and a real uv receipt the matcher accepts; `src/vaultspec_rag/tests/test_tool_env_provisioning_hostile.py`.

## Wave `W03` - repair transaction

Reshape the repair so it never replaces an environment from inside it, and so its consent and scope match what it actually does.

### Phase `W03.P03` - refusal contract

Remove the destructive in-environment invocation, constrain consent and scope, and prove every branch.

- [x] `W03.P03.S05` - Replace the in-environment reinstall with a holder preflight that refuses and hands over the exact command; `src/vaultspec_rag/commands/_tool_torch.py`.
- [x] `W03.P03.S06` - Separate repair consent from the file-overwrite flag and constrain repair scope to the torch wheel, preserving installed version and receipt extras; `src/vaultspec_rag/commands/_install.py and src/vaultspec_rag/cli/_install.py`.
- [ ] `W03.P03.S07` - Render every repair outcome in human mode, not only under JSON; `src/vaultspec_rag/cli/_render.py`.
- [ ] `W03.P03.S08` - Prove repair safety and receipt postconditions, including that a refusal launches no uv child; `src/vaultspec_rag/tests/test_tool_torch_repair.py`.

## Wave `W04` - classification and canonical pin

Stop reading a deliberate torch-free install as defective, collapse the duplicated pin version, and surface holders before an operator acts.

### Phase `W04.P04` - install correctness

Correct defect classification, the pin version source, and readiness reporting.

- [ ] `W04.P04.S09` - Treat torch absent by design as a state rather than an installation defect; `src/vaultspec_rag/cli/_process.py`.
- [ ] `W04.P04.S10` - Collapse the torch pin version to the single lockfile-backed derivation; `src/vaultspec_rag/torch_config/_constants.py and tools/binaries/torch_channel.py`.
- [ ] `W04.P04.S11` - Report environment holders as an informational readiness dimension; `src/vaultspec_rag/_readiness.py`.

## Wave `W05` - operator surfaces

Give the Windows proofs a pull-request home and correct the operator-facing account of what fails and how.

### Phase `W05.P05` - gating and documentation

Add the hosted Windows leg and correct the installation account.

- [ ] `W05.P05.S12` - Add the hosted Windows pull-request leg covering the provisioning proof class; `.github/workflows/ci.yml`.
- [ ] `W05.P05.S13` - Correct the installation account of what a blocked reinstall does, what a bad wheel URL returns, and how a repair is refused; `docs/installation.md and README.md`.

## Parallelization

`W01` and `W02` are independent and may run concurrently: holder detection touches the
process-probe surface, the harness touches only the test tree. `W03` depends on both -
the refusal needs the holder query, and its proofs need the harness. Within `W04`,
`W04.P04.S09` and `W04.P04.S10` are independent of everything else and may be taken at any
point; `W04.P04.S11` depends on `W01`. `W05.P05.S12` depends on `W02` existing to have
something to gate, and `W05.P05.S13` depends on `W03` having settled the behaviour it
describes.

## Verification

Each Step runs its own gates before it is marked: formatter, linter, type-check over the
files touched, and the tests covering the branches touched. Guard Steps carry an
additional obligation from the guard-tests rule - the guard is broken, the test is watched
failing on its named assertion, and the guard is restored, in one uninterrupted sequence
recorded in the Step Record.

The campaign is complete when every Step is checked, the vault checks pass clean, and
three campaign-level properties hold: no test in the suite mutates a live uv installation
or the operator's tool directory, the repair transaction contains no path that invokes a
whole-environment replacement from inside the environment it targets, and a receipt
written by real uv is accepted by the production matcher.
