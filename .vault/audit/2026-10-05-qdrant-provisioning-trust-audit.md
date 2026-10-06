---
tags:
  - '#audit'
  - '#qdrant-provisioning-trust'
date: '2026-10-05'
modified: '2026-10-06'
body_schema: 'body-v2'
body_hash: 'sha256:2befd84e1c17a45091a8b7d11ee3efe539b9f9111c0ac176f12515ccf1fa4dbb'
related:
  - "[[2026-06-12-qdrant-server-provisioning-adr]]"
  - "[[2026-06-13-provisioning-setup-adr]]"
---

# `qdrant-provisioning-trust` audit: `managed qdrant binary provisioning and execution path review`

## Scope

How a host installation obtains, verifies, and executes the managed Qdrant server binary when `vaultspec-rag server start` runs on a machine that has never provisioned one, read against the verify-before-execute contract of `2026-06-12-qdrant-server-provisioning-adr` and the front door of `2026-06-13-provisioning-setup-adr`. Covered: `src/vaultspec_rag/qdrant_runtime/_constants.py`, `_provision.py`, `_resolve.py`, `_supervise.py`, the start path in `src/vaultspec_rag/cli/_service_start.py`, the daemon start in `src/vaultspec_rag/server/_lifespan.py`, and the heartbeat restart in `src/vaultspec_rag/server/_lifecycle.py`. Three probes ran: a PATH lookup probe on Windows, an install-state probe in an isolated status directory, and a comparison of the six committed archive digests against the upstream release API for tag `v1.19.0` (all six match). No download and no binary execution was performed.

## Findings

### path-tier-cwd-exec | high | a qdrant file in the working directory is executed instead of provisioning

The third resolution tier is `shutil.which("qdrant")` at `src/vaultspec_rag/qdrant_runtime/_resolve.py:824`. On stock Windows that lookup searches the current directory first and returned `.\qdrant.CMD` and `.\qdrant.EXE` in the probe. On a machine with no operator binary and no managed install the first two tiers are empty, so `_ensure_qdrant_binary` returns early at `src/vaultspec_rag/cli/_service_start.py:338` with no download and no console message. The daemon is spawned without a working directory at `src/vaultspec_rag/cli/_process.py:894`, resolves the same file, and the only signal is a warning in the service log at `src/vaultspec_rag/qdrant_runtime/_supervise.py:1352`. The lookup is confirmed; the execution step is traced by reading. A PATH binary is also assumed to be the pinned version for the store-format judgement at `src/vaultspec_rag/qdrant_runtime/_supervise.py:1368`.

### pre-exec-self-attested | high | the pre-execution check trusts a digest stored beside the binary and can be skipped

Only the archive digest is a code constant. The executable digest is read from `manifest.json` in the same directory at `src/vaultspec_rag/qdrant_runtime/_resolve.py:787` and compared at `src/vaultspec_rag/qdrant_runtime/_supervise.py:1328`. A manifest carrying only a `version` key resolves as `provisioned` with an empty digest, and the comparison branch is not taken, with no warning (confirmed by probe). The archive is hashed at `src/vaultspec_rag/qdrant_runtime/_provision.py:371` and then reopened by path for extraction at `src/vaultspec_rag/qdrant_runtime/_provision.py:306`, and whatever is extracted is recorded as trusted. The build toolchain already pins executable digests in `tools/binaries/bun_pins.py:27` and checks them with `verify_native_binary`; the qdrant path uses a second inline comparison.

### respawn-unverified | medium | restarts re-execute the binary without re-hashing

The heartbeat restart at `src/vaultspec_rag/server/_lifecycle.py:473` reaches `restart` at `src/vaultspec_rag/qdrant_runtime/_supervise.py:880`, and the quarantine retry loop at `src/vaultspec_rag/qdrant_runtime/_supervise.py:795` re-spawns as well. Neither re-verifies the executable.

### recovery-dead-end | medium | the documented recovery for a digest mismatch does nothing

A mismatch at start tells the operator to run `server qdrant install --upgrade` at `src/vaultspec_rag/qdrant_runtime/_supervise.py:1333`. `_existing_install_state` at `src/vaultspec_rag/qdrant_runtime/_provision.py:412` never hashes the binary, so a tampered binary with an intact manifest reports `unchanged` both with and without `--upgrade` (confirmed by probe). `src/vaultspec_rag/tests/test_qdrant_runtime.py:312` asserts that behaviour.

### install-not-atomic | medium | a failed or interrupted install destroys or strands an install

The generic failure handler unlinks the existing binary at `src/vaultspec_rag/qdrant_runtime/_provision.py:537` even when the failure was the download, so `--upgrade` over a working operator-registered install while offline removes it. Extraction writes in place at the final name; an interrupt mid-extract leaves a truncated binary with no manifest, which every later provision reports as a stale install that needs `--upgrade`.

### start-does-not-provision | medium | a default start on an unprovisioned host fails instead of provisioning

`--qdrant-auto-provision` defaults off at `src/vaultspec_rag/cli/_service_start.py:268`, so a plain `server start` exits with `qdrant_missing`. Models have no such gate: the daemon loads them online-capable unless the hub offline switch is set (`src/vaultspec_rag/config/_types.py:269`). The two fetch-and-go dependencies therefore behave differently on the same command. The client refusal sits in `_preflight_daemon_accelerator` at `src/vaultspec_rag/cli/_service_start.py:555`, which runs after the binary check at `src/vaultspec_rag/cli/_service_start.py:913`.

### duplicate-model-fetch | low | two implementations fetch model snapshots

`provision_models` at `src/vaultspec_rag/commands/_provision.py:413` and the `server warmup` loop at `src/vaultspec_rag/cli/_service_lifecycle.py:243` each probe the cache and call the hub download for the same repo list.

### download-hardening | low | staging, locking, deadline, and allowlist gaps

The `.partial` staging file is opened without the no-follow guard the extraction target has (`src/vaultspec_rag/qdrant_runtime/_provision.py:254`). The staging name is fixed and nothing serialises provisioning, so concurrent starts collide. The 120 second timeout is per socket operation with no overall deadline. `api.github.com` is allow-listed at `src/vaultspec_rag/qdrant_runtime/_constants.py:61` and never used. The release base URL and host set are code constants with no settings override. An unsupported platform raises `RuntimeError` from `provision` at `src/vaultspec_rag/qdrant_runtime/_provision.py:599`, which nothing in `src/vaultspec_rag/cli/_service_start.py` catches.

### stale-provisioning-prose | low | comments and a published phase say the daemon provisions

`src/vaultspec_rag/server/_lifespan.py:463` and the `_no_progress` docstring in `src/vaultspec_rag/qdrant_runtime/_provision.py:70` describe daemon-side provisioning; `start_supervised_from_config` only resolves and raises. The resolution docstring promises a version-skew warning for a PATH binary that does not exist.

### model-child-cwd-shadow | critical | a child interpreter started with a module flag imports the package from the working directory

Hostile review, trust and supply chain, at `d0de3724`. The model download child is started as the interpreter with the module flag and no working directory at `src/vaultspec_rag/commands/_model_download.py:328`. That form puts the current directory first on the import path, so a `vaultspec_rag` package at the root of a cloned repository is imported and run as the operator on `install`, `server warmup`, or the first `server start`. Confirmed with a benign planted module using the exact command the parent builds. The same form starts the daemon (`src/vaultspec_rag/cli/_process.py:552`, marker at `src/vaultspec_rag/_process_probe.py:714`), which predates this plan, and the environment probe runs an inline script at `src/vaultspec_rag/operator_state/_environment_probe.py:70`, which puts the working directory on the path as well. The monitor bridge already starts its child in safe-path mode.

### base-url-input-hygiene | low | the source URL validator admits a control character in the host and port zero

Same review. `src/vaultspec_rag/config/_schema.py:119` accepts a NUL in the host and port 0. The setting is environment-only and digest-protected, so the effect is a confusing connect-time failure rather than a refusal that names the setting.

Held under attack in the same review: userinfo, downgrade, query, fragment, and look-alike hosts in the base URL; cross-host, downgraded, trailing-dot, and literal-address redirects; certificate verification under the interpreter's verification-off variable and through a proxy; hostile archive member names, links, duplicates, and directory collisions; workspace files repointing any source setting; re-verification on restart and retry; the parent's handling of the download child's pipe. The archive and executable digests for the Windows and Linux x64 musl assets were re-derived from the official host and match.

### start-ignores-persisted-backend | high | a plain server start ignores the persisted local-only choice and the backend environment

Hostile review, client and command contract, at `d0de3724`. The start preflight decides whether a binary is needed from flags alone (`src/vaultspec_rag/cli/_service_start.py:366`), and the daemon is handed an explicit server-mode value rather than no value (`src/vaultspec_rag/cli/_service_start.py:1012`, `src/vaultspec_rag/cli/_process.py:401`). After `install --local-only`, a plain start fetches the binary and flips the backend to server mode, where the local index is not visible. An exported local-only variable, the server-mode variable set off, and a remote server URL are overridden the same way. The mechanism predates this plan; automatic provisioning changed its consequence from a refusal to an unrequested download. Confirmed by five runs.

### doctor-demands-provisioning-from-client | high | readiness tells a client to provision what its install declines to provision

Same review. Only the torch row of the readiness report asks the installation role (`src/vaultspec_rag/_readiness.py:356`); the model and binary rows do not (`src/vaultspec_rag/_readiness.py:374`, `src/vaultspec_rag/_readiness.py:454`). A client's `server doctor` reports both not ready and names `install`, which then reports them not needed. `server qdrant status` names the install verb to a client the same way (`src/vaultspec_rag/cli/_service_qdrant.py:217`). Nothing is downloaded. Confirmed.

### cwd-executable-lookup-remains | high | three helper executables are still found by a search that takes the working directory first on stock Windows

Same review. The daemon inherits the directory the start ran in (`src/vaultspec_rag/cli/_process.py:876`) and resolves the monitor by bare name on every start (`src/vaultspec_rag/monitor_process.py:44`); status resolves `nvidia-smi` the same way (`src/vaultspec_rag/operator_state/_hardware.py:40`), and the install repair resolves `uv` (`src/vaultspec_rag/commands/_tool_torch.py:366`, `src/vaultspec_rag/commands/_uv_sync.py:40`). This is the class `path-tier-cwd-exec` closed for the server binary only. Resolution confirmed; execution traced by reading. Predates this plan.

### remedy-names-flag-the-verb-lacks | medium | a manifest-less install is absent to the resolver and unverified to the provisioner

Same review. An executable with no manifest, which a kill between replace and manifest write leaves behind, is treated as absent at `src/vaultspec_rag/qdrant_runtime/_resolve.py:860` and as needing `--upgrade` at `src/vaultspec_rag/qdrant_runtime/_provision.py:597`. `server start` relays the upgrade text though it has no such flag, `install --upgrade` means something else, and status names a command that fails. None resolves and nothing is provisioned. Confirmed.

### start-interrupt-no-envelope | medium | an interrupt during the foreground fetch ends a JSON start with no envelope

Same review. The provisioning stage at `src/vaultspec_rag/cli/_service_start.py:340` has no interrupt handling, unlike the readiness wait at `src/vaultspec_rag/cli/_service_start.py:1306`; the outcome is empty output and exit 130 for start and for the install verb, and the interrupt takes effect only at the stall bound because the main thread sits in a blocking read. Confirmed with a simulated interrupt; a real console interrupt was not exercised.

### host-role-from-unrelated-distribution | medium | one unrelated distribution makes an environment a host to every provisioning gate

Same review. The role is the presence of one distribution (`src/vaultspec_rag/operator_state/_compute.py:52`). With that metadata present in a torch-free environment, warmup and the install verbs reached the network and wrote the backend marker, and only start refused. The mechanism is confirmed; a project that depends on that library itself and adds this package as a client is the plausible real case. A follow-on decision must settle whether provisioning gates on role alone or on role and capability.

### help-misstatements-at-head | low | help text that is wrong or names a flag that does nothing

Same review. The install verb's upgrade help describes a version change it does not perform; `install --skip-torch` has no effect; the tool-repair help says nothing is installed where the consented path runs a fetch; warmup still speaks of search-time latency; start's description never says it downloads model files or the server archive.

### json-surface-inconsistencies | low | smaller envelope drift

Same review. Next actions never reach a JSON envelope (`src/vaultspec_rag/cli/_service_lifecycle.py:76`); the install verb reports a generic failed code where start reports the provisioning code; a bad setting yields a different envelope schema; warmup has no JSON mode though start's remedy sends callers there; a client start creates the managed directory before the role gate; a failed install still writes the backend marker (`src/vaultspec_rag/commands/_install.py:1402`).

Held under attack in the same review: every client command with the network blocked made no request and wrote nothing under the status, storage, or model directories; the MCP tools only forward; a host cannot skip verification through the client path; the host start matrix gave one envelope and exit 1 on every failure tried; both dry-run verbs made no request and no managed write; exit codes agree across the four provisioning verbs.

### model-preflight-unbounded | high | a silent or trickling hub hangs the model size query forever in the parent

Hostile review, failure and concurrency, at `d0de3724`. The free-space preflight asks the hub for file sizes in the parent with no timeout (`src/vaultspec_rag/commands/_model_fetch.py:331`) while holding the cache claim (`src/vaultspec_rag/commands/_model_fetch.py:248`). The progress floor and the killable child do not apply because no child exists yet. Against a hub that accepts and never answers the command sat for 846 seconds until killed, and an interrupt did not end it on Windows. Confirmed.

### install-killed-after-replace-strands | high | a kill between the replace and the manifest leaves a pinned executable every later start refuses

Same review; the same state as `remedy-names-flag-the-verb-lacks`, reached by a hard kill at `src/vaultspec_rag/qdrant_runtime/_provision.py:867`. The executable matches its committed digest, the manifest is absent, and the archive staging file remains because the sweep runs only inside a performed install (`src/vaultspec_rag/qdrant_runtime/_provision.py:1128`). Only the upgrade form of the install verb repairs it, by re-downloading a byte-identical file. The five earlier kill stages recover on the next attempt. Confirmed.

### upgrade-remedy-crashes-on-unreadable-binary | medium | the remedy named for a binary that could not be held ends in a traceback

Same review. A binary held by another reader is reported as unverified with the upgrade remedy (`src/vaultspec_rag/qdrant_runtime/_spawn_trust.py:104`), which is wrong for a transient hold, and running it raises an uncaught permission error because only one exception class is caught around the hash (`src/vaultspec_rag/qdrant_runtime/_provision.py:613`). Confirmed.

### single-restart-burned-no-recovery-path | medium | a refused heartbeat restart is terminal for the daemon's lifetime and no surface names the way out

Same review. A restart refused before any spawn still counts as the one restart (`src/vaultspec_rag/qdrant_runtime/_supervise.py:862`, `src/vaultspec_rag/server/_lifecycle.py:457`). Health names the status verb, status names a start that answers already running with exit 0, and nothing names stop then start. Confirmed for the supervisor; the operator chain is read, not run.

### model-cache-fault-network-remedy | medium | an unusable model cache directory is reported as a network failure

Same review. The classifier recognises only exhausted space among local errors (`src/vaultspec_rag/commands/_hub_failure.py:65`); a cache path whose parent is a file, or a permission error, takes the network remedy. Confirmed.

### worst-case-wait-arithmetic | medium | bounded waits add up to hours and the model fetch has no whole-operation bound

Same review. The cache-claim wait of an hour is applied per repository (`src/vaultspec_rag/commands/_model_fetch.py:224`), so three repositories can wait three hours; the download has only the progress floor, so a hub just above it holds the command for as long as the weights take; none of the waiting lines is visible in JSON mode. A second starter for the binary can wait about 31 minutes. A follow-on decision must settle whether the model fetch gets a whole-operation deadline.

### start-path-tests-assert-a-substitute | medium | start-step tests stand on a double whose stated justification is no longer true

Same review. `src/vaultspec_rag/tests/test_start_provisioning.py:289` replaces the provisioner and asserts a canned string, with a manifest shape the provisioner never writes (`src/vaultspec_rag/tests/_qdrant_provision_seam.py:98`); the seam's reason, that a local archive cannot be driven, is disproven by the install tests. No test interrupts between replace and manifest, kills a lock holder, or exercises an unreadable installed binary, a local cache fault, or a silent size query.

### failure-surface-low | low | four smaller failure-path defects

Same review. A base URL with an empty or over-long host label passes validation and crashes the download with an encoding error (`src/vaultspec_rag/qdrant_runtime/_download.py:679`). Filesystem faults under the managed directory end with no remedy, and a directory at the installed name is told to stop the service (`src/vaultspec_rag/qdrant_runtime/_provision.py:1045`, `src/vaultspec_rag/qdrant_runtime/_provision.py:437`). A body with no declared length cut by a clean close reads as a replaced upstream asset (`src/vaultspec_rag/qdrant_runtime/_download.py:482`). A filesystem that refuses the lock call would read as sixteen minutes of contention (`src/vaultspec_rag/_anchor_claim.py:399`; plausible, not reproduced).

Held under attack in the same review: hard kills at five earlier install stages; two concurrent provisions; a hard-killed lock holder on Windows and Linux; an upgrade over a running child; the retry policy for each status class; a heartbeat restart over a changed, missing, or held binary never executing it; non-ASCII and very long paths; the download child dying with its parent; a killed cache-claim holder.

### closing-review | info | every plan step is closed and each earlier finding has a landed change

Reviewed 2026-10-06 against the plan and the accepted decision, by the author and not by an independent reviewer: delegation was withdrawn after the process incident recorded below. The findings above map to landed commits as follows. Working-directory execution and import shadowing: `9ee5bd95`, and the child-interpreter commits before it. The persisted backend choice: `9a80b406`. Install classification and the killed-install recovery: `f3e831a6`. Model revisions, per-file digests, safetensors only and verified import of repository code: `960027fd`. The one service-environment judgement, including the readiness remedies and the host role read from an unrelated distribution: `bc1f583c`. Stopping the whole server tree and restart accounting: `864e0b97`. The whole-fetch deadline, the shared wait and cache-fault classification: `0e5893e9`. Interrupt envelopes, next actions in JSON, and a JSON mode for warmup: `93acc847`, corrected by `1674b241`. The shared child teardown: `e5a563aa`. Help text and the provisioning guide: `732b69de`. Evidence: the complete unit tier on Windows, 7338 passed in seven bounded runs with four tests deselected for want of a compiled monitor binary, and break-and-restore proofs recorded per step in the ledger.

### stop-leaves-launcher-started-server | high | a stop ended the supervised process and not the server it had started

Found during execution and fixed in `864e0b97`. `src/vaultspec_rag/qdrant_runtime/_child_tree.py` ends the job on Windows and the process group elsewhere. The test stand-in at `src/vaultspec_rag/tests/_fake_qdrant_binary.py` had been written to watch its own ancestors, which is how the defect stayed hidden from every supervisor test.

### linux-run-replaced-the-windows-environment | high | running the suite under WSL against the Windows checkout removed most of its virtual environment

A process fault of this session, not a product defect. The Linux interpreter was pointed at the checkout on the Windows drive, tests in that tree shell out to `uv`, and a Linux `uv` treats a Windows environment directory as invalid and replaces it. It removed the package directory and part of the scripts directory and stopped at an interpreter that was in use. No tracked file changed. The environment was restored with `uv sync --locked --group dev` and confirmed to hold the GPU build again. The Linux sweep was stopped at that point.

### linux-lane-not-swept-end-to-end | medium | the closing Linux run covers modules a to m only

Targeted Linux runs accompanied each step and are in the ledger. The closing sweep reached modules a through m and was then stopped for the reason above, so modules from n onward were last run on Linux at the step that touched them, not after the final commit. Two failures seen in the sweep are environmental: git inside WSL cannot read this worktree's metadata, and the development runner's fixture needs a `python` on the path. One was real and is fixed: a start test that met the client refusal on a lane without the inference stack.

### tiers-and-platforms-not-run | medium | nothing here was proven on a GPU, against a running service, or on macOS

The GPU and integration tiers were not run, no real `server start` was performed end to end, and no model was loaded on a device, so the cache-only verifying load at `src/vaultspec_rag/embeddings.py` and the sparse import at `src/vaultspec_rag/_sparse_encoder.py` are proven by unit tests and static reading only. macOS was never run; the process-group stop relies on `os.waitid`, present there from Python 3.13.

### orphan-reap-acts-on-one-pid | low | the startup reap of an orphaned server signals the recorded process alone

`src/vaultspec_rag/qdrant_runtime/_resolve.py` reaps by the recorded pid on POSIX and by tree on Windows. It refuses a process whose image is not qdrant, so a launcher's orphan is refused rather than half-ended, and the operator is told to stop it by hand.

### owned-by-vaultspec-core | medium | two working-directory lookups cannot be fixed in this repository

The MCP entry that vaultspec-core renders launches `python -m vaultspec_rag.server` in the workspace directory without safe-path mode, and its `require_executable` helper is built on a search that takes the working directory first on Windows. Both need a change in vaultspec-core.

### live-tiers-run | info | the GPU and integration tiers and a real start were run on a Windows host

Run 2026-10-06 on an RTX 4080 SUPER against a service started with its own status and storage directories, so the operator's service and machine lock were not touched. A first `server start` downloaded and verified the pinned Qdrant archive; a second downloaded nothing; a third started in 28.2 seconds with all three models loaded on the device from the verified cache, and `server doctor` reported it ready. The resident tiers gave 740 passed, 8 failed, 2 skipped. The subprocess tier gave 71 passed, 3 failed of 74 on its second run; its first run was 34 passed, 3 failed, 37 errors, for the reason in the next entry. Of the eleven failures, three came from this work and are fixed and were re-run against the live service: the two entries below and one test that still expected the ONNX backend to be tried for a pinned model (`bde28ac0`). Eight are in code and tests this work does not change and are reported to the project's tracker with their output, not fixed here. The service was stopped through `server stop` and its launcher, daemon and Qdrant processes were confirmed gone. This supersedes the GPU and running-service part of `tiers-and-platforms-not-run`; macOS is still unrun.

### live-fixture-waited-for-removed-log-line | medium | every test that starts a service failed at setup on a line the service no longer writes

Found by the subprocess tier. The service now loads every model from the cache alone and has no mode to report, and the live-service fixture at `src/vaultspec_rag/tests/integration/conftest.py` still required the removed cache-only log lines. The unit tier could not see it: the fixture's one unit test wrote the expected line itself. Fixed in `05745ee7`; the fixture now requires each model's load to be reported with the hub switched off and the hub's address absent, and a unit test proves both refusals can fail.

### stop-returned-before-server-gone | high | on Windows a stop could return while the Qdrant process was still alive

Found by the resident tiers and fixed in `3492dd7a`. Ending the job and then terminating the process directly made the wait return on the recorded exit code before the process had gone. `src/vaultspec_rag/qdrant_runtime/_child_tree.py` now terminates directly only when the job did not take the process, and confirms on the process itself and on the job's member count.

### library-beside-verified-executable | high | a file planted beside the managed server would be loaded into it with its digest still matching

Raised by the independent review and confirmed: the pinned Windows executable imports libraries Windows does not take from its known set, and Windows looks beside the executable first. Fixed in `27cffa4c`. `src/vaultspec_rag/qdrant_runtime/_managed_install.py` judges the version directory wherever it judges the executable, on every platform, and `src/vaultspec_rag/qdrant_runtime/_spawn_trust.py` lists it before a process is created and again once it exists. Anything but the executable, the manifest and an install's working files refuses the start under `qdrant_install_foreign_files`, and no install removes it. Proven against the real installed binary: with a file planted, `server qdrant status` reported the refusal and `server start` exited non-zero with one envelope and no server process. Residual, stated in the module and the guide: nothing can close a directory to new files, so a file written and removed between the two listings is not seen. An operator's own binary is not judged on its directory; the guide says to keep that directory trusted.

### independent-review-outcomes | medium | an independent review of the branch returned revision required with nothing critical

Delegation was re-authorised for this review and for two bounded fixes, each in its own working tree with no push. Landed after being read and re-gated by the author: a process's image is read through psutil where `/proc` has none, so a live server on macOS is no longer refused as someone else's (`fe673f9c`); the exit peek asks whether the platform has it and states what is given up where it does not (`ed15acde`); PowerShell is taken from the operating system's directories and not from the search path (`7a17cb7d`); a docstring that still said the daemon loads online-capable (`7c6eec5c`). Accepted without change: an install hashes the staged file by descriptor and replaces by path, which the hold at every spawn covers. Left alone: the changelog's version and date, which release automation owns. Unexecuted: the branches that run only without `/proc` or without the peek, and the whole process-group stop, were not run on this host; Linux runs them in continuous integration and macOS runs none of this.

### tests-launching-uv-on-the-checkout | medium | a test session could let uv replace the checkout's environment

Follow-up to `linux-run-replaced-the-windows-environment`, decided and landed in `741c7c20` and `3b616b71`. The launch that did it was the development gates' environment probe, `uv run --no-sync python -c`, reached from a test: uv creates or replaces a project environment before it reads that flag. A test may now launch `uv run --no-sync` only on the environment its own interpreter runs from; every other project verb must target the temporary tree, and a session started from any other interpreter points uv's project environment into its own temporary tree for its duration. The session audit hook had also never read that launch on Windows, because its command-line splitter gave up on program text. Not run: a session from the checkout's own environment under the new hook before this entry, and anything off Windows.

### push-to-a-ready-pull-request-runs-light-lint | info | a green check after a push does not mean the suites ran

The merge gate runs the full suites when a pull request is opened or marked ready, or when a user applies the full-run label; a push to a ready pull request runs the light lint alone and the gate passes on it. The Linux lane for this work is therefore the labelled run on the head commit and nothing else.

### vaultspec-core-lookups-landed | info | both working-directory lookups owned by vaultspec-core are fixed there

Resolves `owned-by-vaultspec-core`. The rendered MCP entry now launches the interpreter in safe-path mode and executable lookup no longer takes the working directory; merged in that project as `57258a86`, with both of its issues closed.

## Recommendations

- For `path-tier-cwd-exec`: a follow-on ADR must decide whether an implicit PATH lookup remains a resolution tier at all once provisioning is automatic.
- For `pre-exec-self-attested`, `respawn-unverified`, and `recovery-dead-end`: a follow-on ADR must decide where the executable digest is anchored and at which points it is checked.
- For `start-does-not-provision`: a follow-on ADR must decide the consent model for the binary on `server start`, and where the client and host roles are gated relative to any download.
- For `install-not-atomic` and `download-hardening`: stage, verify, then replace; serialise provisioning; bound the download; route the source through settings. The override shape for the source is a decision for the same ADR.
- For `duplicate-model-fetch` and `stale-provisioning-prose`: collapse to one implementation and correct the prose in the change that touches each site.

Added at plan close. Run the GPU and integration tiers and one real `server start` on a host before release, and run the unit tier on macOS. Run the Linux lane from a checkout that lives on a Linux filesystem, never from the Windows drive. Decide whether a test may shell out to `uv` with the checkout as its working directory at all; that is a decision for a follow-on record, because the same hazard exists for anyone who runs the suite from two operating systems against one tree. Raise the two vaultspec-core lookups with that project.

Added after the live run. Of the paragraph above, the GPU and integration tiers and the real start are done, the `uv` question is decided and guarded, and the vaultspec-core lookups are fixed in that project. Still open: run the unit tier on macOS, where the image probe, the exit peek and the process-group stop have never executed. The eight live failures reported to the tracker are in code this work does not change and need an owner there. A mitigation that makes Windows prefer its own directory for a child's libraries would close the window `library-beside-verified-executable` leaves, at the cost of creating the server process through the platform call directly; whether that is worth it is a decision for a follow-on record.
