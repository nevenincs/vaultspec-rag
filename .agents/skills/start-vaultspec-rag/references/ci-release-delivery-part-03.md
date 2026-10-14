# CI, builds and release delivery: evidence group s1-0150

Read this part when working with: [tests/smoke_check.py](../../../../tests/smoke_check.py).

This is static evidence. Implementation observations, documentation claims, and test expectations remain distinct; no tests were run. An imported dependency uninspected within this evidence group may be covered in another capability reference. All listed full-file ranges are covered; report-local dependency boundaries are not inventory gaps.

[CI, builds and release delivery](ci-release-delivery.md) provides module summaries, connections, and reconciled limitations.

## Capability summary

- [tests/smoke_check.py](../../../../tests/smoke_check.py) is a standalone smoke-check harness for an installed wheel or sdist, rather than a pytest suite. It states a CI invocation and deliberately uses `check_*` names and a [tests/smoke_check.py](../../../../tests/smoke_check.py) filename to avoid pytest collection because failures call `sys.exit(1)` (lines 1–17).
- `_fail` prints a failure to stderr and exits with status 1; `_run_script` resolves a named executable from PATH or falls back to `python -m`, captures UTF-8 output, and applies a 30-second timeout (lines 36–60).
- Checks cover the requested interpreter, package import, installed version metadata, both console-script entry-point names, the installed canonical MCP builtin resource, and the installed `vaultspec-core` version floor and required callable MCP lifecycle exports (lines 63–145).
- Checks also require both CLI help commands to exit successfully (lines 147–165), then exercise installed CLI MCP enrollment in a temporary project directory. The enrollment expectation accepts either an operator-approval hold for both Claude and Codex with no `.mcp.json` enrollment and an approval hint, or successful enrollment in both native project configs followed by status and dry-run selective-uninstall checks (lines 168–249).
- The `__main__` block invokes all checks in sequence and prints a final success message only after they return (lines 252–262). This is an expectation encoded by the harness, not a recorded passing run.

## Interfaces and data flow

- Entry point: direct script execution invokes nine checks in order (lines 252–262). The file documents `uv run --isolated --no-project --with dist/*.whl [tests/smoke_check.py](../../../../tests/smoke_check.py)` as its CI invocation (lines 9–16).
- Inputs: `UV_PYTHON` optionally specifies a version prefix checked against the running interpreter's major/minor version (lines 63–78). Other inputs are the installed Python environment and availability of its console scripts or fallback modules (lines 41–60).
- Outputs/failure behavior: checks emit `PASS` lines on success; a failed condition emits `FAIL` to stderr and exits 1 (lines 36–38 and the check implementations). `_run_script` captures stdout/stderr and the enrollment helper parses JSON from stdout (lines 41–60, 168–188).
- State/storage: enrollment runs against a `TemporaryDirectory`; the script reads `.mcp.json` and `.codex/config.toml` from that target, then removes the temporary directory on context exit (lines 210–249). It calls uninstall with `dry_run=True` (lines 240–248).
- Integrations asserted by the source: Python package metadata and entry points; `vaultspec_rag` and its packaged `builtins/mcps/vaultspec-rag.builtin.json` resource; `vaultspec-core` metadata and `vaultspec_core.core.mcps` exports; the `vaultspec-rag` and `vaultspec-search-mcp` launchers; Claude and Codex project MCP config formats (lines 81–145, 147–165, 210–248). Implementations behind these imports and tools were not inspected.

## Boundaries and dependencies

- The sole inspected project file is a test harness; it does not define product implementation behavior. Its assertions constrain the installed artifact and some `vaultspec-core` APIs without showing their implementations (lines 96–145, 210–248).
- The harness makes subprocess calls to installed scripts or fallback modules and checks their observable exit codes/output; module mapping is explicitly provided only for the two named commands (lines 41–60).
- MCP enrollment behavior is checked via temporary project files and imported Core status/uninstall APIs. The branch logic treats an approval hold as valid only when both providers are skipped, `.mcp.json` is absent, and each provider warning names `spec mcps trust`; otherwise it expects both canonical entries and a two-provider status (lines 191–207, 220–248).
- Dependencies not inspected: implementation of `vaultspec_rag`, packaging metadata/build configuration, `vaultspec_core`, console-script definitions, and any CI workflow. The docstring claims the scripts check installed artifacts, but no packaging or CI source was in scope (lines 1–16).

## Evidence

- The script presents itself as a distribution smoke check, documents its CI invocation, and excludes pytest collection by naming convention — [tests/smoke_check.py:1-17](../../../../tests/smoke_check.py#L1) — documentation claim.
- Failure exits, executable lookup, fallback module mapping, subprocess capture, and timeout — [tests/smoke_check.py:36-60](../../../../tests/smoke_check.py#L36) — test-harness implementation.
- Interpreter version, package import/version, entry-point names, canonical builtin shape, Core version floor and callable exports — [tests/smoke_check.py:63-145](../../../../tests/smoke_check.py#L63) — test expectations and harness implementation.
- CLI `--help` exit expectations — [tests/smoke_check.py:147-165](../../../../tests/smoke_check.py#L147) — test expectations.
- Install invocation and JSON provider-result extraction — [tests/smoke_check.py:168-189](../../../../tests/smoke_check.py#L168) — test-harness implementation.
- Approval-held branch conditions — [tests/smoke_check.py:191-207](../../../../tests/smoke_check.py#L191) — test expectations.
- Temporary project enrollment config shape, status providers, and dry-run uninstall result — [tests/smoke_check.py:210-249](../../../../tests/smoke_check.py#L210) — test expectations.
- Ordered execution and success banner — [tests/smoke_check.py:252-262](../../../../tests/smoke_check.py#L252) — test-harness implementation.

## Uncertainty and follow-up

- No unresolved questions about the assigned file. To verify the implementation behind the smoke expectations, request separate reads of `vaultspec_rag` CLI/MCP modules, the canonical builtin resource and packaging metadata, and `vaultspec_core.core.mcps`; to verify the stated CI use, request the workflow source. Those files were outside this slice and were not read.
