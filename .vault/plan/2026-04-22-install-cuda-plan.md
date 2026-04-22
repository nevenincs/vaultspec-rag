---
tags:
  - "#plan"
  - "#install-cuda"
date: 2026-04-22
related:
  - "[[2026-04-22-install-cuda-adr]]"
  - "[[2026-04-22-install-cuda-research]]"
  - "[[2026-04-12-vaultspec-rag-install-adr]]"
---

# install-cuda plan: executable implementation steps

## summary

Implements [[2026-04-22-install-cuda-adr]]. Scope:

- New module `src/vaultspec_rag/torch_config.py`.
- Extend `install_run` / `uninstall_run` in `commands.py`.
- New flags on `cmd_install` / `cmd_uninstall` in `cli.py`.
- Refactor `_handle_gpu_error` to 3-state taxonomy; migrate the
  bare check at `cli.py:1652`.
- Add `tomlkit>=0.13` to `pyproject.toml` dependencies.
- Update README install section.
- Unit tests and integration tests per ADR.

Target branch: `feature/install-cuda` (current).

## prerequisites

- Working tree clean (verified at plan time: `git status` clean).
- Tests currently pass: run
  `uv run pytest src/vaultspec_rag/tests/unit -x` before the first
  commit to establish baseline.
- User approval on this plan before step 1 begins.

## step 1 — add tomlkit runtime dependency

**file:** `pyproject.toml`

Insert `"tomlkit>=0.13",` into `[project] dependencies` (line 17-34),
alphabetically between `sentence-transformers` and `torch` or at
the obvious insert point matching existing style (append to the
list — current order is not strictly alphabetical).

Run `uv lock` to refresh the lockfile.

**exit criteria:**
- `uv run python -c "import tomlkit; print(tomlkit.__version__)"`
  prints a version string ≥0.13.
- `uv.lock` updated, no other dep deltas.

**step record:** `.vault/exec/2026-04-22-install-cuda/2026-04-22-install-cuda-phase1-task1.md`

## step 2 — create torch_config.py

**file:** `src/vaultspec_rag/torch_config.py` (NEW)

Implement per the ADR surface:

- Module-level constants `CU130_INDEX_NAME`, `CU130_INDEX_URL`,
  `CU130_MARKER` (all `Final`).
- `TorchConfigState(StrEnum)`: `MISSING`, `CANONICAL`,
  `CUSTOMISED`, `NO_PROJECT_FILE`.
- `TorchDiagnosis(StrEnum)`: `NO_TORCH`, `CPU_ONLY`, `NO_GPU`,
  `WORKING`.
- `PatchReport` dataclass with `action: str`, `conflicts: list[str]`,
  `path: Path`.
- `detect_state(pyproject: Path) -> TorchConfigState`: parses with
  `tomlkit.parse`, inspects `tool.uv.index` (list) for a
  `pytorch-cu130` entry and `tool.uv.sources.torch` for a matching
  source; returns the appropriate state. Must handle missing tables
  gracefully (no `KeyError`).
- `apply_patch(pyproject: Path) -> PatchReport`: uses tomlkit to
  add missing pieces in place (preserving style); writes via
  `vaultspec_core.core.helpers.atomic_write`. Idempotent when state
  is CANONICAL. Refuses (no write) when CUSTOMISED or
  NO_PROJECT_FILE.
- `remove_patch(pyproject: Path) -> PatchReport`: inverse of
  apply. Drops the source entry; if the resulting list is empty,
  drops the key. Drops the index table; if the resulting list is
  empty, drops the table. Preserves everything else.
- `diagnose_torch(cuda: str | None, available: bool) -> TorchDiagnosis`:
  pure function matching the table in the research doc.
- `preview_patch(pyproject: Path) -> str`: returns the TOML we'd
  add (or empty string if state is CANONICAL).
- `manual_snippet() -> str`: returns the canonical block as a
  string literal assembled from the three constants.

Implementation tips (not verbatim code):
- Use `tomlkit.aot()` (array-of-tables) when adding `[[tool.uv.index]]`
  to a doc that has no `[tool.uv]` table yet.
- Use `tomlkit.array()` + `tomlkit.inline_table()` for the
  `torch = [{ index = ..., marker = ... }]` source (list of inline
  tables matches rag's own pyproject shape).
- Comparison for the "canonical" predicate uses the three module
  constants only. No string reformatting sensitivity.

**exit criteria:**
- File exists. `uv run ruff check src/vaultspec_rag/torch_config.py`
  passes with 0 violations.
- `uv run python -c "from vaultspec_rag.torch_config import
  detect_state, apply_patch, remove_patch, diagnose_torch,
  manual_snippet, TorchConfigState, TorchDiagnosis, PatchReport"`
  succeeds.

**step record:** `.vault/exec/2026-04-22-install-cuda/2026-04-22-install-cuda-phase1-task2.md`

## step 3 — unit tests for torch_config

**file:** `src/vaultspec_rag/tests/unit/test_torch_config.py` (NEW)

Tests listed in the ADR (`### testing` section). No mocks,
no monkeypatching. Each fixture is a real `tmp_path / "pyproject.toml"`
written with a known byte content, loaded by real `tomlkit`.

Assertions to cover:
- `detect_state` classifies each of the 5 fixtures correctly.
- `apply_patch` on MISSING writes exactly the canonical block,
  preserves the rest of the file, and a second call returns
  `action="skipped"` without modifying mtime.
- `apply_patch` on CUSTOMISED returns `action="conflict"` with a
  non-empty `conflicts` list; file bytes unchanged.
- `remove_patch` after `apply_patch` restores the original file
  SHA-256 exactly.
- `remove_patch` on CUSTOMISED leaves it alone and reports
  `action="skipped"` with a warning in conflicts.
- `diagnose_torch` for each of the 4 input combinations.
- `manual_snippet()` output parses as valid TOML and matches the
  apply output for a blank input.

**exit criteria:**
- `uv run pytest src/vaultspec_rag/tests/unit/test_torch_config.py -v`
  passes, minimum 12 test cases.
- 0 ruff / ty violations on the new test file.

**step record:** `.vault/exec/2026-04-22-install-cuda/2026-04-22-install-cuda-phase1-task3.md`

## step 4 — extend commands.py

**file:** `src/vaultspec_rag/commands.py`

- Add import: `from . import torch_config`.
- Extend `InstallReport` with `torch_config_action: str = "skipped"`
  and `torch_config_conflicts: list[str] = field(default_factory=list)`.
  Extend `to_dict()`.
- Extend `UninstallReport` with `torch_config_removed: bool = False`.
  Extend `to_dict()`.
- Change `install_run` signature to add `configure_torch: bool =
  True`, `assume_yes: bool = False`, `sync_after: bool = False`
  (all keyword-only).
- Change `uninstall_run` signature to add `assume_yes: bool = False`.
- Implement the install-side torch_config flow per ADR: after the
  `sync_provider` block, run the detect → (prompt / skip / apply)
  → optional `uv sync` pipeline. Record outcomes on the report.
  The confirmation prompt uses `rich.prompt.Confirm.ask` (rich is
  already a dep).  Non-TTY detection via `sys.stdin.isatty()`:
  when False and `assume_yes` is False, set
  `torch_config_action="skipped-non-tty"` and emit a warning that
  names the `--yes` / `--no-torch-config` flags.
- Implement the uninstall-side removal: always call
  `remove_patch`; record the outcome on the report (silent when
  state is MISSING). No prompt on uninstall (the user has already
  consented by running `uninstall`).
- `dry_run=True` on install: call `preview_patch` and record the
  intended action without writing.
- `dry_run=True` on uninstall: call `detect_state`; report what
  would be removed without calling `remove_patch`.
- The `sync_after` step uses `subprocess.run(["uv", "sync",
  "--reinstall-package", "torch"], cwd=target, check=False)`.
  Non-zero exit → warning on report, not an exception.

**exit criteria:**
- `uv run pytest src/vaultspec_rag/tests/integration/test_install.py`
  (existing) still passes — backward compat with the prior
  install feature.
- Both new params default-off at the function level do not change
  the prior report shape except additively.

**step record:** `.vault/exec/2026-04-22-install-cuda/2026-04-22-install-cuda-phase1-task4.md`

## step 5 — update cli.py Typer wrappers

**file:** `src/vaultspec_rag/cli.py`

In `cmd_install`:
- Add three new `Annotated[...]` parameters:
  `configure_torch` (bool, `--torch-config/--no-torch-config`,
  default True), `yes` (bool, `--yes`/`-y`, default False),
  `sync_after` (bool, `--sync`, default False).
- Pass through to `install_run(..., configure_torch=configure_torch,
  assume_yes=yes, sync_after=sync_after)`.

In `cmd_uninstall`:
- Add `yes` parameter (`--yes`/`-y`, default False).
- Pass through to `uninstall_run(..., assume_yes=yes)`.

Render the new report fields in the post-run summary (both JSON
and Rich panels) so the user sees the torch-config action.

**exit criteria:**
- `uv run vaultspec-rag install --help` shows the three new flags.
- `uv run vaultspec-rag uninstall --help` shows the one new flag.
- `uv run pytest src/vaultspec_rag/tests/unit/test_cli.py` still
  passes (if such file exists; otherwise the Typer handler smoke-test
  is covered by integration tests).

**step record:** `.vault/exec/2026-04-22-install-cuda/2026-04-22-install-cuda-phase1-task5.md`

## step 6 — refactor _handle_gpu_error and migrate cli.py:1652

**file:** `src/vaultspec_rag/cli.py`

Replace the body of `_handle_gpu_error` (lines 58-80) with the
3-state dispatch per the ADR. Lazy-import torch inside the helper
so ImportError remains the fast path.

Migrate the bare check at `cli.py:1652` in `service_warmup` to:

```python
if not torch.cuda.is_available():
    _handle_gpu_error(RuntimeError("CUDA runtime unavailable"))
```

so both sites share the taxonomy.

**exit criteria:**
- A unit test in `tests/unit/test_torch_config.py::test_diagnose_torch`
  covers all 4 states (from step 3).
- A manual smoke test (in the step record) confirms the 3 messages
  render as expected — constructed by raising the appropriate
  exception in a fixture that stubs torch.version.cuda via the
  `cuda`/`available` args of `diagnose_torch` (no monkeypatching of
  the real torch module).

**step record:** `.vault/exec/2026-04-22-install-cuda/2026-04-22-install-cuda-phase1-task6.md`

## step 7 — integration tests

**file:** `src/vaultspec_rag/tests/integration/test_install_torch_config.py`
(NEW)

Tests per ADR `### testing` section, integration scope:

- Fresh install + `assume_yes=True` writes the cu130 block.
- Install then uninstall round-trip returns pyproject to
  byte-equal original (SHA-256 compare).
- `configure_torch=False` path: no pyproject mutation.
- Missing pyproject at target: warning, no crash.
- Pre-existing canonical block: action="already", no write.
- Pre-existing customised block: action="conflict", file unchanged.
- JSON output contains the new `torch_config_action` field.

Exclude the `--sync` path from automated tests (requires
live `uv` + network); document it in the step record as a manual
verification step.

**exit criteria:**
- `uv run pytest src/vaultspec_rag/tests/integration/test_install_torch_config.py -v`
  passes. Minimum 6 test cases.

**step record:** `.vault/exec/2026-04-22-install-cuda/2026-04-22-install-cuda-phase1-task7.md`

## step 8 — README updates

**files:** `README.md`, `src/vaultspec_rag/README.md`

- Root `README.md`, Install section: lead with `uv add vaultspec-rag
  && uv run vaultspec-rag install`. Add a callout naming `--sync`
  for one-liner install and `--no-torch-config` for opt-out.
  Add a short "Troubleshooting: CPU torch" note that reproduces
  the 3-state error taxonomy.
- `src/vaultspec_rag/README.md`: cross-reference from the install
  docs to the torch-config flag surface.
- Retain the manual cu130 snippet for air-gapped users.

**exit criteria:**
- Markdown lints (`mdformat`, `pymarkdownlnt`) pass via the
  existing pre-commit hook.

**step record:** `.vault/exec/2026-04-22-install-cuda/2026-04-22-install-cuda-phase1-task8.md`

## step 9 — full test + lint sweep, commit, push

Run the full matrix:

```
uv run ruff check .
uv run ruff format --check .
uv run ty check src/vaultspec_rag
uv run pytest src/vaultspec_rag/tests/unit -v
uv run pytest src/vaultspec_rag/tests/integration -v
```

Any failures roll back to the failing step's commit and are
fixed in place.

Commit cadence: one commit per logical step where practical, with
`prek` / pre-commit hooks passing each time. Commit messages focus
on the "why" per the project's `CLAUDE.md` convention. Final push
to `origin feature/install-cuda`.

**exit criteria:**
- All lints + all unit + integration tests green.
- `git push origin feature/install-cuda` succeeds.
- PR body draft ready (targeting `main`, referencing issue #81).

**step record + phase summary:**
`.vault/exec/2026-04-22-install-cuda/2026-04-22-install-cuda-phase1-task9.md`
and
`.vault/exec/2026-04-22-install-cuda/2026-04-22-install-cuda-phase1-summary.md`

## step 10 — code review artefact

**skill:** `vaultspec-code-review` (conceptual — produced as an
audit doc since the skill is not wired as a slash command in this
harness).

**file:** `.vault/exec/2026-04-22-install-cuda/2026-04-22-install-cuda-code-review.md`

Structured review covering: (a) adherence to prior install ADR,
(b) companion-delegation compliance (we do edit user's pyproject,
not core's files), (c) test mandate compliance (no mocks / skips),
(d) 3-state diagnosis completeness, (e) uninstall symmetry, (f)
idempotency of `apply_patch`, (g) confidence that README changes
match the new flag surface exactly.

**exit criteria:**
- Review doc signs off with a green status, or lists blockers to
  address before PR merges.

## rollback / abort points

- After step 1: if `tomlkit` bump breaks something, `git reset`
  the pyproject edit and revert to prior behaviour.
- After step 2-3: if `torch_config.py` design proves infeasible,
  ADR and this plan revisited.
- After step 4-5: if the new report fields break existing
  integration tests, roll forward with a migration commit (do
  not revert).
- After step 6: bare print-and-exit can be restored in one file.
- After step 9: if CI fails on push, fix on-branch; do not
  force-push.

## risks and mitigations

| risk                                          | likelihood | impact | mitigation                                                                                    |
| :-------------------------------------------- | :--------- | :----- | :-------------------------------------------------------------------------------------------- |
| tomlkit round-trip drops non-ASCII chars      | low        | med    | integration test asserts SHA-256 equality after install/uninstall round-trip                  |
| `apply_patch` destroys user formatting        | med        | high   | unit test asserts user comments + ordering preserved; tomlkit is explicitly designed for this |
| `uv sync --reinstall-package torch` fails     | med        | low    | `--sync` is opt-in; failure becomes a warning, not a blocker                                  |
| Non-TTY UX surprise (CI hangs)                | low        | high   | refuse to prompt when stdin is not a TTY; require explicit flag                               |
| Installing breaks rag's own dev environment   | low        | high   | smoke test: run `install` against rag's own pyproject and verify idempotency (already canonical) |
| `diagnose_torch` classification wrong         | low        | high   | 4 explicit unit test cases pinning each input combination                                     |

## approval

**Awaiting user approval before proceeding to step 1.**

Per the project's execution convention
([[2026-04-12-vaultspec-rag-install-adr]] and CLAUDE.md mandate
"The user must approve plans before execution proceeds"), no code
changes land until this plan is approved.
