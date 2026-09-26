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
modified: '2026-09-26'
body_schema: body-v2
body_hash: 'sha256:60a062b1357968cc6ac2d3e2a0785f9e6bb03456f1ab237ec9720a4f8dca2b72'
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

## Steps

### Phase `P01` - one GPU owner per machine

Makes it impossible for any process, release or configuration to load a model stack while another process owns the machine's GPU, except the process tree the owner has lent it to.

- [x] `P01.S01` - add the canonical own-process lineage query (pid and start time of this process and its ancestors) to the process probe; `src/vaultspec_rag/_process_probe.py`.
- [x] `P01.S02` - resolve one machine-global GPU anchor directory, create shared anchors lockable by every account with a read-only fallback, and move the load-window anchor into it; `src/vaultspec_rag/_anchor_claim.py, src/vaultspec_rag/_gpu_admission.py`.
- [ ] `P01.S03` - add the torch-free GPU ownership module (claim, observe, lend, reclaim, legacy owner detection, typed refusal) and enforce it in load_accelerator before admission; `src/vaultspec_rag/_gpu_owner.py, src/vaultspec_rag/_gpu.py`.
- [ ] `P01.S04` - lend the GPU to a bound borrower and reclaim it on resume or lease loss, and observe ownership in the server start preflight; `src/vaultspec_rag/_service_borrower.py, src/vaultspec_rag/cli/_service_start.py`.
- [ ] `P01.S05` - refuse a mandated local search before it runs when another process owns the GPU, and render the typed refusal on every local compute path; `src/vaultspec_rag/cli/_search.py, src/vaultspec_rag/cli/_gpu_errors.py`.

### Phase `P02` - one voice for install and doctor remediation

Makes install, doctor, status and start give one correct, exact repair per condition, list only real holders, and never report a refused install as a success.

- [ ] `P02.S06` - move install-topology classification into operator_state, detect uv tool environments by their receipt with one non-resolving environment root, and build every tool CUDA command from one platform-checked builder; `src/vaultspec_rag/operator_state/, src/vaultspec_rag/commands/_tool_torch.py, src/vaultspec_rag/cli/_gpu_errors.py, src/vaultspec_rag/cli/_service_start.py`.
- [ ] `P02.S07` - state the version pin in the tool repair and replace every uv tool upgrade recommendation with a command that upgrades while keeping the CUDA wheel; `src/vaultspec_rag/commands/_tool_torch.py, src/vaultspec_rag/cli/_service_doctor.py, docs/`.
- [ ] `P02.S08` - render a refused install as refused, once: correct headline and action, no duplicated warnings, no second torch diagnosis, no rows for steps that never ran; `src/vaultspec_rag/commands/_install.py, src/vaultspec_rag/cli/_install.py, src/vaultspec_rag/cli/_render.py`.
- [ ] `P02.S09` - exclude the invoking launch chain from environment holders, pair launcher and interpreter, name each holder's role, and count what could not be inspected; `src/vaultspec_rag/_process_probe.py, src/vaultspec_rag/commands/_tool_torch.py`.
- [ ] `P02.S10` - make doctor print the exact repair for the daemon interpreter and report that environment's holders in both human and JSON output; `src/vaultspec_rag/cli/_service_doctor.py, src/vaultspec_rag/_readiness.py`.

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
- Lint, format, type-check and the tests covering every touched path pass at each
  Step; the P01 and P02 Phase closes each pass an integrated review recorded in the
  audit.
