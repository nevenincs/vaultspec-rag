---
tags:
  - '#plan'
  - '#install-command'
date: 2026-04-12
related:
  - '[[2026-04-12-vaultspec-rag-install-adr]]'
  - '[[2026-04-12-vaultspec-rag-install-research]]'
  - '[[2026-04-12-vaultspec-rag-install-reference]]'
---

# `install-command` `feature` plan

Implement `vaultspec-rag install` and `vaultspec-rag uninstall` (issues
#54 and #55) as a thin, symmetric companion-package enrollment surface
that delegates all shared-repository state changes to vaultspec-core
via direct Python imports. The work spans two coordinated PRs: a
sister core PR that teaches core's sync to reconcile (prune orphans)
must land first, then the rag PR adds bundling, orchestration, CLI
wiring, and integration tests.

## Proposed Changes

The work follows the architectural decisions in the related ADR. Two
non-trivial constraints shape the plan:

- rag has a hard dependency on vaultspec-core. Both install and
  uninstall use core's public Python API directly (no subprocess, no
  fallback path).

- Install and uninstall are pure mirrors of each other: install adds
  rag's bundled builtin source files and calls core's `sync_provider`
  to propagate; uninstall removes the same source files and calls
  the same `sync_provider` to propagate the removal. This requires
  core's sync to be a reconciling operation, not purely additive.

The reference doc captures core's existing install pipeline and
public API surface. The ADR documents the layer-separation rules,
the dependency-direction rules (CLI → orchestration → core), the
bundling mechanism (hatch `force-include`), the CLI flag-name
alignment with core (verbatim), and the test mandate (no mocks,
real filesystem, real core).

The plan introduces no `install.py` module — orchestration lives
in a new `src/vaultspec_rag/commands.py` mirroring core's role for
`core/commands.py`. CLI wiring stays in the existing `src/vaultspec_rag/cli.py`
and consists of two thin Typer wrappers that delegate immediately.
A future repo-level refactor toward a layered `cli/` + `core/`
subpackage shape is filed as a separate follow-up issue and is
explicitly out of scope here.

## Tasks

The plan is split into six phases. Phases 2–6 cannot start until
Phase 1 lands and rag's dependency pin is bumped to the new core
release. Within each phase, steps are intended to be sequential
unless flagged otherwise in the Parallelization section.

- `Phase 1` — vaultspec-core sister PR: reconciling sync

  1. Create a new core worktree branch off `main`. Read the existing
     core sync surfaces in `core/mcps.py`, `core/rules.py`,
     `core/agents.py`, `core/skills.py`, and `core/sync.py` to
     determine the minimum-viable scope of the reconciling change.
  1. Write a core-side ADR capturing the reconciling-sync decision,
     the ownership-tracking strategy (manifest field vs reserved
     `_managed` key vs source-existence-at-last-sync), and the
     rollout impact on existing core users.
  1. Investigate whether the orphan-pruning gap exists in
     `rules_sync`, `agents_sync`, `skills_sync`, and `mcp_sync`
     symmetrically. Decide whether the fix lands in one place
     (the shared sync engine in `core/sync.py`) or per-resource.
  1. Implement the reconciling sync with the ownership-tracking
     strategy chosen in step 2. Preserve user-added entries by
     construction (the design must make it impossible to prune
     entries that were never managed by core).
  1. Add tests against real filesystem fixtures: install→uninstall
     leaves zero orphans; user-added entries survive a sync after a
     companion uninstall; dry-run preview lists pruned items;
     pre-existing core users see no behavior change for the
     additive path.
  1. Update core's manifest schema if needed to track managed
     entries.
  1. Bump `vaultspec-core` version to 0.1.10 in core's `pyproject.toml`.
  1. Run pre-commit hooks, ruff, pyright, and the full core test
     suite. Fix all failures at the root cause (no skips, no
     bypasses).
  1. Commit and push the core branch. Open a PR titled
     `feat: reconciling sync — prune orphans on companion uninstall`.
     Reference the rag-side issues #54/#55 and this plan.
  1. Wait for the core PR to merge. Once merged, ensure
     `vaultspec-core==0.1.10` is published or installable from
     the relevant source so the rag PR can pin it.

- `Phase 2` — rag bundling foundation

  1. Bump `vaultspec-core>=0.1.10` in rag's `pyproject.toml`
     `[project] dependencies` block.
  1. Add a `[tool.hatch.build.targets.wheel.force-include]` mapping
     of `.vaultspec/rules` to `vaultspec_rag/builtins` in rag's
     `pyproject.toml`. Mirrors core's bundling pattern verbatim.
  1. Verify the bundled tree by building a wheel locally (`uv build`)
     and confirming `vaultspec_rag/builtins/rules/rules/vaultspec-rag.builtin.md`
     and `vaultspec_rag/builtins/rules/mcps/vaultspec-rag.builtin.json`
     are present inside the wheel.
  1. Run `uv sync` to refresh the lockfile against the new core pin.
     Confirm the lockfile updates cleanly with no other unexpected
     drift.

- `Phase 3` — `vaultspec_rag.builtins` module

  1. Create `src/vaultspec_rag/builtins/__init__.py` exposing
     `seed_builtins(target_rules_dir, *, force=False) -> list[str]`
     and `list_builtins() -> list[str]`. Mirror core's
     `vaultspec_core/builtins/__init__.py` exactly.
  1. Use `importlib.resources.files("vaultspec_rag.builtins")` for
     resource enumeration; use `vaultspec_core.core.helpers.atomic_write`
     for the actual file writes — no hand-rolled helper.
  1. Add unit tests at `src/vaultspec_rag/tests/test_builtins_unit.py`
     covering: enumeration returns the expected two relative paths;
     seeding into an empty target writes both files; seeding when
     destinations already exist is a no-op without `force`; with
     `force` overwrites; atomic-write semantics survive a torn-write
     scenario (simulate via interruption-safe assertion of either
     fully-written or absent).

- `Phase 4` — `vaultspec_rag.commands` module

  1. Create `src/vaultspec_rag/commands.py`. Public surface:
     `install_run(path, *, upgrade=False, dry_run=False, force=False, skip=None) -> dict`
     and `uninstall_run(path, *, remove_data=False, dry_run=False, force=False, skip=None) -> dict`.
     Mirror core's `core/commands.py` role.
  1. Imports from core: `vaultspec_core.config.workspace.resolve_workspace`,
     `vaultspec_core.core.commands.sync_provider`,
     `vaultspec_core.core.helpers.atomic_write`, and the typed
     exception classes from `vaultspec_core.core.exceptions`. No
     try/except-ImportError fallback.
  1. `install_run` step order: resolve workspace; idempotent
     `mkdir -p` for `.vault/`, `.vault/data/`, `.vaultspec/`,
     `.vaultspec/rules/`, `.vaultspec/rules/rules/`,
     `.vaultspec/rules/mcps/`; `seed_builtins(force=force or upgrade)`;
     `sync_provider("all", dry_run=dry_run, force=force, skip=skip or set())`;
     return result dict shaped like core's `install_run` return value.
  1. `uninstall_run` step order: refuse without `force=True` (return
     dry-run preview); `unlink(missing_ok=True)` rag's two builtin
     source files; `sync_provider("all", dry_run=dry_run, force=force, skip=skip or set())`;
     if `remove_data`, `rmtree` `.vault/data/`; return result dict
     shaped like core's `uninstall_run` return value.
  1. Both functions raise core's `VaultSpecError` subclasses on
     failure — no new exception types.
  1. Add module-level docstring noting the layer role (orchestration,
     not CLI; importable independently of Typer).

- `Phase 5` — CLI wiring in `cli.py`

  1. Modify `src/vaultspec_rag/cli.py` to add two new Typer commands
     registered against the existing root `app`: `cmd_install` and
     `cmd_uninstall`. Both are thin wrappers that parse args, call
     `commands.install_run` / `commands.uninstall_run`, render the
     result, and exit with appropriate codes on `VaultSpecError`.
  1. Flag definitions match core's `cli/root.py:cmd_install` and
     `cmd_uninstall` exactly. For install: `--target/-t`, `--upgrade`,
     `--dry-run`, `--force`, `--skip` (repeatable), `--json`. For
     uninstall: `--target/-t`, `--remove-data`, `--dry-run`, `--force`,
     `--skip`, `--json`. Help text mirrors core's wording where the
     meaning is shared.
  1. The `provider` positional argument core takes is omitted because
     rag has no provider concept. Document this divergence in the
     command docstring.
  1. Reuse the existing Rich console singleton already present in
     `cli.py` for rendering. JSON output goes to stdout via
     `json.dumps(result, default=str)` to match core's `--json`
     convention.
  1. Add CLI unit tests at `src/vaultspec_rag/tests/test_cli_install.py`
     using Typer's `CliRunner` against the real `commands.py`
     (no mocks). Cover: `vaultspec-rag install --help` returns the
     expected flag list; `vaultspec-rag uninstall --help` returns
     the expected flag list; `--dry-run` does not invoke writes;
     `uninstall` without `--force` exits zero with a preview.

- `Phase 6` — End-to-end integration tests

  1. Create `src/vaultspec_rag/tests/integration/test_install.py`
     using real filesystem via `tmp_path` and the real `vaultspec_core`
     installed in the dev environment. No mocks per project mandate.
  1. Test cases (each gets its own function):
     - Fresh install in an empty workspace creates the expected
       directories, seeds both builtin files, and (after
       `sync_provider`) registers `vaultspec-search-mcp` in
       `.mcp.json` and propagates `vaultspec-rag.builtin.md` to
       at least one provider directory.
     - Idempotent re-install on an already-installed workspace is
       a no-op except for the report.
     - `--upgrade` re-seeds when files exist.
     - `--force` re-seeds when files exist (parallel semantics to
       core).
     - `--dry-run` install: workspace is unchanged.
     - Uninstall without `--force`: workspace unchanged, dry-run
       preview returned.
     - Uninstall with `--force`: rag's two builtin source files are
       removed, the propagated copies in provider dirs are pruned
       (depends on Phase 1), the `vaultspec-search-mcp` entry is
       gone from `.mcp.json` (depends on Phase 1), `.vault/` and
       `.vault/data/` are preserved.
     - Uninstall with `--force --remove-data`: `.vault/data/` is
       also removed.
     - Pre-existing user `.mcp.json` entry (e.g. `my-custom-server`)
       survives both install and uninstall flows.
     - Pre-existing user content under `.vaultspec/rules/rules/`
       survives both flows.
     - `--json` output for both commands parses as valid JSON and
       contains the expected top-level keys (`action`, `items`,
       `path`).
     - Symmetric round-trip: install then uninstall returns the
       workspace to a state byte-equivalent (modulo `.vault/data/`)
       to its pre-install state.

- `Phase 7` — Verification, commit, PR

  1. Run pre-commit hooks on all modified files. Fix all failures at
     the root cause.
  1. Run ruff and pyright clean.
  1. Run the full rag test suite (`uv run vaultspec-rag test` or
     equivalent) and confirm 100% pass with no skips.
  1. Update `MEMORY.md` and any session memory entries with the
     new public surface (`commands.install_run`,
     `commands.uninstall_run`, `builtins.seed_builtins`,
     `builtins.list_builtins`).
  1. Stage and commit. Commit message focused on the why
     (companion-package enrollment, symmetric mirror of core,
     direct delegation) not the what.
  1. Push the branch.
  1. Open the PR: title `feat: vaultspec-rag install/uninstall — companion enrollment via core sync`. Body closes #54 and #55,
     references the core sister PR, sets milestone
     "Alpha: Core Compatibility".
  1. Mark phase tasks complete in this plan file as the work
     progresses.

## Parallelization

Phase 1 is strictly serial — the core PR must land and be installable
before any rag-side work that touches the new pin.

Within Phase 1, steps 1–3 (investigation) can be parallelized across
sub-agents by file/module: one agent reads `mcps.py`, one reads the
shared `sync.py`, one reads the rules/agents/skills sync surfaces.
Steps 4–6 (implementation) are sequential.

Within the rag side (Phases 2–6):

- Phases 2 (bundling) and 3 (builtins module) can run in parallel
  because they touch independent files. Phase 4 (commands.py) depends
  on both.
- Phase 4 (commands.py) and Phase 5 (CLI wiring) are sequential
  because cli.py imports from commands.py.
- Phase 6 (integration tests) cannot start until Phase 5 is complete.
- Phase 7 is strictly final.

A practical execution shape: Phase 1 in one focused effort, then
Phases 2+3 in parallel sub-agents, then Phase 4, then Phase 5, then
Phase 6 in one focused integration-test session, then Phase 7.

## Verification

Mission success has three layers:

**Functional correctness.** The integration tests in Phase 6
exercise every documented behavior end-to-end against a real
vaultspec-core, real filesystem, and real bundled wheel. The
symmetric round-trip test (install → uninstall → state matches
pre-install) is the strongest single signal that both flows are
correct and that core's reconciling sync (Phase 1) is working as
designed. If that test fails, either Phase 1 is wrong or rag's
flow is wrong — both are diagnosable from the test output.

**Architectural alignment.** Verify by manual review that:

- No file named `install.py` exists in the rag tree.
- `commands.py` imports only from `vaultspec_core.*` and
  `vaultspec_rag.builtins`, never from `vaultspec_rag.cli`.
- `cli.py` additions are thin wrappers — under ~80 lines for both
  commands combined — and contain no orchestration logic.
- Flag names in rag's `cmd_install` / `cmd_uninstall` match core's
  verbatim. Diff against core's `cli/root.py` declarations.
- rag never reads or writes `.gitignore`, `.gitattributes`,
  `.mcp.json`, manifest, or provider directories directly. Grep
  the new modules to confirm.

**Linting and typing.** Zero ruff violations, zero pyright errors,
all pre-commit hooks pass. No skips, no `# type: ignore`, no
`# noqa` introduced. If a check fails, fix the underlying issue.

**Honesty about limits.** Tests cannot prove that the modular
ecosystem story scales to multiple companion packages — only that
rag's single companion enrollment works. The discovery API,
`.gitignore` companion entries, `.gitattributes` companion entries,
and manifest companion tracking are all tracked in the ADR's
"Required Core Support" section as follow-ups; this plan does not
verify them. If the user later adds a second companion package and
discovers an interaction bug, that is a new feature, not a
regression of this work.

The pre-commit hook is canonical authority for what must pass
before commit. If a test passes locally but the hook flags
something, the hook is right and the test setup is incomplete.
