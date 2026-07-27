set positional-arguments := false
set shell := ["pwsh", "-NoProfile", "-Command"]
set windows-shell := ["pwsh.exe", "-NoProfile", "-Command"]

# Every recipe that merely *runs* a tool from the existing environment uses this
# runner. --no-sync keeps `uv run` from re-resolving and rebuilding the project
# into .venv, which fails on Windows whenever a resident process holds one of the
# console-script .exe shims open. Recipes whose purpose IS to touch the
# environment (uv sync / uv lock / uv build / uv audit) deliberately do not.
uvr := "uv run --no-sync"

export VIRTUAL_ENV := justfile_directory() + "/.venv"
export PATH := if os_family() == "windows" { VIRTUAL_ENV + "/Scripts;" + env_var('PATH') } else { VIRTUAL_ENV + "/bin:" + env_var('PATH') }

default:
  @just --list

# ===========================================================================
# readme-assets - regenerate the README terminal-render SVGs
#
# Requires the managed search server running and this repo's own index current.
# ===========================================================================

# readme-assets - regenerate the README terminal-render SVGs
readme-assets out_dir='assets':
  {{uvr}} python scripts/render_readme_assets.py {{out_dir}}

# ===========================================================================
# Verbs:
#   deps      dependency management (sync, upgrade, lock)
#   lint      read-only static analysis (ruff, ty, taplo, mdformat, lychee, complexity, ...)
#   fix       auto-fix everything fixable (python, toml, vault)
#   audit     supply-chain / security checks (uv audit)
#   test      pytest
#   build     uv build
#   health    aggregate code-health report (complexity, LOC, MI, strict types)
#
# Examples:
#   just deps sync
#   just lint
#   just lint type
#   just lint complexity
#   just lint type-strict
#   just lint module-length
#   just fix
#   just fix python
#   just audit deps
#   just test python
#   just build python
#   just health
# ===========================================================================

# ===========================================================================
# ci - full pipeline: lint → audit → vault check → test
# ===========================================================================

# ci - full pipeline: lint → audit → vault check → test
ci:
  just lint all
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  just audit deps
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  {{uvr}} vaultspec-core vault check all
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  just test all
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

deps target='sync':
  switch ("{{target}}") { \
    "sync" { uv sync --locked --group dev ; break } \
    "upgrade" { uv sync --upgrade --all-groups ; break } \
    "lock" { uv lock ; break } \
    "lock-upgrade" { uv lock --upgrade ; break } \
    default { \
      Write-Host "unknown deps target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: sync upgrade lock lock-upgrade" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

lint target='all':
  switch ("{{target}}") { \
    "python" { {{uvr}} ruff check src tools ; break } \
    "type" { {{uvr}} python -m ty check src/vaultspec_rag ; break } \
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
      {{uvr}} mdformat --check README.md .vaultspec/ .vault/ ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      {{uvr}} pymarkdown --config .pymarkdown.json scan -r README.md .vaultspec/ .vault/ ; \
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
      {{uvr}} python tools/complexity_gate.py ; \
      break \
    } \
    "type-strict" { \
      {{uvr}} basedpyright ; \
      break \
    } \
    "module-length" { \
      {{uvr}} python tools/module_length.py ; \
      break \
    } \
    "docs-version" { \
      {{uvr}} python tools/check_docs_version.py ; \
      break \
    } \
    "citations" { \
      {{uvr}} python tools/citation_gate.py ; \
      break \
    } \
    "absolute-imports" { \
      $absHits = Get-ChildItem -Recurse -Path src/vaultspec_rag -Filter *.py | Select-String -Pattern "^\s*from vaultspec_rag\." -CaseSensitive | Where-Object { $_.Line -notmatch "absolute-import-ok" } ; \
      if ($absHits) { \
        Write-Host "ABSOLUTE IMPORTS FOUND!" -ForegroundColor Red ; \
        $absHits | ForEach-Object { Write-Host "$($_.Path):$($_.LineNumber):$($_.Line)" } ; \
        exit 1 \
      } ; \
      break \
    } \
    "all" { \
      just lint python ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just lint type ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just lint links ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just lint toml ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just lint markdown ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just lint workflow ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just lint absolute-imports ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just lint complexity ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just lint module-length ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just lint docs-version ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just lint citations ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just lint type-strict ; \
      break \
    } \
    default { \
      Write-Host "unknown lint target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: python type type-strict links toml markdown workflow complexity module-length docs-version citations absolute-imports all" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

fix target='all':
  switch ("{{target}}") { \
    "python" { \
      {{uvr}} ruff format src tools ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      {{uvr}} ruff check --fix src tools ; \
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
      {{uvr}} mdformat README.md .vaultspec/ .vault/ ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      {{uvr}} pymarkdown --config .pymarkdown.json fix -r README.md .vaultspec/ .vault/ ; \
      break \
    } \
    "vault" { \
      {{uvr}} vaultspec-core vault check all --fix ; \
      break \
    } \
    "all" { \
      just fix python ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just fix toml ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just fix markdown ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just fix vault ; \
      break \
    } \
    default { \
      Write-Host "unknown fix target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: python toml markdown vault all" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

# The audit runs with no suppressions: torch 2.13.0 resolved GHSA-rrmf-rvhw-rf47
# (CVE-2025-3000) and lifted the transitive setuptools pin past the PYSEC-2026-3447
# fix (83.0.0). A future advisory with no upstream fix should be suppressed with
# --ignore-until-fixed (self-expiring), never a bare --ignore without a comment.
audit target:
  switch ("{{target}}") { \
    "deps" { uv audit --locked --preview-features audit ; break } \
    default { \
      Write-Host "unknown audit target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: deps" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

# Excludes the exact marker set conftest.py's own pytest_runtestloop guard
# checks before requiring HF_TOKEN (_GPU_MARKERS | {"subprocess_gpu"} =
# integration/quality/performance/robustness/subprocess_gpu), plus "cuda" for
# tests that need a real GPU but carry no HF-auth dependency. Excluding only
# "integration" here let a quality/performance/robustness/subprocess_gpu/cuda
# test slip through gateless and hard-abort this recipe on a GPU-less runner;
# matching conftest's own needs-real-infra set here is the durable fix so a
# newly-added GPU-marked test is excluded automatically, with no marker to
# remember to also duplicate onto "integration". Every test now declares a
# tier, enforced at collection time by the root conftest, so this exclusion
# expression and "-m unit" select the same population; the exclusion is kept
# because it stays correct when a new slow tier is added, where "-m unit" would
# have to be taught about it. No -x here: a repo-health recipe must report every
# failure, not stop at the first one.
#
# "gpu" is the real-GPU CORRECTNESS tier, run on a CUDA host, as two
# invocations: the serialized integration/quality/robustness/cuda tests share
# the in-process gpu_lock, but subprocess_gpu tests spawn their own
# model-loading process whose VRAM is outside that lock and must not
# co-schedule with the first group on a 16 GB card. "perf" is a separate
# quiet-machine-ONLY lane: the performance tests' wall-clock latency/footprint
# assertions ARE the system under test, so a loaded machine fails them for
# reasons unrelated to a regression - they are excluded from "gpu" and run
# only on explicit `just test perf`, never as a correctness gate.
#
# Only "python" runs parallel. `-n auto` resolves to PHYSICAL cores when psutil
# is importable, which it always is here (it is a runtime dependency), and
# `--dist loadfile` keeps a module's tests on one worker so module-scoped state
# and the ports a file reserves stay private to it. The tier is dominated by
# subprocess spawns and socket waits rather than by CPU, so it parallelises
# well: 666s to 162s on a 12-core host. The other lanes must NOT get this. "gpu"
# serialises on the in-process gpu_lock and a 16 GB card, and "perf" asserts
# wall-clock latency, so on both a second worker changes the answer rather than
# just the runtime.
# NOTE: this recipe body is one continuation-
# joined logical line for `just`/PowerShell, so it must never contain a `#`
# comment inside the switch - PowerShell's `#` runs to the end of the joined
# line and silently swallows every case after it, including the closing
# braces (this broke every target, not just "gpu", the last time it happened).
test target='all':
  switch ("{{target}}") { \
    "python" { {{uvr}} pytest src/vaultspec_rag/tests/ -q --tb=short -n auto --dist loadfile -m "not (integration or quality or performance or robustness or subprocess_gpu or cuda)" ; break } \
    "fast" { {{uvr}} pytest src/vaultspec_rag/tests/ -x -q --tb=short -m unit ; break } \
    "gpu" { \
      {{uvr}} pytest src/vaultspec_rag/tests/ -q --tb=short -m "(integration or quality or robustness or cuda) and not subprocess_gpu" ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      {{uvr}} pytest src/vaultspec_rag/tests/ -q --tb=short -m "subprocess_gpu" ; \
      break \
    } \
    "perf" { {{uvr}} pytest src/vaultspec_rag/tests/ -q --tb=short -m "performance" ; break } \
    "all" { just test python ; break } \
    default { \
      Write-Host "unknown test target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: python fast gpu perf all" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

build target:
  switch ("{{target}}") { \
    "python" { uv build ; break } \
    default { \
      Write-Host "unknown build target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: python" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

# Aggregate code-health report: worst offenders per dimension (cyclomatic,
# cognitive, function limits, module LOC, maintainability, strict types).
# Measurement only — always exits 0. Pass --fast to skip basedpyright.
health *args='':
  {{uvr}} python tools/health_report.py {{args}}
