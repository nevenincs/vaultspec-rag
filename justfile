set positional-arguments := false
set quiet := true
set shell := ["pwsh", "-NoProfile", "-File", "scripts/run-just-recipe.ps1"]
set windows-shell := ["pwsh.exe", "-NoProfile", "-File", "scripts/run-just-recipe.ps1"]

# Every recipe that merely *runs* a tool from the existing environment uses this
# runner. --no-sync keeps `uv run` from re-resolving and rebuilding the project
# into .venv, which fails on Windows whenever a resident process holds one of the
# console-script .exe shims open. Recipes whose purpose IS to touch the
# environment (uv sync / uv lock / uv build / uv audit) deliberately do not.
uvr := "uv run --no-sync"

export VIRTUAL_ENV := justfile_directory() + "/.venv"
export PATH := if os_family() == "windows" { VIRTUAL_ENV + "/Scripts;" + env_var('PATH') } else { VIRTUAL_ENV + "/bin:" + env_var('PATH') }

# List available recipes.
default:
  @just --list

# ===========================================================================
# readme-assets - regenerate the README terminal-render SVGs
#
# Requires the managed search server running and this repo's own index current.
# ===========================================================================

# Regenerate the README terminal-render SVGs.
readme-assets out_dir='assets':
  {{uvr}} python scripts/render_readme_assets.py {{out_dir}}

# ===========================================================================
# Development toolchain (linters, formatters, tests, builds).
#
# Nothing here exists in the shipped CLI.
#
# The split is by CONSEQUENCE, not by tool:
#
#   lint   GATES. Read-only, and a finding fails the build. Every threshold
#          sits at today's worst offender, so lint is green now and each
#          threshold can only ever be ratcheted DOWN.
#   fix    MUTATES. Everything automatically repairable, in one pass.
#   audit  ADVISORY. Reports and never fails, because each dimension yields
#          leads to confirm rather than verdicts. A dimension graduates into
#          `lint` once it reaches zero and can hold there.
#
# Verbs:
#   deps      dependency management (sync, upgrade, lock)
#   lint      gating static analysis (ruff, ty, complexity, size, citations, ...)
#   fix       auto-fix everything fixable (python, toml, vault)
#   audit     advisory scans (security, dead code, duplication, dependencies)
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
#   just lint size
#   just lint nesting
#   just fix
#   just fix python
#   just audit
#   just audit security
#   just audit dead-code
#   just test python
#   just build python
#   just health
# ===========================================================================

# ===========================================================================
# ci - full pipeline: lint → audit → vault check → test
# ===========================================================================

# Run lint, audit, vault validation, and tests.
ci:
  just lint all
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  just audit deps
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  {{uvr}} vaultspec-core vault check all
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  just test all
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Manage project dependencies.
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

# The complexity gate measures PRODUCTION code. The test tree is measured by
# `just audit complexity`, which reports without failing.
#
# The split is not a concession. The worst scores in this tree belong to guard
# tests that walk the AST of every module to prove a structural invariant;
# branch count and nesting are what those tests ARE, so gating them at a
# production threshold would price the guard out rather than simplify it.
# Production carries no such exemption and is gated at its current worst.
#
# Four of those guard blocks rank D against the `--max-absolute C` ceiling.
# That regression reached the default branch unseen: the markdown step fails
# earlier in the same CI job and aborts it, so the complexity step never ran.
# A gate behind a red gate is not a gate.
#
# NOTE: the switch body is one continuation-joined logical line, so it must
# never contain a `#` comment - PowerShell's `#` runs to the end of the joined
# line and silently swallows every case after it, closing braces included.

# `type` checks `tools` alongside the package. tools/ carries the release
# binary builder and the Scoop/Homebrew generators, where a break fails a
# release rather than a test. Both were outside this gate when a generator
# default naming a product that does not exist, and a builder invoked so it
# could not import its own package, reached main with CI green; `ty` finds
# either in one pass.

# Run static analysis and documentation checks.
lint target='all':
  switch ("{{target}}") { \
    "python" { {{uvr}} ruff check src tools ; break } \
    "type" { {{uvr}} python -m ty check src/vaultspec_rag tools ; break } \
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
      $env:PYTHONIOENCODING = "utf-8" ; \
      {{uvr}} complexipy src/vaultspec_rag ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      Push-Location src ; \
      {{uvr}} xenon vaultspec_rag --max-absolute C --max-modules C --max-average A -e "vaultspec_rag/tests/*" ; \
      $xenonExit = $LASTEXITCODE ; \
      if ($xenonExit -ne 0) { {{uvr}} radon cc vaultspec_rag -s -n C } \
      Pop-Location ; \
      exit $xenonExit \
    } \
    "nesting" { \
      {{uvr}} ruff check src --select PLR1702 --preview ; \
      break \
    } \
    "size" { \
      {{uvr}} pylint src/vaultspec_rag --rcfile=pyproject.toml --recursive=y --score=n ; \
      break \
    } \
    "type-strict" { \
      {{uvr}} basedpyright ; \
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
      {{uvr}} python tools/absolute_import_gate.py ; \
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
      just lint nesting ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } \
      just lint size ; \
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
      Write-Host "  targets: python type type-strict links toml markdown workflow complexity nesting size docs-version citations absolute-imports all" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

# Apply available formatters and automatic fixes.
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
#
# "deps" GATES: a published advisory against a pinned version is a verdict,
# not a lead, and the `ci` recipe stops on it.
#
# Every other target is ADVISORY and exits 0 even with findings. Each yields a
# lead to confirm rather than a verdict - vulture infers reachability it cannot
# always see, bandit reports this project's deliberate subprocess and
# filter-construction design alongside anything real, and deptry reports
# imports that resolve transitively, which is a supply-chain risk rather than a
# build break. The exit code is stated here because a check whose documented
# contract and actual exit code disagree is worse than no check: this repo
# shipped a CI step labelled "report-only" that gated, and a complexity gate
# that never ran because an earlier step aborted the job.
#
# Promote a dimension into `lint` once its finding count reaches zero and
# the gate can hold that line.
#
# NOTE: the switch body is one continuation-joined logical line, so it must
# never contain a `#` comment - PowerShell's `#` runs to the end of the joined
# line and silently swallows every case after it, closing braces included.

# Audit project dependencies and code quality.
audit target='all':
  switch ("{{target}}") { \
    "deps" { uv audit --locked --preview-features audit ; break } \
    "security" { {{uvr}} bandit -c pyproject.toml -r src/vaultspec_rag -x "src/vaultspec_rag/tests" -q ; exit 0 } \
    "dead-code" { {{uvr}} vulture ; exit 0 } \
    "dependencies" { {{uvr}} deptry src/vaultspec_rag ; exit 0 } \
    "duplication" { \
      if (Get-Command npx -ErrorAction SilentlyContinue) { \
        npx --yes jscpd@4 src/vaultspec_rag --min-lines 20 --min-tokens 70 --reporters console \
      } else { \
        Write-Host "npx not found - skipping duplication scan" -ForegroundColor Yellow \
      } \
      exit 0 \
    } \
    "complexity" { \
      $env:PYTHONIOENCODING = "utf-8" ; \
      {{uvr}} complexipy src/vaultspec_rag/tests --failed ; \
      Push-Location src ; \
      {{uvr}} xenon vaultspec_rag --max-absolute C --max-modules C --max-average A ; \
      Pop-Location ; \
      exit 0 \
    } \
    "all" { \
      Write-Host "=== dependency advisories ===" -ForegroundColor Cyan ; \
      just audit deps ; \
      Write-Host "=== security ===" -ForegroundColor Cyan ; \
      just audit security ; \
      Write-Host "=== dead code ===" -ForegroundColor Cyan ; \
      just audit dead-code ; \
      Write-Host "=== undeclared dependencies ===" -ForegroundColor Cyan ; \
      just audit dependencies ; \
      Write-Host "=== duplication ===" -ForegroundColor Cyan ; \
      just audit duplication ; \
      Write-Host "=== test-tree cognitive complexity ===" -ForegroundColor Cyan ; \
      just audit complexity ; \
      exit 0 \
    } \
    default { \
      Write-Host "unknown audit target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: deps security dead-code dependencies duplication complexity all" -ForegroundColor Red ; \
      Write-Host "  (the cross-dimension ranking report is 'just health')" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

# Excludes the exact marker set conftest.py's own pytest_runtestloop guard
# checks before requiring HF_TOKEN (_GPU_MARKERS | {"subprocess_gpu"} =
# integration/quality/performance/robustness/subprocess_gpu), plus "cuda" and
# "mps" for tests that target one real accelerator without the shared CUDA
# model fixtures. Excluding only
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
# "gpu" is the real-GPU CORRECTNESS tier, run serially on a CUDA host through
# one pytest invocation so the root-conftest coordinator owns the complete
# acknowledged borrower lease. "perf" is a separate quiet-machine-ONLY lane:
# its wall-clock latency/footprint assertions ARE the system under test, so a
# loaded machine fails them for reasons unrelated to a regression. It is
# excluded from "gpu" and runs only on explicit `just test perf`, never as a
# correctness gate.
#
# GPU tiers require a self-hosted runner image with the pinned,
# manifest-verified Qdrant binary used only by test-owned isolated children.
# The coordinator verifies that prerequisite read-only and refuses a
# missing binary; these recipes never provision Qdrant, preflight a GPU, or
# start a service.
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

# The "gpu" target runs TWO sequential selections, and that split is load
# bearing rather than tidiness. A resident-model tier holds its models for the
# length of the lane while each subprocess_gpu test spawns a service that loads
# its own set, and the combined footprint exceeds the card. Co-scheduled, the
# spawned service simply never becomes healthy - so the failure arrives as a
# health-poll timeout in whichever test drew the short straw, naming nothing
# about memory and pointing at code that is fine. The tier gate refuses a
# marker expression that can reach both at once; this is the recipe that
# satisfies it.
#
# Run project test suites.
test target='all':
  switch ("{{target}}") { \
    "python" { {{uvr}} pytest src/vaultspec_rag/tests/ -q --tb=short -n auto --dist loadfile -m "not (integration or quality or performance or robustness or subprocess_gpu or cuda or mps)" ; break } \
    "fast" { {{uvr}} pytest src/vaultspec_rag/tests/ -x -q --tb=short -m unit ; break } \
    "gpu" { \
      {{uvr}} pytest src/vaultspec_rag/tests/ -q --tb=short -m "(integration or quality or robustness or cuda) and not performance and not subprocess_gpu" ; \
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } ; \
      {{uvr}} pytest src/vaultspec_rag/tests/ -q --tb=short -m "subprocess_gpu" ; \
      break \
    } \
    "perf" { \
      {{uvr}} pytest src/vaultspec_rag/tests/ -q --tb=short -m "performance" ; \
      break \
    } \
    "mps" { \
      $env:PYTORCH_ENABLE_MPS_FALLBACK = "0" ; \
      {{uvr}} pytest src/vaultspec_rag/tests/integration/test_mps_backend.py -q --tb=short -m "mps" ; \
      break \
    } \
    "all" { just test python ; break } \
    default { \
      Write-Host "unknown test target: {{target}}" -ForegroundColor Red ; \
      Write-Host "  targets: python fast gpu perf mps all" -ForegroundColor Red ; \
      exit 1 \
    } \
  }

# Build Python distribution artifacts.
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

# Report code-health metrics; always exits zero.
health *args='':
  {{uvr}} python tools/health_report.py {{args}}

# ===========================================================================
# Release channels
#
# Both recipes deliberately bypass `{{uvr}}` and run under a bare
# `--no-project` interpreter, exactly as .github/workflows/binaries.yml does,
# so a local reproduction and CI execute the same command. Routing them
# through the project environment would put .venv between the maintainer and
# the artifact being reproduced.
# ===========================================================================

# Build the standalone PyApp binaries for one release tag and Rust target.
binaries tag rust_target outdir='dist-bin':
  uv run --no-project --python 3.13 -- python -m tools.binaries.build_pyapp --tag {{tag}} --target {{rust_target}} --outdir {{outdir}}

# `root` is REQUIRED and is a checkout of nevenincs/homebrew-tap - the account
# channel root, which is where these pointers live. It used to default to this
# repository, which quietly wrote into a local `bucket/` and `Formula/` that the
# release job never read; those copies sat at 0.4.11 while the live tap served
# 0.4.14. Point `checksums` at the release's SHA256SUMS.
#
# Regenerate and validate a release's channel pointers, as the release job does.
channels tag root checksums='dist-bin/SHA256SUMS':
  uv run --no-project --python 3.13 -- python -m tools.packaging.generate --tag {{tag}} --checksums {{checksums}} --root {{root}}
  uv run --no-project --python 3.13 -- python -m tools.packaging.validate --root {{root}}
