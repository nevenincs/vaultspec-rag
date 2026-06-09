---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
step_id: 'S15'
related:
  - '[[2026-06-09-operability-hardening-plan]]'
---

# operator-persona testimonial end-to-end CLI integration tests

## Scope

- `src/vaultspec_rag/tests/integration/test_cli_ux_testimonial.py` (new file)

## Description

Created `test_cli_ux_testimonial.py` with three operator-persona test
classes. Each class runs a scripted real CLI sequence and records
structured `_Observation` dataclasses (command, exit_code, output,
friction), then asserts correct behaviour at the end. No mocks,
monkeypatches, patches, or skips.

**Persona 1 — `TestFirstTimeIndexer`:**

A single `test_persona` method exercises three workspace-free commands
via `typer.testing.CliRunner`:

- `--help` — exit 0; top-level command list contains `index`, `search`,
  `status`, `server`.
- `index --help` — exit 0; `docs/indexing.md` cross-reference present;
  no forbidden tokens (`Args:`, `Raises:`, `CLIState`, `ctx`).
- `status` — exit 0; output contains CUDA/GPU information.

**Persona 2 — `TestSearchPowerUser`:**

Two tests:

- `test_search_help` (no GPU, `integration` marker) — invokes
  `search --help` via `CliRunner`; asserts exit 0, no forbidden tokens,
  and that both `Code filters` and `Vault filters` rich help panels are
  present.
- `test_live_code_search` (`subprocess_gpu` marker) — builds a minimal
  synthetic vault with a Python stub, indexes via subprocess
  (`index --type code`), then runs `search "embedding model" --type code --language python`; asserts exit 0 and that ranked output is returned.

**Persona 3 — `TestServiceOperator`:**

Eight tests; the first six use `CliRunner` with an isolated
`_service_env(tmp_path)` context (no GPU, no live daemon), the last one
uses the `live_service` fixture:

- `test_server_service_is_invalid` — `server service --help` exits 2 and
  contains `"No such command"`, confirming the old nested path is gone.
- `test_server_status_no_service` — `server status` exits 3 with
  `"stopped"` or `"missing"` in output.
- `test_server_logs_no_service` — `server logs` exits 3 with non-empty
  output (remediation hint).
- `test_server_jobs_no_service` — `server jobs` exits 3 with non-empty
  output.
- `test_server_watcher_status_no_service` — `server watcher status` exits
  3\.
- `test_server_projects_list_no_service` — `server projects list` exits 3.
- `test_server_lifecycle_and_observability` (`subprocess_gpu`) — uses the
  `live_service` fixture to spin up a real GPU-backed daemon; exercises
  `server status`, `server logs`, `server jobs`, `server watcher status`,
  `server projects list` via `CliRunner`; asserts all exit 0, that
  `"running"` and the port number appear in `server status` output, and
  that every other command returns non-empty output.

## Outcome

- `ruff check` clean (0 violations).
- `ty check` clean (0 errors).
- `pytest --collect-only` collects 10 tests without error.
- Non-GPU subset (`-m "not subprocess_gpu"`): 8/8 pass in 5 s.
- `subprocess_gpu` tests (`test_live_code_search`,
  `test_server_lifecycle_and_observability`) deferred to W04 full-run
  validation.
