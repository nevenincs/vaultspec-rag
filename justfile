set positional-arguments := false
set shell := ["pwsh", "-NoProfile", "-Command"]
set windows-shell := ["pwsh.exe", "-NoProfile", "-Command"]

export VIRTUAL_ENV := justfile_directory() + "/.venv"
export PATH := if os_family() == "windows" { VIRTUAL_ENV + "/Scripts;" + env_var('PATH') } else { VIRTUAL_ENV + "/bin:" + env_var('PATH') }

default:
  @just --list

# ===========================================================================
# prod - pure 1:1 mirror of the vaultspec-rag Python CLI
#
# just prod [args...]  →  uv run vaultspec-rag [args...]
#
# Examples:
#   just prod index .
#   just prod search "query text"
#   just prod status
#   just prod server
# ===========================================================================

# prod - pure 1:1 mirror of the vaultspec-rag Python CLI
prod *args='':
  uv run vaultspec-rag {{args}}

# ===========================================================================
# dev - development toolchain (linters, formatters, tests, builds)
#
# Nothing here exists in the shipped CLI.
#
# Verbs:
#   deps      dependency management (sync, upgrade, lock)
#   lint      read-only static analysis (ruff, ty, taplo, mdformat, lychee, complexity, ...)
#   fix       auto-fix everything fixable (python, toml, vault)
#   audit     supply-chain / security checks (uv audit)
#   test      pytest
#   build     uv build
#   precommit pre-commit hook management (install, upgrade, run)
#   health    aggregate code-health report (complexity, LOC, MI, strict types)
#
# Examples:
#   just dev deps sync
#   just dev lint
#   just dev lint type
#   just dev lint complexity
#   just dev lint type-strict
#   just dev lint module-length
#   just dev fix
#   just dev fix python
#   just dev audit deps
#   just dev test python
#   just dev build python
#   just dev health
# ===========================================================================

# dev - development toolchain (linters, formatters, tests, builds)
dev target *args='':
  switch ("{{target}}") { \
    "deps" { just _dev-deps {{args}} ; break } \
    "lint" { just _dev-lint {{args}} ; break } \
    "fix" { just _dev-fix {{args}} ; break } \
    "audit" { just _dev-audit {{args}} ; break } \
    "test" { just _dev-test {{args}} ; break } \
    "build" { just _dev-build {{args}} ; break } \
    "precommit" { just _dev-precommit {{args}} ; break } \
    "health" { just _dev-health {{args}} ; break } \
    default { \
      Write-Host "unknown dev target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: deps lint fix audit test build precommit health" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

# ===========================================================================
# ci - full pipeline: lint → audit → vault check → test
# ===========================================================================

# ci - full pipeline: lint → audit → vault check → test
ci:
  just dev lint all
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  just dev audit deps
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  uv run vaultspec-core vault check all
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  just dev test all
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ---------------------------------------------------------------------------
#  Internal recipes (prefixed with _ to hide from --list)
# ---------------------------------------------------------------------------

_dev-deps target='sync':
  switch ("{{target}}") { \
    "sync" { uv sync --locked --group dev ; break } \
    "upgrade" { uv sync --upgrade --all-groups ; break } \
    "lock" { uv lock ; break } \
    "lock-upgrade" { uv lock --upgrade ; break } \
    default { \
      Write-Host "unknown dev deps target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: sync upgrade lock lock-upgrade" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

_dev-lint target='all':
  switch ("{{target}}") { \
    "python" { uv run ruff check src tools ; break } \
    "type" { uv run python -m ty check src/vaultspec_rag ; break } \
    "links" { \
      if (Get-Command lychee -ErrorAction SilentlyContinue) { \
        lychee --config lychee.toml README.md .vault .vaultspec \
      } elseif (Get-Command docker -ErrorAction SilentlyContinue) { \
        docker run --rm -v "$PWD`:/repo" -w /repo lycheeverse/lychee:latest --config /repo/lychee.toml README.md .vault .vaultspec \
      } else { \
        Write-Host "lychee not found and docker is unavailable" -ForegroundColor Red ; \
        exit 127 \
      } \
      break \
    } \
    "toml" { \
      if (Get-Command taplo -ErrorAction SilentlyContinue) { \
        taplo lint *.toml \
      } elseif (Get-Command docker -ErrorAction SilentlyContinue) { \
        docker run --rm -v "$PWD`:/repo" -w /repo tamasfe/taplo:0.9 lint *.toml \
      } else { \
        Write-Host "taplo not found and docker is unavailable" -ForegroundColor Red ; \
        exit 127 \
      } \
      break \
    } \
    "markdown" { \
      uv run mdformat --check README.md .vaultspec/ .vault/ ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      uv run pymarkdown --config .pymarkdown.json scan -r README.md .vaultspec/ .vault/ ; \
      break \
    } \
    "workflow" { \
      if (Get-Command actionlint -ErrorAction SilentlyContinue) { \
        actionlint \
      } elseif (Get-Command docker -ErrorAction SilentlyContinue) { \
        docker run --rm -v "$PWD`:/repo" -w /repo rhysd/actionlint:latest \
      } else { \
        Write-Host "actionlint not found and docker is unavailable" -ForegroundColor Red ; \
        exit 127 \
      } \
      break \
    } \
    "complexity" { \
      uv run python tools/complexity_gate.py ; \
      break \
    } \
    "type-strict" { \
      uv run basedpyright ; \
      break \
    } \
    "module-length" { \
      uv run python tools/module_length.py ; \
      break \
    } \
    "absolute-imports" { \
      if (Select-String -Path src\vaultspec_rag\*.py, src\vaultspec_rag\*\*.py -Pattern "^\s*from vaultspec_rag\." -Quiet -CaseSensitive) { \
        Write-Host "ABSOLUTE IMPORTS FOUND!" -ForegroundColor Red ; \
        Select-String -Path src\vaultspec_rag\*.py, src\vaultspec_rag\*\*.py -Pattern "^\s*from vaultspec_rag\." -CaseSensitive ; \
        exit 1 \
      } ; \
      break \
    } \
    "all" { \
      just _dev-lint python ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just _dev-lint type ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just _dev-lint links ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just _dev-lint toml ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just _dev-lint markdown ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just _dev-lint workflow ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just _dev-lint absolute-imports ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just _dev-lint complexity ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just _dev-lint module-length ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just _dev-lint type-strict ; \
      break \
    } \
    default { \
      Write-Host "unknown dev lint target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: python type type-strict links toml markdown workflow complexity module-length absolute-imports all" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

_dev-fix target='all':
  switch ("{{target}}") { \
    "python" { \
      uv run ruff format src tools ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      uv run ruff check --fix src tools ; \
      break \
    } \
    "toml" { \
      if (Get-Command taplo -ErrorAction SilentlyContinue) { \
        taplo fmt *.toml \
      } elseif (Get-Command docker -ErrorAction SilentlyContinue) { \
        docker run --rm -v "$PWD`:/repo" -w /repo tamasfe/taplo:0.9 fmt *.toml \
      } else { \
        Write-Host "taplo not found and docker is unavailable" -ForegroundColor Red ; \
        exit 127 \
      } \
      break \
    } \
    "markdown" { \
      uv run mdformat README.md .vaultspec/ .vault/ ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      uv run pymarkdown --config .pymarkdown.json fix -r README.md .vaultspec/ .vault/ ; \
      break \
    } \
    "vault" { \
      uv run vaultspec-core vault check all --fix ; \
      break \
    } \
    "all" { \
      just _dev-fix python ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just _dev-fix toml ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just _dev-fix markdown ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just _dev-fix vault ; \
      break \
    } \
    default { \
      Write-Host "unknown dev fix target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: python toml markdown vault all" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

# --ignore-until-fixed suppresses an advisory ONLY while no upstream fix exists,
# re-activating automatically once one ships. GHSA-rrmf-rvhw-rf47 (CVE-2025-3000)
# is a torch.jit.script memory-corruption advisory with no fix release; vaultspec-rag
# never calls torch.jit.script, and torch is the pinned GPU dependency, so it cannot
# be pinned away. Remove this when torch publishes a patched release.
_dev-audit target:
  switch ("{{target}}") { \
    "deps" { uv audit --locked --preview-features audit --ignore-until-fixed GHSA-rrmf-rvhw-rf47 ; break } \
    default { \
      Write-Host "unknown dev audit target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: deps" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

_dev-test target='all':
  switch ("{{target}}") { \
    "python" { uv run pytest src/vaultspec_rag/tests/ -x -q --tb=short -m unit ; break } \
    "all" { just _dev-test python ; break } \
    default { \
      Write-Host "unknown dev test target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: python all" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

_dev-build target:
  switch ("{{target}}") { \
    "python" { uv build ; break } \
    default { \
      Write-Host "unknown dev build target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: python" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

# Aggregate code-health report: worst offenders per dimension (cyclomatic,
# cognitive, function limits, module LOC, maintainability, strict types).
# Measurement only — always exits 0. Pass --fast to skip basedpyright.
_dev-health *args='':
  uv run python tools/health_report.py {{args}}

_dev-precommit target='run':
  switch ("{{target}}") { \
    "install" { uv run prek install ; break } \
    "upgrade" { uv run prek auto-update ; break } \
    "run" { uv run prek run --all-files ; break } \
    default { \
      Write-Host "unknown dev precommit target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: install upgrade run" -ForegroundColor Red ; \
      exit 1 \
    } \
  }
