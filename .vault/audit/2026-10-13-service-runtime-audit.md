---
tags:
  - '#audit'
  - '#service-runtime'
date: '2026-10-13'
modified: '2026-10-14'
body_schema: 'body-v2'
body_hash: 'sha256:be17acd2b7f18aa93b7b01674b630a0e7832bc1ad72e898c1c1eaa88d025aba1'
related: []
---

# `service-runtime` audit: `clean-machine install and provisioning lab`

## Scope

Every documented and commonly attempted install route for the 0.6.0 PyPI release, run as a clean user on a real GPU: a Linux container with GPU passthrough (Python 3.13, uv 0.12, RTX 4080 SUPER, driver 610.88) and a sandboxed Windows 11 user with redirected profile, uv, Hugging Face and service directories. Routes: `uv tool install "vaultspec-rag[gpu,mcp]"` with the CUDA index, `pip install "vaultspec-rag[gpu,mcp]"` into a venv, and `uvx vaultspec-rag server start`; each followed by `install`, `server start`, `server doctor`, `status`, `index`, `search` and `server stop`, with every exit code recorded. Also read: every install and provisioning `--help` text, the README install section and `docs/installation.md`.

## Findings

### wheel-start | critical | No wheel route can start the service

Both Linux wheel routes provisioned the three models and the Qdrant binary, then `server start` failed in the daemon with "The compiled vaultspec-rag-monitor executable is required. Install it alongside vaultspec-rag or set VAULTSPEC_RAG_MONITOR_BINARY to its absolute path." The wheel carries no monitor (`src/vaultspec_rag/monitor_process.py:37-60`). Covered by `2026-10-13-monitor-provisioning-adr`.

### uvx-start | high | `uvx vaultspec-rag server start` refuses with a self-contradictory message

The one failure printed: a warning that "the installed tool env is broken" when no tool is installed; a `uv pip install --python <uv cache environment>` command; `uv tool install --python 3.14 ...` (Windows) and three lines later `uv tool install --python 3.13 ...`; "The repair applies in place, so nothing has to be stopped"; "cannot run the GPU-only service: not needed (this installation is a client)"; and "does not provision its own python". Three renderers each add their own remedy: `_ephemeral_env_warning` (`src/vaultspec_rag/cli/_service_start.py:1068`), `_fail_unusable_environment` (`src/vaultspec_rag/cli/_service_start.py:650`) and the `NOT_APPLICABLE` remediation (`src/vaultspec_rag/operator_state/_installation.py:106`). The `--python` version is read from the uvx cache environment's `pyvenv.cfg` (`src/vaultspec_rag/operator_state/_provisioning.py:344`), not from `HOST_PYTHON`. There is no route by which a bare `uvx` or a GPU-less install can ever start the service: the daemon always runs from the launching interpreter (`src/vaultspec_rag/cli/_process.py:480`).

### doctor-false-ready | high | `server doctor` reports ready after a failed start

Immediately after each failed start, `server doctor` printed "Readiness: ready for requests" and exited 0, beside "no service has been started". After the uvx refusal it reported torch, models and Qdrant as "ready - not needed". It does not check the monitor. The exit code ignores dependency readiness (`src/vaultspec_rag/cli/_service_doctor.py:135`). This contradicts `2026-06-24-service-doctor-liveness-adr`.

### windows-pip | high | Windows pip install provisions nothing, exits 0, and prescribes a uv-project repair

PyPI's Windows torch is CPU-only. `install` exited 0 with models and Qdrant skipped; the cause, nested three parentheses deep, was repeated three times and said to install the GPU build "on a CUDA-capable machine" on a CUDA-capable machine. Both `install` and `server start` prescribed "vaultspec-rag install, then uv sync --reinstall-package torch", which does not apply to a pip venv with no `pyproject.toml` (`src/vaultspec_rag/operator_state/_provisioning.py:679-701`).

### status-next-action | medium | `status` suggests indexing while no service runs

With the service down, `status` gave "Next action: vaultspec-rag index --type all", which then failed. The selector reads index counts only (`src/vaultspec_rag/cli/_status.py:69`).

### install-noise | medium | A successful host install prints irrelevant PyTorch and pyproject lines

A uv-tool host install printed "PyTorch configuration: not found", "PyTorch: skipped (torch configuration handled by the dedicated PyTorch step (it patches pyproject.toml ...))", "Provisioning: mixed" and a missing-`pyproject.toml` warning (`src/vaultspec_rag/commands/_torch_flow.py:173-175`, `src/vaultspec_rag/commands/_provision.py:578`), plus two MCP-trust warnings naming `--source-from-cwd`.

### help-surface | medium | Install and start help describe internals

`install --help` lists 18 options, about ten of them internal mechanisms (`--torch-config`, `--tool-repair`, `--torch-group`, `--sync`, `--mode`, `--skip`, `--skip-models`, `--skip-qdrant`), inside a 150-word description (`src/vaultspec_rag/cli/_install.py:128-350`). `server start --help` carries `--local-only` and `--qdrant/--no-qdrant` with a precedence rule, and `--qdrant-auto-provision`. The README asks every user for `install --no-torch-config`.

### mcp-trust | medium | Workspace MCP registration is skipped on a clean install

`install` reported "MCP server 'vaultspec-rag' is not approved for claude (project)" and skipped registration, and a peer session's full run shows about 81 install integration failures where `.mcp.json` and the `.vault` links are never created.

### first-index | high | The first index of a new repository fails until `--rebuild` is passed

In a clean Linux container on `fix/install-ux`, the README route reached a ready service, and `vaultspec-rag index --type all` (the next action `status` names) queued three incremental jobs that all failed: vault and documents with "publication proof does not exist; an explicit rebuild is required" (`src/vaultspec_rag/_publication_state.py:101-106`), code with "storage no longer backs the published code index metadata". `index --rebuild --type code` then built the index and search returned `src/retry.py`. Incremental refusal on missing proof is decided (`2026-09-08-incremental-publication-cost-adr`, `2026-10-12-destructive-rebuild-lifecycle-adr`: incremental cannot escalate to a rebuild), and no record decides what the first index of a never-indexed root is. The watcher's automatic reindex reaches the same refusal for a new root.

### doctor-holder-advice | low | Doctor told a fresh service to restart for a new build

`server doctor` printed "restart it with `vaultspec-rag server stop --port 8766` then `vaultspec-rag server start --port 8766` to pick up the new build" for the service it had just started (`src/vaultspec_rag/operator_state/_holders.py:67-87`). The remedy belongs to an in-place repair, and none was pending. Fixed on this branch.

### client-backend-line | low | A client install pointed backend choice at a host it no longer needs

"not saved: a client installation does not choose the backend of the service; the host installation that runs it does" (`src/vaultspec_rag/commands/_backend_choice.py:130-137`) after the README route, which has no separate host. Fixed on this branch.

### doctor-ready-regression | high | Doctor reports not ready while a healthy service answers a client

With a `RUNTIME_REQUIRED` plan, `src/vaultspec_rag/cli/_service_doctor.py:176-180` puts an `unknown` torch row into the dependency axis, which `src/vaultspec_rag/_readiness.py:28` treats as blocking, so a project client's `server doctor` beside a live host service exits 1 with "dependencies not ready". A start there would succeed as already running. Reopens S04.

### runtime-refusal-loop | medium | A runtime that cannot serve offers the command that just failed

`src/vaultspec_rag/service_runtime.py:544-550` reuses the launching capability's remediation, so a runtime that resolved a CPU wheel is told to run `server start` again, which rebuilds and fails identically.

### stale-docs | medium | Two guides document the retired client refusal and a removed error code

`docs/service-mode.md:44,449,516` and `docs/provisioning.md:106,111-120,490` describe the refusal and the `service_env_no_gpu` code this branch removed; `docs/automation.md:151-157` states the old doctor exit-code split.

### tool-install-client-line | medium | A uv tool host in a repository reports itself as a client

The tool-environment torch gate sets `not_applicable`, which `src/vaultspec_rag/cli/_render.py:694` labels "this installation is a client", and `src/vaultspec_rag/commands/_provision.py:558-568` adds a skipped torch row that turns the outcome `mixed`.

### download-before-guards | medium | A start refused by the machine guard has already built the runtime

`src/vaultspec_rag/cli/_service_start.py:1009-1015` creates the runtime before `_guard_start_preconditions`, so a refusal can follow a multi-gigabyte download.

### daemon-child-env | medium | The runtime daemon inherits interpreter-scoped variables

`src/vaultspec_rag/cli/_process.py:385-393,639-643` passes `PYTHONPATH`, `PYTHONHOME` and `PYTHONSTARTUP` to a daemon running under a different interpreter, which can import a checkout instead of the judged release.

### next-actions-contract | low | Start `next_actions` can carry a sentence instead of a command

`src/vaultspec_rag/cli/_service_start.py:695-701`.

### enum-duck-typing | low | Torch-line suppression compares a stringified attribute

`src/vaultspec_rag/cli/_render.py:809`.

### admission-read-escape | medium | A corrupt run ledger escapes first-build admission as an unhandled error

`src/vaultspec_rag/_job_admission.py:119-124` handles four proof errors, not `UNREADABLE_PUBLICATION_ERRORS` (`src/vaultspec_rag/_publication_state.py:43-48`), so a non-SQLite ledger raises `sqlite3.DatabaseError` through `src/vaultspec_rag/server/_routes.py:313-322` and aborts every domain of one request with a 500.

### watcher-spec-duplication | low | The watcher builds its index spec outside admission

`src/vaultspec_rag/watcher_execution.py:297-306` constructs the incremental spec that `index_job_spec` owns.

### eager-storage-reading | low | Admission counts points for sources that have already published

`src/vaultspec_rag/_job_admission.py:96-103`.

### stale-docstrings | low | Doctor readiness and admission lock-order docstrings describe old behaviour

`src/vaultspec_rag/cli/_service_doctor.py:192-196`, `src/vaultspec_rag/_job_admission.py:139-140`.

### mcp-incremental-wording | low | MCP reindex tools say incremental and can run a first build

`src/vaultspec_rag/mcp/_tools.py:634-648,673-688`.

## Recommendations

- wheel-start: implement `2026-10-13-monitor-provisioning-adr`.
- uvx-start and windows-pip: decide whether `server start` may run the daemon from an environment other than the launching one, so GPU-less launchers can start the service; that is a follow-on ADR.
- uvx-start: whatever that decision, render one cause and one command per refusal, built for the environment and platform at hand.
- doctor-false-ready: restore `2026-06-24-service-doctor-liveness-adr`; include every start dependency, and exit non-zero when a start would fail.
- status-next-action, install-noise and help-surface: routine corrections within settled decisions.
- mcp-trust: diagnose against the current vaultspec-core trust contract.
- first-index: decide whether the first index of a root that has never published is an implicit full build, or whether the next action names `index --rebuild`; it is an amendment to `2026-10-12-destructive-rebuild-lifecycle-adr`.
- doctor-ready-regression through enum-duck-typing: routine corrections within `2026-10-13-service-runtime-adr`; fix on this branch.
- admission-read-escape through mcp-incremental-wording: routine corrections under the 2026-10-14 amendment; fix on this branch, with a guard for concurrent first-build admission.
