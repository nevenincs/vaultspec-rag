---
tags:
  - '#reference'
  - '#tool-mode-cuda'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:8bf904f4b12ea989714f89e7856670f2eacc530c0cd7340b14e2b73f799725af'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-adr]]"
---

# `tool-mode-cuda` reference: `installer and service ownership seams`

This code audit maps the production seams needed to repair a CPU-only CUDA
installation in a persistent `uv tool` environment without creating another
installer or another service-ownership check.

## Summary

`cli/_gpu_errors.py:35` owns environment classification. Its pure
`classify_runtime_env` and `classify_interpreter_env` distinguish a persistent
tool environment from an ephemeral cache or project venv. The same module's
`_durable_install_command` constructs the required receipt-carrying invocation:
it pins a CUDA wheel by direct URL, preserves the active interpreter ABI
including free-threaded builds, selects the published platform tag, and asks uv
to recreate the tool on that matching Python request. `durable_tool_install_command`
currently renders this command for users only; no production path executes it.
The package-and-extra request must stay derived from the existing tool-mode
specification in `builtins/mcps/vaultspec-rag.builtin.json:1`, rather than
introducing a second installer literal.

`cli/_process.py:412` owns the torch-free subprocess probe of a chosen
interpreter. `_probe_daemon_cuda` returns a definitive blocking result for
missing torch, a CPU-only wheel, or no visible GPU, while retaining a distinct
inconclusive result for timeout and opaque probe failures. This is the probe a
tool repair should reuse rather than importing torch from an installer path.

`commands/_install.py:844` is the public installation transaction and delegates
the project-surface torch work once to `commands/_torch_flow.py:140`. That flow
edits a target `pyproject.toml` and optionally invokes `uv sync` through
`commands/_uv_sync.py:18`; it cannot alter the isolated environment created by
`uv tool install`. The new tool repair belongs in the installer orchestration
beside this existing flow, with its own structured report outcome, not inside
the project mutation backend.

`cli/_service_start.py:390` provides the existing validated ownership detector
for a current daemon. It validates the status record using the PID, health
endpoint, and service token through `_is_our_service` in `cli/_process.py:112`.
`serviceclient/_discovery.py:536` has a machine-wide conservative resolution
for unknown or degraded lock holders. A repair must use this evidence rather
than treating a readable status file as permission to replace a tool directory:
a live or unverifiable holder must refuse before invoking uv.

The focused tests already exercise the pure environment classifier, receipt
command construction, CUDA probe, and installer confirmation/report patterns in
`tests/test_service_env_preflight.py`, `tests/test_cli_install.py`, and
`tests/test_install_torch_config.py`. No source or test currently invokes
`uv tool install`, inspects a tool receipt after mutation, or supplies a
tool-repair consent path.

uv owns the receipt in the tool directory. A repair may inspect its parsed
direct requirements after a successful child process to establish that the
CUDA wheel is durable, but must never hand-write it or depend on formatting
outside the direct torch requirement. The repair is also replacing the
environment that runs the installer; a Windows execution proof is required
before release, because the live CLI itself may retain handles after the
resident service stops.
