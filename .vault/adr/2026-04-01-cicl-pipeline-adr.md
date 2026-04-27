---
tags:
  - '#adr'
  - '#cicl'
date: 2026-04-01
related:
  - '[[2026-04-01-cicl-pipeline-research]]'
---

# `cicl` adr: ci/cd pipeline and release automation | (**status:** `accepted`)

## Problem Statement

vaultspec-rag has no CI checks, no automatic versioning, and no release
pipeline. Merges to main are unguarded, version bumps are manual, and
there is no path to PyPI publication. The local `file:///` dependency on
vaultspec-core blocks both CI and publishing.

## Considerations

- vaultspec-core already has a proven 5-workflow CI/CD — reuse its patterns
  for ecosystem consistency
- vaultspec-rag is GPU-only — standard GitHub Actions runners lack CUDA,
  so only `@pytest.mark.unit` tests can run in CI
- The project uses hatchling as build backend and uv as package manager
- Pre-commit hooks already cover ruff, taplo, ty, markdownlint — CI should
  mirror these checks
- PyPI trusted publishing (OIDC) eliminates API token management

## Constraints

- No CUDA GPUs on GitHub Actions ubuntu-latest runners
- PyPI rejects packages with `file:///` path dependencies
- Smoke tests cannot exercise GPU inference — limited to package structure
  validation
- First PyPI publish requires a pending publisher configured on pypi.org

## Implementation

8 decisions across 3 workflow files + config + source changes:

- `ci.yml` — 4 jobs triggered on push to main + PRs:
  workflow-lint (actionlint), lint-and-type (ruff, ty, taplo via direct
  `uv run` commands), tests (`uv run pytest -m unit`), dependency-audit
  (uv audit). Concurrency groups cancel in-progress runs.

- `release-please.yml` — `googleapis/release-please-action@v4` on
  main pushes. Python release-type, conventional commits drive version
  bumps (`feat:` → minor, `fix:`/`perf:` → patch). Auto-regenerates
  `uv.lock` on release branches.

- `publish.yml` — Triggered on GitHub release publication. 3 stages:
  build (`uv build`) → smoke-test → publish-pypi (trusted publishing
  via OIDC `id-token`, `uv publish`).

- `release-please-config.json` + `.release-please-manifest.json` —
  Package name `vaultspec-rag`, initial version `0.1.0`, same changelog
  sections as vaultspec-core.

- Tag format — `vaultspec-rag-vX.Y.Z` matching vaultspec-core convention.

- vaultspec-core dependency — Change `pyproject.toml` from `file:///`
  to `"vaultspec-core>=0.1.0"`. Add `[tool.uv.sources]` override for
  local development. uv strips sources from wheel metadata automatically.

- `__version__` — Add `importlib.metadata.version("vaultspec-rag")`
  to `src/vaultspec_rag/__init__.py` with `0.0.0.dev0` fallback.

- `tests/smoke_check.py` — Non-pytest script: checks import, version
  metadata, entry points registered, `vaultspec-rag --help`,
  `vaultspec-search-mcp --help`.

## Rationale

- Mirrors vaultspec-core for ecosystem consistency — same tools, same
  patterns, same reviewer expectations
- Direct `uv run` commands in CI (no justfile) keeps workflows
  self-contained with fewer dependencies
- Unit-only CI testing is the standard approach for GPU-dependent packages;
  integration tests remain local/self-hosted
- uv source overrides are the official pattern for local dev + published deps
- Trusted publishing is the PyPI-recommended approach, eliminating token
  rotation burden

## Consequences

- Manual PyPI setup required: pending publisher must be configured on
  pypi.org before first release
- GitHub environment `pypi` must be created in repo settings
- All future commits to main should follow conventional commit format for
  release-please to work correctly
- Integration/quality/performance tests remain unguarded in CI — a
  self-hosted GPU runner could be added later
- The vaultspec-core PyPI version must stay compatible with what
  vaultspec-rag needs (currently >=0.1.0)
