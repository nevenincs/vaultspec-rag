---
tags:
  - '#audit'
  - '#gpu-single-owner'
date: '2026-09-26'
modified: '2026-09-26'
body_schema: 'body-v2'
body_hash: 'sha256:24f0ae9740b1b048223df0725e6eb54e78c2a3f6ba3f62cabeaa70cbfdbd3599'
related: []
---

# `gpu-single-owner` audit: `install upgrade output and GPU single-owner audit`

## Scope

A field run of `vaultspec-rag install --upgrade` from a 0.4.35 `uv tool`
environment against the workspace `Y:\code\cadrumo-worktrees\mcp` refused with a
tool CUDA repair, listed four holder pids, and printed three different repair
commands. This audit traces that output through the 0.4.35 wheel and the 0.5.2
source on `chore/deps-upgrade-hf-hub-2` (`d18045e8`), verifies the holder list
against the live process table, and audits whether the product can put a second
model stack on the machine's GPU while a service of any release already owns it.

Live facts at audit time: the tool environment carries `torch 2.14.0+cpu`; the
only CUDA compute process is a 0.4.35 daemon run from a development virtual
environment on port 8776; roughly twelve MCP stdio adapters from several
environments hold no CUDA.

## Findings

### local-compute-bypasses-live-singleton | critical | a local search loads a second model stack beside a live service

With a local mandate (`--allow-fallback` or local-only mode) the search router
runs the in-process search with no machine-lock check, and against a daemon of
another release it deliberately leaves that daemon alone and runs locally
(`src/vaultspec_rag/cli/_search.py:1366-1379`). The in-process path reaches the
full model stack through `load_accelerator` (`src/vaultspec_rag/_gpu.py:164`),
whose admission compares free memory against a floor and nothing else. On the
audited 16 GiB card 12.4 GiB was free, so a second stack would have been
admitted. The accepted quiesce decision already forbids local GPU allocation
beside a live singleton; the code does not enforce it.

### singleton-scoped-to-storage | high | the service singleton is per storage directory, not per GPU

`machine_lock_path` derives the identity lock from the configured Qdrant storage
directory (`src/vaultspec_rag/_machine_lock.py:155-160`), so a second storage
directory, or a different home directory, yields a second lock and a second
daemon on the same device. The GPU borrower anchor inherits the same derivation
(`src/vaultspec_rag/gpu_borrow_lease.py:108-110`).

### python-api-loads-without-owner | medium | the Python API loads models with no ownership check

`search_*` and `index*` reach `get_registry()` and the model loaders with no
daemon or ownership check (`src/vaultspec_rag/api.py:455-610`).

### admission-is-free-memory-only | medium | GPU admission asks about room, never about ownership

The load window brackets only `set_per_process_memory_fraction`
(`src/vaultspec_rag/_gpu.py:164-182`); the models are constructed after it is
released, so two processes can both be admitted. The window anchor lives in
`tempfile.gettempdir()` (`src/vaultspec_rag/_gpu_admission.py:564-572`), which
moves with `TEMP`, `TMPDIR` and the user.

### tool-repair-commands-disagree | high | one run prints three different repair commands

The blocked install prints the pinned repair from
`src/vaultspec_rag/commands/_tool_torch.py:395`, then the post-install warning
prints an unpinned durable command and an in-place `uv pip` command from
`src/vaultspec_rag/cli/_gpu_errors.py:106,122`; `server start` and the ephemeral
warnings print further variants
(`src/vaultspec_rag/cli/_service_start.py:574,581,963,990`).

### pinned-repair-freezes-tool | high | the pinned repair makes `uv tool upgrade` a no-op

The repair pins the installed version, as the accepted provisioning decision
requires. uv records that `==` pin in the receipt, and a later `uv tool upgrade`
answers "Nothing to upgrade" (reproduced with an isolated tool directory). The
doctor's version-floor advice to run `uv tool upgrade vaultspec-rag`
(`src/vaultspec_rag/cli/_service_doctor.py:314`) then does nothing, and nothing
tells the operator the pin exists.

### blocked-install-reads-as-success | medium | a refused install renders a success headline and duplicate text

The blocked path hard-codes `action="install"`
(`src/vaultspec_rag/commands/_install.py:875`), so the report opens with
"vaultspec-rag installed" over a run that wrote nothing; "PyTorch configuration:
not changed" is the default of a step that never ran; the refusal detail and
command are copied into `warnings` (`src/vaultspec_rag/commands/_install.py:877-879`)
and printed twice; the post-install warning then probes the same interpreter again
(`src/vaultspec_rag/cli/_install.py:426-429`) and advises stopping a service the
environment does not run.

### holder-list-includes-self | medium | the holder scan lists the invoking command and its launcher

`_handoff_outcome` scans with no exclusion
(`src/vaultspec_rag/commands/_tool_torch.py:322`). Running the 0.4.35 scan from
inside the environment listed its own pid and its venv launcher parent. The list
shows the image path only, so a launch-path holder reads as the shared base
interpreter, and launcher and child are not paired.

### doctor-remediation-dead-end | medium | status defers to doctor for a command doctor never prints

`ComputeCapability.CPU_ONLY_BUILD.remediation` says `server doctor` prints the
exact command (`src/vaultspec_rag/operator_state/_installation.py:17,120`) and
`server status` renders it (`src/vaultspec_rag/cli/_status.py:295`), but doctor
renders only the capability label. Doctor also runs a holder scan
(`src/vaultspec_rag/cli/_service_doctor.py:69`) over the CLI's own environment
while its compute verdict describes the daemon interpreter, and then neither
renders nor emits the scan.

### tool-detection-heuristic | low | uv tool detection depends on directory names and an environment variable

`classify_runtime_env` recognises a tool environment by a parent named `tools`
or a `UV_TOOL_DIR` ancestor (`src/vaultspec_rag/cli/_gpu_errors.py:61-90`); the
audited tool directory is `tools\versions`, so detection held only because the
variable was exported. `uv-receipt.toml` is the authoritative marker and the
repair already reads it. `classify_interpreter_env` resolves the interpreter
while `_tool_root` deliberately does not, so the two disagree on POSIX.

### wheel-platform-unchecked | low | the durable wheel URL is never checked against what PyTorch publishes

`_wheel_platform_tag` returns `win_amd64` for every Windows machine and a
manylinux tag for every other platform, macOS included
(`src/vaultspec_rag/commands/_tool_torch.py:132-136`). The ARM64 Windows URL
returns 403 from the index.

## Recommendations

- local-compute-bypasses-live-singleton, singleton-scoped-to-storage,
  python-api-loads-without-owner, admission-is-free-memory-only: a follow-on ADR
  must decide a machine-global GPU ownership primitive, independent of every
  configured directory, and where it is enforced so that no local path can load
  models beside a live owner of any release.
- tool-repair-commands-disagree, pinned-repair-freezes-tool: derive every tool
  CUDA command from one builder, state the pin in the refusal, and replace every
  `uv tool upgrade` recommendation with a command that upgrades.
- blocked-install-reads-as-success, holder-list-includes-self,
  doctor-remediation-dead-end: render one refusal per condition, exclude the
  invoking launch chain from holders while naming each holder's role, and make
  doctor print the command that the status fix promises.
- tool-detection-heuristic, wheel-platform-unchecked: classify tool environments
  by their receipt, and refuse a platform PyTorch publishes no CUDA wheel for.
