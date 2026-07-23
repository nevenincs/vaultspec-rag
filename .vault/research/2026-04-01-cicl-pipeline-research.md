---
tags:
  - '#research'
  - '#cicl'
date: 2026-04-01
modified: '2026-07-23'
---

# `cicl` research: CI/CD pipeline and release automation

Research into setting up a complete CI/CD pipeline for vaultspec-rag,
mirroring the vaultspec-core reference implementation. Covers CI checks,
automatic versioning via release-please, and PyPI publish pipeline with
trusted publishing.

## Findings

### Reference implementation (vaultspec-core)

The vaultspec-core project has a mature 5-workflow CI/CD:

- **ci.yml** — 5 parallel jobs on every push to main and PRs: workflow-lint
  (actionlint), lint-and-type (ruff, ty, taplo, lychee, pymarkdown), tests
  (pytest -m unit), vault-audit, dependency-audit (uv audit). Uses
  concurrency groups to cancel in-progress runs.

- **release-please.yml** — Runs on main pushes. Uses
  `googleapis/release-please-action@v4` with `release-please-config.json` and
  `.release-please-manifest.json`. Generates release PRs from conventional
  commits, auto-regenerates `uv.lock` on release branches.

- **publish.yml** — Triggered on GitHub release publication or manual dispatch.
  Three-stage pipeline: build (`uv build`), smoke-test (import + CLI + MCP
  checks), publish-pypi (trusted publishing via OIDC `id-token`).

- **bootstrap-branch.yml** and **add-to-project.yml** — Already present in
  vaultspec-rag, no changes needed.

### Current vaultspec-rag state

- **Already has:** `add-to-project.yml`, `bootstrap-branch.yml`
- **Missing:** `ci.yml`, `release-please.yml`, `publish.yml`,
  `release-please-config.json`, `.release-please-manifest.json`
- **No `__version__`** in `__init__.py` — needs `importlib.metadata` pattern
- **Version:** `0.1.0` (static in `pyproject.toml`, hatchling build)
- **Pre-commit hooks:** ruff, taplo, ty, markdownlint (mirrors CI checks)
- **Entry points:** `vaultspec-rag` (CLI), `vaultspec-search-mcp` (MCP server)

### Key design decisions

#### GPU-only tests in CI

Standard GitHub Actions runners have no CUDA GPUs. The project already
separates tests via markers (`@pytest.mark.unit` vs `@pytest.mark.integration`).
The CI workflow should run only `pytest -m unit` — fast tests with no GPU, no
network, no disk I/O beyond fixtures. Integration, quality, performance, and
robustness tests run locally on GPU hardware or on a self-hosted runner if
added later. GitHub's GPU-enabled larger runners exist but cost ~$0.07/min and
require org-level setup — overkill for this project currently.

#### vaultspec-core dependency for CI and publishing

The current `pyproject.toml` has a local file path dependency:
`vaultspec-core @ file:///C:/projects/worktrees/main`. This is a
hard blocker for both CI runners and PyPI publishing (PyPI rejects path deps).

**Solution:** Use uv's source override pattern:

- `dependencies` list references the PyPI version: `"vaultspec-core>=0.1.0"`
- `[tool.uv.sources]` overrides with local path for development:
  `vaultspec-core = { path = "...", editable = true }`
- uv strips `[tool.uv.sources]` from built wheel metadata, so PyPI gets the
  clean version specifier

This is uv's recommended approach for local development with published deps.

#### Tag format and release-please configuration

Follow the same convention as vaultspec-core: `vaultspec-rag-vX.Y.Z` tags.
Configure release-please with `release-type: python`, `package-name: vaultspec-rag`. The config uses conventional commits to determine version
bumps: `feat:` → minor, `fix:` → patch, `perf:` → patch. Pre-1.0 versions
use `bump-minor-pre-major` and `bump-patch-for-minor-pre-major` to keep
bumps conservative.

#### Smoke tests for GPU-dependent package

The smoke test cannot exercise GPU inference on standard runners. Instead,
verify the non-GPU surface:

- Package importability (`import vaultspec_rag`)
- Version metadata via `importlib.metadata.version("vaultspec-rag")`
- Console script entry points registered (`vaultspec-rag`, `vaultspec-search-mcp`)
- CLI `--help` exits cleanly (typer app loads without GPU)
- MCP server `--help` exits cleanly

GPU-dependent imports (torch, sentence-transformers) will succeed as long as
they're in the wheel's dependency tree — the smoke test just verifies the
package structure is correct, not runtime inference.

#### PyPI trusted publishing

No API tokens needed. Setup:

- **PyPI side:** Add a "pending publisher" on pypi.org for the repo, workflow
  filename (`publish.yml`), and environment name (`pypi`).
- **GitHub side:** The publish job needs `permissions: id-token: write` and a
  GitHub environment named `pypi`. `uv publish` handles the OIDC token
  exchange automatically.

#### Justfile vs direct commands

vaultspec-core uses a justfile for task automation (e.g., `just dev lint python`).
vaultspec-rag does not have a justfile. Two options:

- **Option A:** Add a justfile mirroring vaultspec-core's pattern for
  consistency across the ecosystem.
- **Option B:** Use direct `uv run` commands in CI workflows. Simpler, fewer
  moving parts, no justfile dependency to install in CI.

**Recommendation:** Option B for now. The CI workflows should use direct
commands (`uv run ruff check src/`, `uv run pytest -m unit`). A justfile can
be added later if the project grows. This avoids the `just` dependency in CI
and keeps the workflows self-contained.

#### Runtime version discovery

Add `importlib.metadata` pattern to `src/vaultspec_rag/__init__.py`, matching
vaultspec-core:

```python
from importlib.metadata import PackageNotFoundError, version
try:
    __version__: str = version("vaultspec-rag")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"
```

### Workflow files needed

- **`.github/workflows/ci.yml`** — 4 jobs: workflow-lint, lint-and-type,
  tests, dependency-audit. No vault-audit (vaultspec-rag doesn't have
  `vault check` CLI). No lychee or pymarkdown (not in dev deps currently).

- **`.github/workflows/release-please.yml`** — Mirror vaultspec-core exactly,
  substituting package name.

- **`.github/workflows/publish.yml`** — Three-stage pipeline mirroring
  vaultspec-core: build, smoke-test, publish-pypi. Smoke test adapted for
  vaultspec-rag entry points.

- **`release-please-config.json`** — Same changelog sections, python
  release-type, package-name `vaultspec-rag`.

- **`.release-please-manifest.json`** — Initial version `"0.1.0"`.

- **`tests/smoke_check.py`** — Adapted from vaultspec-core: checks import,
  version metadata, entry points, CLI help, MCP help.

### Source changes needed

- `pyproject.toml`: Change vaultspec-core dep from file path to PyPI version,
  add `[tool.uv.sources]` override for local dev.
- `src/vaultspec_rag/__init__.py`: Add `__version__` via importlib.metadata.

### Risk assessment

- **Low risk:** CI lint/type/test jobs — mirrors pre-commit hooks, no new
  tooling.
- **Low risk:** release-please — well-established action, config is
  declarative.
- **Medium risk:** PyPI trusted publishing — requires manual PyPI config step.
  First publish may need the package registered on PyPI first.
- **Medium risk:** vaultspec-core dependency change — must verify the PyPI
  version is compatible. Currently published as 0.1.5+ on PyPI.
- **Low risk:** Smoke tests — conservative checks, no GPU dependency.
