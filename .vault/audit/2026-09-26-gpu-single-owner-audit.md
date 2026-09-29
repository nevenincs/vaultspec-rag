---
tags:
  - '#audit'
  - '#gpu-single-owner'
date: '2026-09-26'
modified: '2026-09-26'
body_schema: 'body-v2'
body_hash: 'sha256:ab314e9776cdd3599724ed3cb4e455bff8467b9ef5c8cd14e69c7d37537a9c89'
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

### p01-review-verdict | low | Phase P01 passed its close review after three rounds

Final re-review of `bdcc8dc3` over the Phase range `5c5b4088` to `bdcc8dc3`: the
Phase meets `2026-09-26-gpu-single-owner-adr`. Four high and eight lower findings
closed across the rounds, each with a test naming the mutation it catches. One
observation: `test_gpu_borrow_cli.py::test_borrowed_work_runs_only_during_safe_pause_then_resumes_and_releases`
failed once in a loaded 216-test run and passed in three repeats and alone; if it
recurs, the borrow coordinator's waits should be bounded and reported, and the
new claim inside the pause route timed first.

### p02-review-verdict | low | Phase P02 passed its close review

Phase P02 close review of `bc1f4c11` to `8a160339`: every audit finding it
targeted closes. The refused install gives one refusal, one verify-depth probe,
one envelope and exit 2; its holder list excludes the invoking chain and names an
MCP adapter with the session to close. Each of the classifier, environment root,
holder role and remediation builder exists once.

### p02-review-json-parity | medium | two adapters still disagreed with their human output

Doctor's JSON carried no version-floor upgrade command, and a refused install's
JSON still carried the defaults of steps that never ran. Folded into P03.S13 and
P03.S12, which rewrite those surfaces.

### p02-review-api-rename | medium | a released public keyword was renamed without a breaking marker

`get_readiness(include_holders=...)` became `holders_root=...`. Resolved by
`2cd6282f`, which documents both parameters and carries a `BREAKING CHANGE`
footer; the merge request must carry the marker too if the branch is squashed.

### p02-review-launch-marker | medium | the service spawn spelled the launch module apart from its matchers

Resolved by `d69a8c3d`: the spawn and the MCP launch module both derive from the
shared launch marker.

### p02-review-posix-bare-python-holder | medium | a POSIX holder started as bare `python -m` from an activated venv is not detected

Suspected, not reproduced. The harm named - an operator running a wholesale
`--force` replacement against a held environment - is removed by Phase P03, whose
repair and upgrade apply in place, tolerate holders, and never replace an
environment; holders then inform rather than gate. Recorded, with the evidence
question (how a POSIX process is proven to run from an environment) left for a
follow-on decision should holders gate anything again.

### p02-review-lows | low | holder count, precondition wording, root spelling, role fallback, CPU-only advice

Folded into P03.S11 and P03.S13: an unbounded holder count with an "and N more"
line, a precondition that names its command, one environment-root derivation, a
role fallback instead of a raise, and the load-failure path's CPU-only advice
taken from the canonical builder.

### p03-incident-real-tool-env-rebuilt | critical | a consenting unit test rebuilt the machine's real tool installation

During P03.S12, before its commit at 18:04, a unit test that consented to the
in-place repair ran real uv against the machine's real `vaultspec-rag` tool
installation, the one hosting the machine's shared service. The test had forced the tool classification
onto the project interpreter, so the command named that interpreter's Python and
not the tool environment's. uv then ignored the existing environment, deleted its
`Lib`, and failed on the held `Scripts` at 17:48. The running service survived on
imported modules; the `vaultspec-rag` shim and a spawn-based rebuild in flight
failed until another session rebuilt `Lib` at 17:58. The S12 ledger note saying
nothing changed was wrong; only the receipt and `Scripts` had been checked.
Reproduced in a sandbox as `2026-09-26-tool-upgrade-cycle-research` F5. Required
before P03 resumes: the repair runner refuses under pytest outside the
containment root, and refuses anywhere when uv's tool entry for the package is
not the environment the running interpreter belongs to; commands name the target
environment's own interpreter.

### p03-e2e-running-launcher-deletes-env | critical | a consented repair run through the tool's own launcher deletes the tool environment

End to end on Windows with uv 0.12.12, from a wheel built at `9d067c0f`: a tool
environment in the field shape (CPU torch, no receipt options) and
`vaultspec-rag install --upgrade --yes` run through the tool's `bin` launcher.
uv swapped torch to the CUDA build in place, then failed on
`failed to remove directory ...\Scripts: Access is denied`; `Lib` was gone and
the command crashed rendering its report. The interpreter request matched the
environment. The cause is the launcher: `uv tool install` re-installs every
entry-point launcher after any package change, cannot replace one that is
running, and then removes the whole tool environment
(`2026-09-26-tool-upgrade-cycle-research` F8). The product's own consented run
always holds its launcher on Windows, so `src/vaultspec_rag/commands/_tool_torch.py`
destroys the environment it repairs whenever it is invoked by name. An operator
running the handed-over command while any `vaultspec-rag` command or adapter
started through a launcher is alive gets the same result. The accepted
constraint that nothing replaces an environment wholesale is not met, and the
rationale that in-place application needs nothing stopped is incomplete.

### p03-e2e-holder-remedy-contradicts-in-place | medium | holders are told to end or stop beside a repair that says nothing has to stop

The repair handoff lists holders under "running out of it now, and unchanged
until restarted" with the role remedies of `src/vaultspec_rag/operator_state/_holders.py:50-59`
("end this process", "stop it with ..."), and its steps say the repair "applies
in place, so nothing has to be stopped". Doctor renders the same remedies under
a docstring that still describes a repair replacing the environment
(`src/vaultspec_rag/cli/_service_doctor.py:378-384`). The remedy for a process
running the old build is a restart after the repair, and after F8 a running
launcher is a blocker of a different kind; neither is what the lines say.

### p03-review-post-repair-omits-restart | high | a repair the product applies never tells the operator to restart the service

`src/vaultspec_rag/commands/_tool_torch.py:503` takes `remediation.steps[-1]`,
which for a tool environment is the upgrade-later line, not `RESTART_NOTE`. A
successful repair leaves the running daemon on CPU torch with no instruction to
restart it. The covering test asserts action and receipt only.

### p03-review-force-is-taken-as-consent | high | `--force` authorises the repair against the accepted constraint

`src/vaultspec_rag/commands/_install.py:1000-1006` passes
`assume_yes=request.assume_yes or request.force`; the accepted decision limits
consent to an interactive confirmation or `--yes`. A scripted
`install --force` launches a multi-gigabyte reinstall nobody asked for.

### p03-review-support-section-deleted | high | the installation guide lost its escalation section

`0d5419e0` deleted the `### Ask for help` subsection of `docs/installation.md`,
outside S15's scope; it carried the three outputs a maintainer needs and the
tracker link.

### p03-review-consent-prompt-on-the-json-path | medium | `install --json` prints a prompt before its envelope

`src/vaultspec_rag/cli/_install.py:373` derives the confirmer from
`stdin.isatty()` alone, and the prompt renders on the stdout console. Observed
end to end: with stdin redirected from `NUL`, which Windows reports as a
terminal, the envelope was preceded by the consent prompt, so the output was
not one JSON document.

### p03-review-two-holder-serialisations | medium | the repair report serialises every holder while readiness bounds the list

`src/vaultspec_rag/commands/_tool_torch.py:152-163` and
`src/vaultspec_rag/_readiness.py:317-332` serialise the same probe result with
different keys and bounds.

### p03-review-target-check-is-not-the-running-interpreter | medium | the implemented target predicate differs from the recorded constraint

The constraint names the running interpreter's environment; the code compares
uv's tool entry with the requested target (`src/vaultspec_rag/commands/_tool_torch.py:396-428`).
No production caller passes a divergent target, so the text and the code
disagree without a demonstrated hazard.

### p03-review-receipt-pin-detection-is-url-only | low | a torch pin recorded as a path or specifier reads as durable

`src/vaultspec_rag/operator_state/_provisioning.py:246-267`. No shape the
product produces reaches it.

### p03-review-second-uv-launcher-unbounded | low | the project sync launch has no timeout or containment

`src/vaultspec_rag/commands/_uv_sync.py:31-42`; predates the branch.

### p04-e2e-repair-survives-running-launchers | info | the two-step repair and a bare upgrade leave the environment whole end to end

Rerun on Windows with uv 0.12.12 from wheels built at `fc40e93a` (0.5.2, and
a 0.5.3 bump), in a sandbox tool directory in the field shape, with an MCP
adapter running through its launcher throughout. `install --upgrade --json`
without consent exited 2 with one JSON document naming both steps.
`install --upgrade --yes` run through the product's own launcher exited 0:
torch `2.14.0+cu130`, the receipt step reported the package already installed,
`Lib`, both launchers and a receipt carrying the index and strategy intact, and
the restart named. A bare `uv tool upgrade` then installed 0.5.3 with torch
still `+cu130`, reporting only the running adapter launcher, which runs 0.5.3.
This closes p03-e2e-running-launcher-deletes-env.

### p04-e2e-console-script-adapter-unrecognised | low | an MCP adapter started through its console script is reported as an unrecognised process

The same run listed the running adapter with role `unrecognised`: the
`vaultspec-search-mcp` console script (`pyproject.toml:71`) starts
`vaultspec_rag.server:main` without `-m vaultspec_rag.server` on its command
line, so `is_server_launch` (`src/vaultspec_rag/_process_probe.py:672`) does
not match it. The remedy printed, restart once the repair is done, is still
right; the label is less specific than the product can be. The
`HolderRelation` docstring (`src/vaultspec_rag/_process_probe.py:625-633`)
still says image and launch-path holders are processes to end. Confirmed at
low by the plan-close review.

### p04-review-verdict | info | P04 close and plan close: PASS

Reviewed `f66706d2..30f58b76` and the plan's integrated behaviour. The P03
critical and all three P03 highs are resolved; no critical or high finding
remains. Verified clean: no command the product runs or hands over for an
existing environment is a package-changing `uv tool install`, and the
structural guard covers every builder output; each P03 finding is resolved as
recorded; the list-valued `mode.upgrade_commands` and
`tool_torch_repair.commands` have no consumer on the old keys and cross no
service boundary; the S19 proofs assert wholeness before exit codes; the
documentation matches the builder.

### p04-review-upgrade-advice-names-a-command-that-does-not-upgrade | medium | the repair block offers the receipt install as the way to take a newer release

`src/vaultspec_rag/operator_state/_provisioning.py:691` renders the first
element of `tool_upgrade_commands`, which for a non-durable receipt is the
options-only install; it changes no package and takes no release. `fc40e93a`
fixed the same defect on the version-floor axis only.

### p04-review-receipt-fix-is-a-newline-blob | medium | doctor and status print the two-step repair as one unlabelled run-on

`ToolReceiptVerdict.fix` (`src/vaultspec_rag/operator_state/_provisioning.py:126-133`)
joins the two commands with a newline; `src/vaultspec_rag/cli/_service_doctor.py:347`
and `src/vaultspec_rag/cli/_status.py:298` embed it after a label, so the second
step lands at column zero with nothing saying the order matters, and the JSON
`receipt.fix` is a newline string beside list-valued command fields. Running
only the visible pip step leaves a receipt that the next upgrade resolves back
to CPU.

### p04-review-repair-command-property-is-test-only | medium | a joined-string property only tests still read

`CudaRemediation.repair_command` (`src/vaultspec_rag/operator_state/_provisioning.py:171-174`)
has no production reader; `tests/test_service_env_preflight.py:191,537` are its
only callers.

### p04-review-lows | low | damaged-metadata release, holder command lines in detail, stale fixtures, README wrap

- The swap omits the release pin when the installed release cannot be read
  (`src/vaultspec_rag/operator_state/_provisioning.py:457-478`), so a damaged
  environment resolves the newest release against D3 of
  `2026-09-04-cuda-provisioning-adr`.
- `holder_wire` omits command lines for the HTTP route while the repair
  report's `detail` still carries them through `holder_summary`
  (`src/vaultspec_rag/operator_state/_holders.py:81-150`).
- Two renderer fixtures in `tests/test_tool_torch_repair.py:477-484` spell the
  pre-S18 holder wording.
- `README.md:104-105` breaks a paragraph's wrapping.
- The plan's Verification list did not cover P04; extended at close.

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
