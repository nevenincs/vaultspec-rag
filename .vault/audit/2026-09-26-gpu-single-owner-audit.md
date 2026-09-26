---
tags:
  - '#audit'
  - '#gpu-single-owner'
date: '2026-09-26'
modified: '2026-09-26'
body_schema: 'body-v2'
body_hash: 'sha256:f54cd18461afe6e17df883b6a0327346b50d7433855693dd19975171f77db6c0'
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

### p01-review-borrow-lane-loan | high | a loan that could not be recorded reported the bind as a success

Phase P01 close review. The bind lent the GPU only if the service already held
the owner anchor, which it takes at its first model load; a service whose models
never loaded held nothing, the loan silently failed and the bind still succeeded,
so the borrower's loads were refused with advice that did not apply. The
production daemon does load its models at boot (`src/vaultspec_rag/server/_lifespan.py:519`),
so the ordinary case was sound. Resolved: the bind now claims the GPU for the
service before lending (`src/vaultspec_rag/_service_borrower.py`), and a loan that
cannot be recorded refuses the pause with `borrower_gpu_not_lendable`
(`src/vaultspec_rag/server/_routes_quiesce.py`).

### p01-review-lent-path-cost | high | every model load in a borrowing process walked the process table

Phase P01 close review. The loan check re-read this process's lineage at every
`load_accelerator`, measured at about 215 ms per call on Windows. Resolved: the
lineage is read once per process and the anchor location once, and a lent check
now costs 0.66 ms after a first call of about 400 ms.

### p01-review-citation-gate | high | the macOS shared folder tripped the identity-leak gate

Phase P01 close review. `/Users/Shared` matched the user-home pattern although it
names no account. Resolved: the gate excludes that segment beside its other
placeholders, including where it ends a scanned value (`tools/citation_gate.py`).

### p01-review-json-refusal | high | an ownership refusal at model load printed prose to a JSON caller

Phase P01 close review. `_handle_gpu_error` rendered the ownership refusal in
human mode whatever the caller had asked for. Resolved: the command name and JSON
mode are threaded through from search and index. Local indexing runs only inside
the `--borrow-gpu` lane (`src/vaultspec_rag/cli/_index.py:909-918`), so it needs no
separate ownership pre-check.

### p01-review-refusal-shapes | medium | one condition carried two envelope shapes and search-shaped advice on start

Phase P01 close review. Resolved: both refusals carry one `gpu_owner` object from
one helper, placed where each envelope family keeps its detail, and a start
refusal receives start-shaped next actions.

### p01-review-legacy-detection | medium | an unobservable default-location service lock read as no service

Phase P01 close review. Resolved: the default-location check observes through
the shared-anchor fallback, raises on an unobservable lock so the caller reports
it unverifiable, and is exercised directly against held, free, absent and
unobservable locks. The review's alternative of checking the service lock before
the anchor was not taken, because a borrower runs beside the service that holds
that lock and would be refused before its loan was read; the claim instead
publishes its owner record at once, and names the service when a service lock
refuses it.

### p01-review-anchor-directory | medium | a host with neither preferred directory refused all compute

Phase P01 close review. Resolved: the temporary directory is the last resort when
every account shares it (world-writable and sticky), and the substitution entry
now states the real constraint.

### p01-review-fixture-and-foreign-release | medium | the private-anchor fixture leaked its claim, and a foreign release was refused for the wrong reason

Phase P01 close review. Resolved: the fixture releases any claim taken on its
anchor, the borrower suites use it, and a mandated local search beside a daemon of
another release is refused as ownership, naming the release replacement as the
way forward.

### p01-review-latent | low | a forked child and a detached descendant

Phase P01 close review. A forked child now forgets the parent's held claims and
lineage. A descendant whose intermediate parent has exited cannot prove its loan;
recorded only, as no caller starts one.

### p01-rereview-shared-open-widened-a-private-lock | high | observing a service lock through the shared path made it world-writable on POSIX

Phase P01 re-review of `c3c26626`. The default-location check observed the
storage-scoped service lock through the shared-anchor path, and that path widened
the mode of every file it opened, not only of one it created, so on Linux or macOS
a peer's `0o600` service lock became `0o666` and its owner pid spoofable.
Resolved: only a shared anchor this call created is widened
(`src/vaultspec_rag/_anchor_claim.py`, `_create_shared_anchor`). Proven on WSL
Ubuntu against native `/tmp`: the previous code left the private lock at `0o666`,
the fix keeps `0o600`, and a newly created shared anchor is still `0o666`; the two
POSIX tests in `test_hardware_anchor.py` assert both.

### p01-rereview-refused-loan-stays-bound | low | a pause refused for an unlendable GPU stays quiesced and bound

Phase P01 re-review. Kept deliberately: the binding is what lets the service
resume by itself when the borrower's lease is lost; clearing it on a refused loan
would leave an unbound quiescence that nothing resumes if the borrower then
crashes. The refusal names the way out, and the borrower's own resume clears it.

### p01-rereview-fork-and-fallback | low | inherited descriptors in a forked child, and the temporary-directory fallback

Phase P01 re-review. A forked child now closes its copies of the parent's
descriptors. The temporary-directory fallback remains weaker than the two
preferred locations - a per-account `1777` `TMPDIR` passes the shared test, and
`/tmp` is swept by age - and is reached only on a host with neither preferred
directory; whether such a host should refuse instead is a follow-on decision.

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
