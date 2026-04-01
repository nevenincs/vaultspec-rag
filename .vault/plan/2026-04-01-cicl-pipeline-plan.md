---
tags:
  - "#plan"
  - "#cicl"
date: 2026-04-01
related:
  - "[[2026-04-01-cicl-pipeline-adr]]"
  - "[[2026-04-01-cicl-pipeline-research]]"
---

# `cicl` phase-1 plan

Set up a complete CI/CD pipeline for vaultspec-rag: CI checks on PRs,
automatic versioning via release-please, and PyPI publish pipeline with
trusted publishing. Mirrors vaultspec-core's proven patterns.

## Proposed Changes

Implement all 8 decisions from the accepted ADR. The work breaks into
3 phases: source preparation, workflow authoring, and release validation.

## Tasks

- Phase 1: Source preparation
  1. Fix vaultspec-core dependency in `pyproject.toml` — change from
     `file:///` path to `"vaultspec-core>=0.1.0"` in `[project.dependencies]`.
     Add `vaultspec-core = { path = "../vaultspec-core-worktrees/main",
     editable = true }` to `[tool.uv.sources]` (alongside existing torch
     entry). The static `version = "0.1.0"` stays — release-please bumps
     it in `pyproject.toml` directly. Verify `uv lock` succeeds.
  1. Add `__version__` to `src/vaultspec_rag/__init__.py` via
     `importlib.metadata.version("vaultspec-rag")` with `0.0.0.dev0`
     fallback. Add to `__all__`. This reads from installed package metadata
     which hatchling populates from the static version field.
  1. Create `release-please-config.json` — python release-type,
     package-name `vaultspec-rag`, `include-component-in-tag: true` (produces
     `vaultspec-rag-vX.Y.Z` tags), bump-minor-pre-major,
     bump-patch-for-minor-pre-major, same changelog sections as vaultspec-core.
  1. Create `.release-please-manifest.json` — initial version `"0.1.0"`.
  1. Remove `.github/workflows/.gitkeep` placeholder (if it exists).

- Phase 2: Workflow authoring (mirror vaultspec-core patterns precisely)
  1. Create `.github/workflows/ci.yml` — 4 jobs with shared setup pattern
     (actions/checkout@v4, actions/setup-python@v6 3.13,
     astral-sh/setup-uv@v7 with enable-cache). Top-level
     `permissions: contents: read`, env `NO_COLOR: "1"` / `FORCE_COLOR: "0"`.
     Concurrency `ci-${{ github.workflow }}-${{ github.ref }}` with
     cancel-in-progress: true. Jobs: workflow-lint (actionlint docker),
     lint-and-type (ruff check, ty check, taplo lint via direct `uv run`),
     tests (`uv run pytest -m unit --timeout=60`), dependency-audit
     (`uvx pip-audit` — ephemeral, no dev dep needed). Triggers: push to
     main, pull_request, workflow_dispatch.
  1. Create `.github/workflows/release-please.yml` — permissions:
     contents: write, pull-requests: write. Concurrency: release-please,
     cancel-in-progress: false. `googleapis/release-please-action@v4` with
     config-file and manifest-file refs. Conditional uv.lock regen:
     `if: steps.release.outputs.pr && !steps.release.outputs.release_created`,
     checkout release branch, `uv lock`, commit and push if changed.
  1. Create `.github/workflows/publish.yml` — concurrency: publish,
     cancel-in-progress: false. Triggered on release publication +
     workflow_dispatch with tag input. 3 stages: build (checkout tag via
     `${{ inputs.tag || github.event.release.tag_name }}`, `uv build`,
     upload-artifact with if-no-files-found: error, retention-days: 5),
     smoke-test (download artifact, run `tests/smoke_check.py` against
     wheel and sdist via `uv run --isolated --no-project --with`),
     publish-pypi (permissions: id-token: write, environment: pypi,
     `uv publish --check-url`).

- Phase 3: Smoke test and validation
  1. Create `tests/smoke_check.py` — non-pytest script (intentionally in
     `tests/` to match vaultspec-core convention; exempt from the
     "deprecated tests/ dir" rule since it's not a pytest suite). Functions:
     `check_import`, `check_version_metadata`, `check_entry_points_registered`
     (vaultspec-rag and vaultspec-search-mcp), `check_cli_help`
     (vaultspec-rag --help), `check_mcp_help` (vaultspec-search-mcp --help).
  1. Run pre-commit hooks on all modified files.
  1. Run `uv run pytest -m unit` locally to confirm no regressions.
  1. Commit all changes, push, merge to main.
  1. Monitor GitHub Actions: verify ci.yml and release-please.yml trigger.

## Parallelization

- Phase 1 steps 1-4 are independent and can execute in parallel.
- Phase 2 steps 1-3 are independent (separate workflow files).
- Phase 1 and Phase 2 can partially overlap — workflow files don't depend
  on source changes.
- Phase 3 is sequential (each step validates the previous).

## Verification

- All pre-commit hooks pass (ruff, taplo, ty, markdownlint).
- `uv run pytest -m unit` passes with 0 failures.
- `uv lock` succeeds with the new dependency spec.
- `uv build` produces a valid wheel and sdist locally.
- `python tests/smoke_check.py` passes locally against the built wheel.
- After merge to main: ci.yml triggers and runs all 4 jobs. Expected
  result: workflow-lint, lint-and-type pass. Tests job may fail due to
  vaultspec-core local path in uv.lock (acceptable failure condition).
  release-please.yml triggers and creates a release PR.
- Acceptable failure: any remote CI job that tries to install
  vaultspec-core will fail because the PyPI version may not have all
  needed features yet. The `[tool.uv.sources]` local override only
  applies to local `uv` operations.
