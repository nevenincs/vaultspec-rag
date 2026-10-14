---
tags:
  - '#audit'
  - '#monitor-provisioning'
date: '2026-10-14'
modified: '2026-10-14'
body_schema: 'body-v2'
body_hash: 'sha256:ea89402138a03535785336069300cdb18832c565ffb3780b188e611eed8b2287'
related:
  - "[[2026-10-13-monitor-provisioning-plan]]"
---

# `monitor-provisioning` audit: `Integrated review of automatic monitor provisioning`

## Scope

Integrated review of `2026-10-13-monitor-provisioning-plan` Steps S01 to S06, diff `ef49416b..8d17ff52` on `feat/monitor-provisioning`, against `2026-10-13-monitor-provisioning-adr` and the records it reconciled. Three workflows were traced end to end: a wheel install's first `server start`, the release pipeline from monitor compile to bundle, and a development checkout after `just build-monitor`. Verdict: revision required. The high findings reopen S03 and S06.

## Findings

### bundle-sibling-tier | high | the sibling tier cannot see a bundle's own monitor, so every bundle install downloads one

`src/vaultspec_rag/_program_lookup.py:116` derives the installation's program directories from `sysconfig` scripts and `sys.executable`. `src/vaultspec_rag/monitor_runtime/_resolve.py:222` resolves the sibling tier from those directories. A bundle is a PyApp launcher that installs the embedded wheel into its own cache venv (`tools/binaries/build_pyapp.py:211-232`), so both directories point inside that venv, not at the extracted archive that holds the monitor. With the PATH tier removed, a bundle install falls through to the managed tier and downloads a monitor it already has. `src/vaultspec_rag/tests/test_monitor_resolution.py:107` stubs the accessor, so no test covers the real layout. Running a built bundle once confirms or dissolves this finding.

### working-directory-guard | high | the guard records a mutation proof that was never obtained, and it cannot fail on what it guards

`src/vaultspec_rag/tests/test_program_lookup_sites.py:142-177`. The docstring claims a bare-name mutation fails the test, but the S06 ledger records that the mutation did not fire. The assertions on both branches always hold. `assert not ran.exists()` passes vacuously when resolution refuses first. Separately, `executable=held.launch_path` masks the mutation.

### staging-sweep | medium | a killed provisioning run leaks staging files that nothing removes

`src/vaultspec_rag/monitor_runtime/_provision.py:149,298-316`. The `finally` cleanup misses a hard kill. `retire_superseded` (`:327`) only removes other versions' directories. Qdrant sweeps abandoned staging files (`src/vaultspec_rag/qdrant_runtime/_provision.py:915`) under its lock; the monitor has no lock and no sweep.

### readiness-hash-budget | medium | the monitor readiness row hashes about 90 MB with no time limit on a polled route

`src/vaultspec_rag/_readiness.py:722-781` calls `resolve_monitor()` without a time limit, while the Qdrant dimension uses `bounded_call` and reports `qdrant_binary_unchecked` (`:544-586`). The readiness report is served at `/readiness` (`src/vaultspec_rag/server/_routes.py:917`).

### monitor-download-deadline | medium | the download deadline was sized for a 30 MB archive, not the 90 MB monitor

`src/vaultspec_rag/monitor_runtime/_provision.py:99` uses the default 900-second deadline from `DownloadLimits()` (`src/vaultspec_rag/native_binary/_download.py:176`). That roughly triples the minimum bandwidth a start needs to succeed, and there is no resume.

### cross-version-retire | low | retiring an old version can race a concurrent install of another version

Without a lock, `retire_superseded` (`src/vaultspec_rag/monitor_runtime/_provision.py:327`) can remove another version's directory while that install is still running. The result is one failed start that the next start repairs.

### free-space-admission | low | there is no free-space check before installing

A full volume is reported once as an unrecoverable write error that names the volume (`src/vaultspec_rag/monitor_runtime/_provision.py:275`). The only cost is a wasted transfer.

### dev-install-location | low | the development monitor is installed in the interpreter's own scripts directory

This is valid under the ADR's Resolution constraint, since the managed install is only an implementation hypothesis. But a daemon running under a different interpreter does not see the monitor.

### init-recipe | low | `just init` does not build the monitor

`just build-monitor` remains a separate one-time step in a development checkout. This is not a regression.

### start-banner | low | the start progress line omits the monitor

`src/vaultspec_rag/cli/_service_start.py:376` names only models and Qdrant.

### no-verify-commit | low | the S06 commit passed `--no-verify`

The `gates-run-explicitly` rule forbids passing it. No hook existed, so nothing was skipped.

### env-surface | high | the environment template gates fail because the bundle fix reads PYAPP and an exemption went stale

Re-review of `bb128a3f..63fd1c7f`. `src/vaultspec_rag/tests/test_env_example_coverage.py` fails twice. `.env.example` documents no entry for `PYAPP`, which `src/vaultspec_rag/_program_lookup.py:177` now reads. The `GITHUB_ENV` exemption at `test_env_example_coverage.py:61` is stale since S06 removed the write. The earlier bundle-sibling-tier and working-directory-guard findings are resolved by `6e1f8530` and `63fd1c7f`, as are staging-sweep, readiness-hash-budget, monitor-download-deadline and start-banner.

### staging-pid-parse | medium | the sweep reads an all-digit random token as the pid, so it can delete a live run's staging file

`src/vaultspec_rag/native_binary/_install.py:170-180` takes the last all-digit component of the name. The 12-character hex token is all digits about once in 270 names, so a live writer reads as dead and its fresh file is swept. Tests use the token `0123456789ab`, which hides the defect.

### env-template-path-text | low | `.env.example` still says the monitor is found on the search path

`.env.example:1029-1035`.

### sibling-unreadable | low | an unreadable sibling candidate aborts resolution before the managed install is tried

`src/vaultspec_rag/monitor_runtime/_resolve.py:235-239,287`.

### final-review | low | the review passes once env-surface and staging-pid-parse are resolved

`30708f0c` catalogues `PYAPP` in `.env.example` as read-only, drops the stale `GITHUB_ENV` exemption, and reads the staging pid by position. A mutation proof with an all-digit token is recorded in the ledger. `test_env_example_coverage.py` and `test_monitor_provisioning.py` were re-run: 28 passed. The sibling-unreadable finding stays open by judgement: the behaviour is fail-closed, and no falsifying test can be built on Windows. Pending verification: one built-bundle rehearsal of the launcher sibling tier. Pending on the user: `dev lint links` fails on user-owned `.vaultspec/skills/start-vaultspec-rag/references/*`, and `uv.lock` is stale at the branch base.

### ci-guards | high | five repo-wide guard tests failed on PR #615 because no Step's selection ran them

CI's correctness job on PR #615 failed: duplicate bodies between the monitor and Qdrant provisioners, an unconsumed `expected_monitor_sha256`, a symlink-interpreter test, and substitution accounting. Every Step had run `-k` selections, never the whole suite. Resolved by `bd50bc3b`, which converges on the integration branch's `operator_path_fault` and `whole_body_matches` and removes empty install directories after a refused install. The whole accelerator-free suite passed: 8270 passed, 0 failed.

### worker-checkout | low | the fix worker ran `git checkout -- src/vaultspec_rag/native_binary/__init__.py`

The `gates-run-explicitly` rule forbids checking out paths. The worker reports that only that file's whitespace-only difference was involved. The file matches HEAD.

## Recommendations

- bundle-sibling-tier: resolve the sibling tier from the bundle launcher's own directory as well as the venv. Add a test that places the monitor in a real bundle-shaped layout. Confirm with one built-bundle run.
- working-directory-guard: make the guard able to fail by asserting the spawned image against `resolve_monitor().path`, or correct the docstring to say no falsifying mutation was obtained.
- staging-sweep: sweep staging files on entry when the pid that created them is dead or they are older than the download deadline.
- readiness-hash-budget: wrap the monitor resolve in `bounded_call` and add a `monitor_unchecked` code.
- monitor-download-deadline: give the monitor request its own deadline through `_InstallRequest.limits`.
- start-banner: name the monitor in the progress line.
- None of these needs a new decision.
- env-surface: catalogue `PYAPP` in `.env.example` beside `PATH` as read-only, not a knob, and drop the stale `GITHUB_ENV` exemption.
- staging-pid-parse: read the pid positionally, as the second-to-last component, and test it with an all-digit token.
- env-template-path-text: correct the sentence while editing that block.
- sibling-unreadable: consider skipping an unreadable sibling while still refusing an unreadable managed install.
