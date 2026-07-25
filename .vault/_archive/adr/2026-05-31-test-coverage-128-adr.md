---
tags:
  - '#adr'
  - '#test-coverage-128'
date: '2026-05-31'
modified: '2026-06-30'
related:
  - '[[2026-05-31-test-coverage-128-research]]'
---

# `test-coverage-128` adr: `PR-time integration job + subprocess purity tests` | (**status:** `accepted`)

## Problem Statement

Three holes from the end-of-Wave-2 audit (gh #128). Integration
tests don't gate PRs; tqdm suppression is asserted only by code
inspection; `--json` purity is one command deep. Each PR through
Wave 2 merged without integration verification, and a regression
that leaks `\r` into stdout would silently break script-friendly
consumers.

## Considerations

- Integration suite already exists as `gpu-integration.yml` on a
  self-hosted GPU runner. Adding a `pull_request:` trigger reuses
  the existing infrastructure.
- Fork PRs do not get `secrets.HF_TOKEN`. Acceptable: this repo is
  solo-maintained; document the constraint.
- tqdm purity at encode time requires GPU + a real index; belongs
  in integration. At import time it can be asserted from a
  GPU-less subprocess of `vaultspec-rag --help`.
- `--json` purity at success path requires no GPU for `status`,
  `server service status` (idle), and a no-op `index --dry-run`.
  `search` success needs an index; the existing test already
  covers `search` failure path.

## Constraints

- No mocks, no skips, no `@pytest.mark.skip` (per
  `[[feedback_no_adhoc_no_swallow]]` and the testing mandate).
- Subprocess tests use `sys.executable -m vaultspec_rag` so they
  run against the live installed entry point, not an import shim.
- Workflow changes pass `actionlint` (the existing Workflow Lint
  job).
- No new `except` clauses.

## Implementation

### `.github/workflows/gpu-integration.yml`

Add `pull_request:` to the `on:` block with the same path filter
as the existing `push:` trigger. Comment block explains the
secret-access constraint for fork PRs.

### `src/vaultspec_rag/tests/test_cli.py::TestTqdmSuppression`

Two tests:

- `test_suppress_hf_progress_sets_env_vars`: unit-tier; call
  `_suppress_hf_progress()` then assert the three env vars
  (`HF_HUB_DISABLE_PROGRESS_BARS`, `TRANSFORMERS_NO_ADVISORY_WARNINGS`,
  `TOKENIZERS_PARALLELISM`).
- `test_help_subprocess_stdout_has_no_cr`: subprocess
  `sys.executable -m vaultspec_rag --help`; assert exit 0, assert
  `b"\r"` not in stdout. Captures import-time tqdm leakage.

### `src/vaultspec_rag/tests/test_cli.py::TestJsonOutputMode`

New parametric test
`test_envelope_is_pure_json_across_commands`. Parametrise over:

- `("status", ["status", "--json"])`
- `("server-service-status", ["server", "service", "status", "--json"])`
- `("index-dry-run", ["index", "--type", "vault", "--dry-run", "--json"])`
- `("search-filter-mismatch", ["search", "x", "--type", "vault", "--include-path", "src/**", "--json"])` (already covered by the
  existing test but include for symmetry)

Each: subprocess; assert exit code matches expectation (some are
error envelopes, some success); assert `json.loads(stdout.strip())`
parses; assert no ANSI escape (`\x1b[`) or box-drawing characters
in stdout.

## Rationale

Subprocess over in-process Click runner because Rich respects
`sys.stdout.isatty()` and the runner captures via a non-tty
buffer that already strips most ANSI — defeating the purity
check. Real subprocess with a captured pipe is the correct
substrate.

## Consequences

- The existing GPU integration job now triggers on PRs. GPU
  runner cost per PR — acceptable for solo maintenance.
- Two new test classes (one extended), four new tests. Run in
  the standard unit suite (no GPU dependency).
- Fork PR contributors will see the integration job skip with a
  secret-access error. Documented in workflow.
- No new exception suppression; no shims; no test mandate
  violations.
