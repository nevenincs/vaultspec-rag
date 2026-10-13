---
tags:
  - '#audit'
  - '#service-runtime'
date: '2026-10-13'
modified: '2026-10-13'
body_schema: 'body-v2'
body_hash: 'sha256:eda7238344b8335de00532a5bcf1ab6ca490c0c0e8c463fe983a988f1528e711'
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

## Recommendations

- wheel-start: implement `2026-10-13-monitor-provisioning-adr`.
- uvx-start and windows-pip: decide whether `server start` may run the daemon from an environment other than the launching one, so GPU-less launchers can start the service; that is a follow-on ADR.
- uvx-start: whatever that decision, render one cause and one command per refusal, built for the environment and platform at hand.
- doctor-false-ready: restore `2026-06-24-service-doctor-liveness-adr`; include every start dependency, and exit non-zero when a start would fail.
- status-next-action, install-noise and help-surface: routine corrections within settled decisions.
- mcp-trust: diagnose against the current vaultspec-core trust contract.
