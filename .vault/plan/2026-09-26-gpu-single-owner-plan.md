---
tags:
  - '#plan'
  - '#gpu-single-owner'
date: '2026-09-26'
tier: L2
related:
  - '[[2026-09-26-gpu-single-owner-adr]]'
  - '[[2026-07-24-service-quiesce-adr]]'
  - '[[2026-09-04-cuda-provisioning-adr]]'
  - '[[2026-09-23-status-messages-adr]]'
  - '[[2026-07-14-tool-env-gpu-continuity-adr]]'
  - '[[2026-09-26-tool-upgrade-cycle-adr]]'
modified: '2026-09-26'
body_schema: body-v2
body_hash: 'sha256:0ec39a85894cfc1319524346798472474b77c295b19166e581924f4e89a7dd62'
---

# `gpu-single-owner` plan

Enforce one GPU owner per machine, and make install and doctor give one correct repair per condition.

## Description

Approved 2026-09-26. Basis: after the audit in `2026-09-26-gpu-single-owner-audit`
was presented, the user directed "no local fallback if gpu is already held. this
is a critical fix target. Fix all high and medium", covering every critical, high
and medium finding and the stated fix direction of a machine-wide GPU owner lock
enforced at the model-load choke point.

Phase P01 implements `2026-09-26-gpu-single-owner-adr`, which carries out the
local-fallback and borrower rules of `2026-07-24-service-quiesce-adr` for every
path and release. Phase P02 is execution within settled decisions:
`2026-09-04-cuda-provisioning-adr` (the repair pins the installed version and
hands over a command; holders are reported), `2026-07-14-tool-env-gpu-continuity-adr`
(the receipt-carrying durable wheel), and `2026-09-23-status-messages-adr` (typed
enums own labels and remediation; doctor, the post-install warning and the start
preflight consume the same verdicts). No new decision is needed for P02; the pin
stays and its consequence is disclosed.

The low-severity platform findings are addressed only where the canonical command
builder of P02.S06 needs them to avoid printing a wheel URL that cannot exist.
Free-threaded interpreter support and network verification of wheel URLs stay out
of scope.

Phase P03 added 2026-09-26. Basis: asked why the repair keeps a potentially stale
CUDA pin, the user directed "keep investigating and hardening - the install
upgrade cycle must be a persistent and dependable automanagement cycle". P03
implements `2026-09-26-tool-upgrade-cycle-adr`, grounded in
`2026-09-26-tool-upgrade-cycle-research`, which replaces the direct-wheel pin
(`2026-07-14-tool-env-gpu-continuity-adr` O-A1) and the version pin
(`2026-09-04-cuda-provisioning-adr` D3) that P02.S06 and P02.S07 built on; the
remaining decisions of both records stand.

## Steps

### Phase `P01` - one GPU owner per machine

Makes it impossible for any process, release or configuration to load a model stack while another process owns the machine's GPU, except the process tree the owner has lent it to.

- [x] `P01.S01` - add the canonical own-process lineage query (pid and start time of this process and its ancestors) to the process probe; `src/vaultspec_rag/_process_probe.py`.
- [x] `P01.S02` - resolve one machine-global GPU anchor directory, create shared anchors lockable by every account with a read-only fallback, and move the load-window anchor into it; `src/vaultspec_rag/_anchor_claim.py, src/vaultspec_rag/_gpu_admission.py`.
- [x] `P01.S03` - add the torch-free GPU ownership module (claim, observe, lend, reclaim, legacy owner detection, typed refusal) and enforce it in load_accelerator before admission; `src/vaultspec_rag/_gpu_owner.py, src/vaultspec_rag/_gpu.py`.
- [x] `P01.S04` - lend the GPU to a bound borrower and reclaim it on resume or lease loss, and observe ownership in the server start preflight; `src/vaultspec_rag/_service_borrower.py, src/vaultspec_rag/_service_residency.py, src/vaultspec_rag/gpu_borrow_lease.py, src/vaultspec_rag/cli/_service_start.py`.
- [x] `P01.S05` - refuse a mandated local search before it runs when another process owns the GPU, and render the typed refusal on every local compute path; `src/vaultspec_rag/cli/_search.py, src/vaultspec_rag/cli/_gpu_errors.py`.

### Phase `P02` - one voice for install and doctor remediation

Makes install, doctor, status and start give one correct, exact repair per condition, list only real holders, and never report a refused install as a success.

- [x] `P02.S06` - move install-topology classification into operator_state, detect uv tool environments by their receipt with one non-resolving environment root, and build every tool CUDA command from one platform-checked builder; `src/vaultspec_rag/operator_state/, src/vaultspec_rag/commands/_tool_torch.py, src/vaultspec_rag/cli/_gpu_errors.py, src/vaultspec_rag/cli/_service_start.py`.
- [x] `P02.S07` - state the version pin in the tool repair and replace every uv tool upgrade recommendation with a command that upgrades while keeping the CUDA wheel; `src/vaultspec_rag/commands/_tool_torch.py, src/vaultspec_rag/cli/_service_doctor.py, docs/`.
- [x] `P02.S08` - render a refused install as refused, once: correct headline and action, no duplicated warnings, no second torch diagnosis, no rows for steps that never ran; `src/vaultspec_rag/commands/_install.py, src/vaultspec_rag/cli/_install.py, src/vaultspec_rag/cli/_render.py`.
- [x] `P02.S09` - exclude the invoking launch chain from environment holders, pair launcher and interpreter, name each holder's role, and count what could not be inspected; `src/vaultspec_rag/_process_probe.py, src/vaultspec_rag/commands/_tool_torch.py`.
- [x] `P02.S10` - make doctor print the exact repair for the daemon interpreter and report that environment's holders in both human and JSON output; `src/vaultspec_rag/cli/_service_doctor.py, src/vaultspec_rag/_readiness.py`.

### Phase `P03` - one self-sustaining install and upgrade cycle

Makes a uv tool GPU host stay on CUDA and stay upgradable across every uv tool upgrade, with a receipt-carried CUDA source and in-place repair the product can run itself on consent.

- [ ] `P03.S11` - add the typed tool-receipt verdict to operator_state and rebuild the command builder on the receipt-carried CUDA index and first-match strategy: an in-place torch-only repair and a bare upgrade, deleting the direct-wheel and version-pin machinery; `src/vaultspec_rag/operator_state/, src/vaultspec_rag/commands/_tool_torch.py`.
- [ ] `P03.S12` - make install treat a non-durable receipt as needing the repair, run the in-place repair itself on consent and verify compute and receipt afterwards, and hand over the command otherwise; `src/vaultspec_rag/commands/_install.py, src/vaultspec_rag/commands/_tool_torch.py, src/vaultspec_rag/cli/_install.py`.
- [ ] `P03.S13` - report the receipt verdict and its one command in doctor and status, and derive every upgrade recommendation, including the restart it needs, from the builder; `src/vaultspec_rag/cli/_service_doctor.py, src/vaultspec_rag/cli/_status.py, src/vaultspec_rag/cli/_service_start.py`.
- [ ] `P03.S14` - prove the cycle against real uv with loopback stand-in wheels: a receipt written with the options is durable, the repair applies in place under a live holder, and a bare upgrade keeps the CUDA build; `src/vaultspec_rag/tests/`.
- [ ] `P03.S15` - install uv tool hosts with the CUDA index and first-match strategy in the documentation, and document upgrading as uv tool upgrade followed by a service restart; `docs/, README.md`.

## Parallelization

P01.S01 lands first because P02.S09 consumes the lineage query it adds. After it,
Phase P01 (orchestrator) and Phase P02 (one executor) run in parallel in the same
worktree with disjoint write ownership: P01 owns `_anchor_claim.py`,
`_gpu_admission.py`, `_gpu_owner.py`, `_gpu.py`, `_service_borrower.py`,
`cli/_search.py` and the `_handle_gpu_error` branch in `cli/_gpu_errors.py`; P02
owns every other path it names. The one shared file, `cli/_service_start.py`, is
split by function: P01.S04 edits only the machine-owner preflight and P02.S06 only
the compute preflight and ephemeral warnings. Each Step commits its own paths by
explicit pathspec. Within each Phase, Steps run in order.

Phase P03 starts only after P02 closes, because it rewrites the command builder
and the install, doctor and start surfaces P02 owns; one executor carries it
serially.

## Verification

- With the GPU owner anchor held by another process, `load_accelerator` raises the
  typed ownership refusal before admission; a guard test proves it fails when the
  check is removed.
- A process whose ancestor is named as the borrower in the owner record is
  admitted; an unrelated process is refused.
- A held storage-scoped identity lock with a free owner anchor is refused as a
  legacy owner.
- `search --allow-fallback` beside a live owner exits non-zero with one
  `gpu_owned` envelope in JSON mode and never loads a model.
- A live check on this machine: with the running service holding the GPU, a local
  search from this branch refuses.
- A blocked install prints one refusal with one command, no success headline, and
  no holder that is the invoking command or its launcher.
- Doctor prints the exact repair for a CPU-only daemon interpreter.
- A tool host installed with the documented command, and one repaired by the
  product, both carry a durable receipt, and a bare `uv tool upgrade` against real
  uv keeps the CUDA build while moving the release.
- The repair applies in place while a process holds the environment, and no path
  replaces an environment wholesale.
- Lint, format, type-check and the tests covering every touched path pass at each
  Step; the P01, P02 and P03 Phase closes each pass an integrated review recorded
  in the audit.
