---
tags:
  - '#research'
  - '#cuda-provisioning'
date: '2026-09-04'
modified: '2026-09-04'
body_schema: 'body-v2'
body_hash: 'sha256:e57692e0cce4046b1ec3888715ca13671924ea34184a74341b7ea7b15959cc6b'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-adr]]"
  - "[[2026-09-01-tool-mode-cuda-research]]"
  - "[[2026-09-01-tool-mode-cuda-plan]]"
  - "[[2026-09-01-gpu-less-install-footprint-adr]]"
  - "[[2026-06-24-torch-dependency-group-adr]]"
---

# `cuda-provisioning` research: `hostile-condition robustness of CUDA acquisition and the proof harness`

Can the CUDA acquisition paths be trusted under hostile environment conditions, and
can that trust be proven without mutating a live install? A field incident on
2026-09-03 answered the first question no: a hand-run durable pin destroyed a tool
environment, leaving `ModuleNotFoundError: No module named 'annotated_doc'` on every
invocation and a receipt naming a pin for an environment that no longer existed. The
evidence gathered here shows the automatic repair reaches the same end by construction
on Windows, that the guard standing in front of it answers a different question than
the one that matters, and that the destructive window is narrower than assumed - uv
fails non-destructively at resolve and destructively only at replacement. The second
question answers yes: real uv against redirected tool and cache directories, with a
stand-in wheel served over loopback HTTP, reproduces every condition but two at fast-lane
cost. The ADR must settle the execution shape of the durable pin, the holder-detection
contract, the consent and scope of an automatic repair, and which proofs may gate CI.

## Findings

### The forced tool reinstall is non-atomic, and a blocked removal destroys the environment

`uv tool install --force` removes the installed distributions before writing
replacements. On Windows a held file aborts the run mid-removal. Reproduced against
`uv 0.12.8 (68209e5c6)` in a redirected `UV_TOOL_DIR`: with a `<tool>\Scripts\python.exe`
process alive, the run exits 2 with `error: failed to remove directory ...\Scripts: Access is denied. (os error 5)`, `Lib/site-packages` is gone, and `uv-receipt.toml`
survives naming the old pin - a receipt that lies about an environment that no longer
exists. The field environment matched this exactly: `pydantic`, `numpy`, `httpx`,
`fastapi`, `huggingface_hub`, `transformers` and `annotated_doc` removed while their
`Scripts` shims remained, and `typer@0.27.2` imports `annotated_doc` (`uv.lock:2496-2503`),
so the CLI died during import with no exit-code contract and no envelope.

The prior research anticipated this and deferred the proof: `2026-09-01-tool-mode-cuda-research`
states it never performed a real tool reinstall against a live Windows service, and names
the active installer as a replacement hazard requiring a real-Windows execution proof.
That proof is the artifact this campaign owes.

### The automatic repair cannot succeed on Windows from inside the target environment

`repair_tool_torch` requires the interpreter to be a uv tool env
(`src/vaultspec_rag/commands/_tool_torch.py:289`), then calls
`subprocess.run(spec.args, ...)` synchronously (`_tool_torch.py:341-345`) and blocks. The
parent holds its own `python.exe` open for the whole call, so the child uv hits the lock
its own caller holds. Reproduced: exit 2, `os error 5` on `Scripts`, identical to the
holder case. The guard is irrelevant to this failure - whenever
`_service_holder_outcome` reports clear, the repair destroys the environment it was
invoked to fix. The uv trampoline embeds and execs `<tooldir>\Scripts\python.exe`
(observed as a literal inside the generated `.exe`), so a `vaultspec-rag` invoked from
its own shim is itself the holder.

A detached spawn escaped the lock in one experiment, but only by winning a race against
uv's local-cache resolve (~15 ms in that run); a cold resolve narrows the margin. A
relauncher that waits on the former parent's pid before invoking uv (`wait_for_exit`,
`src/vaultspec_rag/_process_probe.py:584-595`) closes the race but requires a genuinely
separate process. Refusing and printing the command (`ToolTorchRepairOutcome.command`
already exists, `_tool_torch.py:59-63`) carries no race at all. The ADR must choose among
these three.

### Holder identity is image path and working directory, not image path alone

A process whose current working directory sits inside the tool env blocks removal even
when its executable is entirely foreign to that env. Reproduced with the repo's own
`.venv` interpreter chdir'd into the tool directory: exit 2 with a *different* Windows
error - `The process cannot access the file because it is being used by another process. (os error 32)` - and a worse post-state, the tool directory left completely empty. An
image-path prefix test alone would report that machine clear.

The two relations need different remediation text: an image-path holder is a process to
close, a working-directory holder is a shell or editor to `cd` out of. `psutil` is
already a dependency (`pyproject.toml:34`), and `psutil.Process(pid).exe()` and `.cwd()`
both read without elevation for same-user processes, so this needs no new platform code.
`src/vaultspec_rag/_process_probe.py:16-20` already establishes the contract to extend:
what cannot be determined is never reported as clear. Cost is bounded by the documented
attribute-cost split at `_process_probe.py:456-466`, where `exe` and `cwd` are cheap
attributes; the scan was not independently timed here.

### The existing guard answers a different question

`_service_holder_outcome` (`_tool_torch.py:252-265`) consults only
`resolve_machine_service()` (`src/vaultspec_rag/serviceclient/_discovery.py:536-587`),
which resolves the daemon's machine-lock singleton. It is blind to a plain CLI
invocation running from the tool env, to an MCP server process that has not yet reached
`_claim_machine_singleton()` (`src/vaultspec_rag/server/_lifespan.py:59-73`), and to the
invoking process itself. In the field incident it would have reported clear: the daemon
had been terminated, while six `python -m vaultspec_rag.server` processes - one per
connected editor session - held the environment. Its conservatism runs the other way
too: it cannot see other interpreters at all, so a daemon running from an unrelated
project venv is the only false positive it can produce. The function also has no
exception guard, so a raising resolver aborts install with exit 1 rather than refusing
the repair.

The origin of this shape is recorded: `2026-09-01-tool-mode-cuda-research` concluded the
service identity model should be reused rather than adding a receipt-specific PID check.
That model verifies a service, not the holders of a directory.

### Resolve-stage failure is non-destructive; only replacement destroys

uv resolves and fetches before it replaces. Observed: a `--force` install whose `--with`
URL is unreachable exits 1, prints the fetch error, and leaves the existing environment
and receipt completely intact. This splits the taxonomy cleanly - a bad wheel URL, a
tag mismatch, an offline cache miss and (by inference, not observation) disk exhaustion
all fail safe, while holders fail destructive. A preflight therefore needs to cover
holders, not fetch failures.

Two reporting details follow. `download.pytorch.org` answers a nonexistent wheel with
HTTP **403** (S3 `AccessDenied`), not 404, so operator-facing copy describing a 404 is
wrong and the error an operator sees will read as a permissions problem. And
`docs/installation.md` describes the failure as "fails mid-removal", which is true of
the lock case only.

### The derived wheel URL has two impossible platforms and two version sources

`tool_cuda_install_spec` (`_tool_torch.py:126-163`) derives interpreter, ABI, platform
and version from one `Tag`, which correctly handles free-threaded `cp314t`. Verified
2026-09-04: the cu313, cp314, cp314t and manylinux URLs it produces all resolve (HTTP 206
on a range GET; wheel size 1 922 599 627 B, 1.79 GiB). Two derivations cannot be right:
`_wheel_platform_tag` returns `win_amd64` unconditionally for win32 (`_tool_torch.py:108-109`),
naming an x86-64 wheel on Windows-on-ARM, and darwin falls to the else branch yielding
`manylinux_2_28_arm64`, a URL that cannot exist. The darwin path is reachable through
`_ephemeral_env_warning` and `_caller_ephemeral_warning`
(`src/vaultspec_rag/cli/_service_start.py:895-945`), which do not guard on platform.

The pin version has two independent sources: `TORCH_TOOL_PIN_VERSION` in
`src/vaultspec_rag/torch_config/_constants.py:74` (used whenever torch is absent, which
is the normal state under the gpu-less footprint) and `tools/binaries/torch_channel.py:82-104`,
which derives the same fact from `uv.lock` and refuses when it is not exactly one. A
lockfile bump updates the binary route and silently leaves the constant behind. One
behaviour, two implementations.

### The repair changes more than torch, and reports almost nothing

`uv tool install --force <name>` resolves the latest published `vaultspec-rag`, so a
repair consented to as "reinstall this uv tool environment with the CUDA torch wheel"
(`_tool_torch.py:227-228`) is also an unannounced version upgrade, adds `[gpu,mcp]`
whatever extras the operator chose, and drops any `--with` requirement they had added.
The prompt names neither the 1.79 GiB download nor the version. Consent is conflated
with file overwrite: `assume_yes=request.assume_yes or request.force`
(`src/vaultspec_rag/commands/_install.py:968`). There is no opt-out - `repair_tool_torch`
defaults true (`_install.py:826`) and no CLI flag disables it, while `docs/installation.md`
tells operators `--no-torch-config` is how to manage PyTorch themselves, which it is not.

Outcomes are structurally truthful but invisible: `_render_install_report`
(`src/vaultspec_rag/cli/_render.py:716-749`) never reads `report.tool_torch_repair`, so
`REPAIRED` - a 1.79 GiB download that just happened - prints nothing outside `--json`.
`SKIPPED_EOF` is dead code from the CLI, since `confirm_fn` is `None` whenever stdin is
not a TTY (`src/vaultspec_rag/cli/_install.py:359`) and the non-TTY branch fires first.

### The project route can report success over a CPU wheel, and nothing has a timeout

`_classify_uv_sync_result` treats `returncode == 0` as success unconditionally
(`src/vaultspec_rag/commands/_uv_sync.py:76`). `uv sync` exits 0 having resolved torch
from the public index whenever the cu130 source pin did not apply - the inert-pin case
the torch-dependency-group ADR records - so the report reads `succeeded` over a
processor-only wheel, and on `--target <other-project>` no backstop probes it. Neither
`_uv_sync.py:31-37` nor `_run_tool_reinstall` (`_tool_torch.py:345`) passes a `timeout`,
and both capture output, so a stalled 1.79 GiB transfer presents as a frozen terminal.

### A gpu-less tool install cannot run `install` non-interactively

Under `2026-09-01-gpu-less-install-footprint-adr` a base `uv tool install vaultspec-rag`
carries no torch. The accelerator probe then exits 3, classifies as an installation
defect (`src/vaultspec_rag/cli/_process.py:475, 498-504`), and a blocking repair outcome
short-circuits the entire install (`_install.py:862-871`) to exit 2 - no seeding, no MCP
sync, no provisioning. So the deliberately torch-free install the footprint ADR
introduced can never complete `vaultspec-rag install` without a TTY. Whether the repair
should fire at all when torch is absent by design, rather than defective, is a question
the ADR must answer.

### Real uv against redirected directories is the only harness with the needed fidelity

Measured on this host, `uv 0.12.8`: a cold tool install of a trivial package resolves and
installs in 0.519 s, a warm-cache forced reinstall in 0.164 s, and `--offline` against a
pre-warmed cache succeeds while an uncached package fails deterministically. Receipts and
tree shape are identical to production's assumptions (`_tool_torch.py:166-171`). A
session-scoped cache with a per-test tool directory keeps marginal cost near zero.

The decisive detail is transport. A `file://` requirement in `--with` is recorded by uv
under a **`path =`** key, not `url =`, while `_receipt_has_cuda_requirement` inspects only
`name`/`url` pairs (`_tool_torch.py:184-193`). A `file://`-based harness would therefore
pass every receipt-verification test without ever entering the branch production depends
on. The same wheel served over loopback HTTP records
`url = "http://127.0.0.1:PORT/..."`, matching the production shape exactly. A stand-in
wheel over loopback HTTP also reproduces a real 404 and, via a hand-crafted `cp299` tag, a
pre-download ABI rejection - both fully offline, in tens of milliseconds.

Alternatives keep a narrower role. An injected runner seam, mirroring the split
`_uv_sync.py:24-28` already documents, pins branch classification cheaply but structurally
cannot prove uv's destructive semantics. Recorded fixtures encode one uv release's
serialization and go stale precisely where the risk lives, and should stay confined to the
pure parsers that already use hand-written TOML (`src/vaultspec_rag/tests/test_tool_torch_repair.py:75-90`).

### The tier vocabulary already has a trap, and a precedent

`integration` is not a generic shells-out tier here: `GPU_MARKERS` in
`src/vaultspec_rag/tests/_tier_gate.py:98` groups it with the GPU markers, and
`conftest.py:338-420` forces an exclusive GPU-borrower lease and a Hugging Face token for
anything carrying it. Marking provisioning tests `integration` would pull them into that
gate for no reason. The precedent that fits is
`src/vaultspec_rag/tests/integration/test_adversarial_singleton.py:37` and
`src/vaultspec_rag/tests/test_machine_singleton_reclaim.py:37`, which spawn real foreign
processes holding real OS locks and are marked `unit`. At the measured per-case costs, a
suite of this kind stays inside commit-gating budget.

### The two repos gate Windows differently, and rag's Windows tests cannot block a merge

vaultspec-core proves Windows behaviour by running its whole suite on a GitHub-hosted
`windows-latest` leg at pull-request time, with a dedicated Windows job beside it
(`vaultspec-core/.github/workflows/ci.yml:292-333,335-359`), and its own comment states a
failure on either OS blocks the merge. vaultspec-rag splits by trust instead of platform:
`pull_request` reaches only `pr-gate` on hosted Linux, and every other job - including
`tests-windows` - is excluded from pull requests to keep fork code off the self-hosted
fleet (`vaultspec-rag/.github/workflows/ci.yml:10-16,83-143,145-855`). That Windows job is
additionally `continue-on-error` (`ci.yml:386-440`).

The consequence is concrete: rag already carries at least eight Windows-only tests behind
`skipif(sys.platform != "win32")` - `src/vaultspec_rag/tests/test_pid_liveness.py:55`,
`test_stdio_lifetime.py:95,132,204`, `tests/integration/test_pytest_daemon_anchor.py:62,99`
among them - which are collected and skipped on the Linux lane that gates PRs, and execute
only in an advisory post-merge lane. A Windows-only regression they exist to catch has no
power to block a merge today. A destructive-replacement proof added now would inherit that
same fate.

The fork this sets up for the ADR: adopt core's shape by adding a hosted `windows-latest`
leg to `pr-gate` (additive - `pr-gate` already proves hosted-runner-only work at
`ci.yml:83-143`, and this test class needs no model cache or GPU), or accept the proof as
advisory. Promoting the existing self-hosted `tests-windows` into the PR lane is the one
option that is not open, since it reintroduces the fork exposure that topology exists to
prevent. Core can adopt the shared shape at zero incremental CI cost; rag cannot, and that
asymmetry is a decision rather than an oversight.

### Tier vocabulary converges in both repos already

Both repos independently settled on the same shape for tests that spawn a real process to
hold a real OS lock: marked `unit`, located beside the code they exercise, selected by
marker rather than directory. Core's is `src/vaultspec_core/core/tests/test_advisory_lock.py:59-146`;
rag's are `src/vaultspec_rag/tests/integration/test_adversarial_singleton.py:37` and
`test_machine_singleton_reclaim.py:37`, the first of which sits under `integration/` while
carrying the `unit` marker. That convergence is the strongest available argument for what
the shared convention should be.

The constraint on inventing a new marker in rag is hard rather than stylistic:
`conftest.py:301-315` refuses collection outright if any test declares zero or two tier
markers, so a new name must be added to `TIER_MARKERS` (`_tier_gate.py:119`) or the tests
must be `unit`. Core has no equivalent enforcement - its markers are declarative
(`vaultspec-core/pyproject.toml:144-164`) - so parity here means core adopting a
convention it does not enforce, not the two repos meeting in the middle.

### uv serialises concurrent forced installs; only disk exhaustion resists honest reproduction

uv holds a tool-directory lock, so vaultspec needs none of its own. Observed: four
simultaneous `uv tool install --force` runs against one redirected tool directory all
exit 0 with staggered completion (0.90 s, 1.55 s, 3.48 s, 3.48 s), a `.lock` file present
in the tool root, and the environment and receipt intact afterwards. Concurrency therefore
collapses into the holder case - it is dangerous only when one of the racing processes is
itself running from the target environment.

Disk exhaustion remains the one condition with no honest mechanism. uv exposes no
injectable seam; a true reproduction needs a capacity-capped volume, and the repo's own
ENOSPC precedent (`src/vaultspec_rag/tests/test_store_writes.py:170-193`) injects
`OSError` at its own write boundary, which tests this project's classification rather than
uv's behaviour.

### Plan reconciliation

The code landed outside the plan's execution discipline, in commit `bb5f0532` (with
`18046663`); `.vault/exec/` holds no `tool-mode-cuda` folder. `P01.S01` and `P01.S02` are
done as described. `P02.S03` is partial: consent and the exit gate exist
(`cli/_install.py:352-359, 428-445`) but human-mode rendering does not. `P02.S04` is
partial: seven tests cover classification, receipt matching and three refusal branches,
while `DRY_RUN`, `UV_UNAVAILABLE`, `UV_FAILED`, `ALREADY_READY` and `NOT_APPLICABLE` are
uncovered, no test proves a refusal launches no uv child, and the ADR-mandated
self-replacement proof is absent. The one existing guard test monkeypatches
`_run_tool_reinstall` itself (`test_tool_torch_repair.py:111-134`), so no test has ever
observed what real uv does to a held environment.

### What the ADR must settle

The execution shape of the durable pin, given that the current one cannot work on
Windows. The holder-detection contract: which relations count, what an undeterminable
result means, and whether it surfaces in `server doctor` readiness as well as the repair
preflight. Whether an automatic repair may change package version and extras, and what
consent that requires. Whether a torch-free install by design should be treated as
defective. The single source of the torch pin version. And, as one decision spanning both
repos rather than a rag-local choice, the marker and location convention for
provisioning tests plus whether rag gains a hosted Windows pull-request lane.

### Not investigated

uv releases other than 0.12.8. Linux and macOS replacement ordering, where POSIX unlink
semantics make the held-file failure unlikely but untested - if it holds, the hazard is
Windows-only and the ADR's remedy may be platform-scoped. Cross-user holders. Windows
Restart Manager (`RmGetList`) as a complete open-handle enumeration. The readiness node
schema needed to wire a holder dimension into `src/vaultspec_rag/_readiness.py:177-201`.
Whether `resolve_machine_service()` can raise in practice. Real cu130 wheel installation:
every measurement here used stand-in packages. Whether a GitHub-hosted `windows-latest`
runner can execute this test class without the self-hosted fleet's warm model cache -
expected to need none, but unverified - and the runtime budget that leg would consume
against `pr-gate`'s 25-minute ceiling (`.github/workflows/ci.yml:96`).

## Sources

- `src/vaultspec_rag/commands/_tool_torch.py:59-63,97-111,126-163,166-171,173-208,227-228,252-265,274-306,309-338,341-362,365-389`
- `src/vaultspec_rag/commands/_install.py:826,854-871,962-971,968`
- `src/vaultspec_rag/commands/_uv_sync.py:24-28,31-37,60-97`
- `src/vaultspec_rag/cli/_gpu_errors.py:78-82,108-121,169-170,305-315,342-345`
- `src/vaultspec_rag/cli/_service_start.py:498-535,895-945`
- `src/vaultspec_rag/cli/_install.py:352-359,359,394-396,400-405,428-445`
- `src/vaultspec_rag/cli/_process.py:475,498-504`
- `src/vaultspec_rag/cli/_render.py:716-749`
- `src/vaultspec_rag/_process_probe.py:16-20,183,229,268,292,456-466,504,584-595`
- `src/vaultspec_rag/serviceclient/_discovery.py:79-81,536-587`
- `src/vaultspec_rag/server/_lifespan.py:59-73`
- `src/vaultspec_rag/_readiness.py:177-201`
- `src/vaultspec_rag/torch_config/_constants.py:60,74`
- `src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json:6`
- `src/vaultspec_rag/tests/_tier_gate.py:98`
- `src/vaultspec_rag/tests/test_tool_torch_repair.py:75-90,111-134,168-200`
- `src/vaultspec_rag/tests/test_service_env_preflight.py:126-183,250,257-305`
- `src/vaultspec_rag/tests/test_machine_singleton_reclaim.py:37`
- `src/vaultspec_rag/tests/integration/test_adversarial_singleton.py:37`
- `src/vaultspec_rag/tests/test_store_writes.py:170-193`
- `tools/binaries/torch_channel.py:67-120`
- `tools/binaries/build_pyapp.py:99,137,150-152`
- `conftest.py:301-315,338-420`
- `.github/workflows/ci.yml:10-16,83-143,96,145-855,386-440`
- `pyproject.toml:34,88-92`
- `vaultspec-core/.github/workflows/ci.yml:3-27,292-333,335-359`
- `vaultspec-core/pyproject.toml:144-164`
- `vaultspec-core/dev/toolchain.py:66,458-569`
- `vaultspec-core/src/vaultspec_core/core/tests/test_advisory_lock.py:59-146`
- `src/vaultspec_rag/tests/test_pid_liveness.py:55`
- `src/vaultspec_rag/tests/test_stdio_lifetime.py:95,132,204`
- `src/vaultspec_rag/tests/integration/test_pytest_daemon_anchor.py:62,99`
- `uv.lock:2496-2503`
- commit `bb5f0532`, commit `18046663`
- `uv 0.12.8 (68209e5c6)`, `typer@0.27.2`, `psutil>=6.0.0`
- https://docs.astral.sh/uv/concepts/tools/
- https://download.pytorch.org/whl/cu130/

Experimental claims above were reproduced on Windows 11 with `uv 0.12.8` against
redirected `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR` and `UV_CACHE_DIR`; no live installation was
mutated. POSIX unlink behaviour is flagged as general knowledge, unverified here.
