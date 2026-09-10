# ===========================================================================
#  vaultspec-rag development harness
#
#  Every entry point is a FLAT HYPHENATED recipe named `<verb>-<thing>` -
#  `just check-type`, `just test-fast`, `just fix-markdown`. There is no
#  `target` argument anywhere: the thing a recipe acts on is part of its name,
#  so `just --list` is the complete surface and tab completion reaches every
#  one of them. Run `just` for the annotated recipe list, grouped by
#  CONSEQUENCE.
#
#  PLATFORM AGNOSTIC BY CONSTRUCTION. Every recipe body below is a single
#  command with no shell branching, no pipes, no conditionals, and no `sh`
#  versus PowerShell dialect. All of the logic - step chaining, tool-or-Docker
#  fallback, advisory-versus-gating exit codes, the working directory the
#  complexity tools need - lives in the stdlib-only modules under `dev/`, which
#  therefore behave identically on every platform. There is no shell script
#  backing this file. To change what a recipe runs, edit `dev/toolchain.py`,
#  which is the single declarative source of truth for the whole toolchain, and
#  from which the help text is DERIVED, so a target cannot exist undocumented.
#
#  This replaced roughly 350 lines of backslash-joined PowerShell `switch`
#  blocks executed through a bespoke `scripts/run-just-recipe.ps1` shim. Those
#  blocks carried a hazard their own comments warned about three separate
#  times: because a `switch` body was one continuation-joined logical line, a
#  `#` anywhere inside it ran to the end of that line and silently swallowed
#  every remaining case, closing braces included.
#
#  The GROUPS split by CONSEQUENCE, not by tool. The taxonomy is a closed set
#  of ten, identical in every repository:
#
#    setup    Provisioning and dependency resolution. MUTATES the environment.
#    dev      Day-to-day operations on this checkout that are not gates.
#    check    GATES.    Read-only, and a finding fails the build.
#    fix      MUTATES.  Everything automatically repairable, in one pass.
#    audit    ADVISORY, and exits 0 even with findings, because each yields a
#             lead to confirm. `audit-deps` is the ONE exception: a published
#             advisory against a pinned version is a verdict, so it gates.
#    build    Produces artifacts from a plain checkout.
#    release  Actions that need a published tag.
#    docs     Regenerates committed documentation assets.
#    test     GATES.
#    meta     The recipe list and the composed pipeline.
#
#  The `health-*` recipes MEASURE and always exit 0; they are filed under
#  `audit` because measurement without a verdict is what that group is.
# ===========================================================================

set quiet := true

# Requires just >= 1.38 (`set working-directory`, native modules, `[doc]`/`[group]`).
#
# just defaults to `sh -cu` on every platform, which on Windows means a Git Bash
# `sh.exe` that is only on PATH for some Git for Windows install options. This
# names the one interpreter every Windows machine is guaranteed to have.
#
# `cmd` is chosen for EXIT-CODE FIDELITY, not familiarity. It forwards a native
# command's status verbatim; `pwsh -Command` and `powershell -Command` collapse
# every non-zero status onto 1, which would erase this harness's own exit codes
# and destroy the advisory-versus-gating split the recipe groups are built on.
# cmd's weaknesses - `%VAR%` expansion and no single-quote literal - cost
# nothing here, because every recipe body below is a single command with no
# shell syntax and no recipe body contains either character.
set windows-shell := ["cmd.exe", "/c"]

# Every recipe that merely *uses* the environment goes through `uv run
# --no-sync`. Skipping the sync keeps `uv run` from re-resolving and rebuilding
# the project into `.venv`, which fails on Windows whenever a resident process
# - an MCP server, an editor, another agent's session - holds one of the
# console-script executables open. The recipes whose purpose IS to change the
# environment call `uv` directly, inside `dev/`.
dev := "uv run --no-sync python -m dev"

# List every recipe, grouped by consequence.
[group('meta')]
default:
    @just --list

# ===========================================================================
#  setup
#
#  These recipes deliberately do NOT go through `uv run --no-sync`: changing
#  the environment is their whole purpose.
# ===========================================================================

# `init` is the one command a fresh worktree needs, and the command git
# tooling and the worktree provisioner call after creating one. It cannot
# route through `{{dev}}`, which presumes the environment `init` is
# responsible for creating; it runs on an ephemeral interpreter instead, and
# `dev/init/` is stdlib-only for exactly that reason.
#
# Idempotent: a second run costs a stamp comparison and touches nothing.
# `just init-check` verifies without mutating, exiting 3 when the worktree is
# not initialized, which is what a hook or a provisioner calls. Set
# VAULTSPEC_INIT_JSON=1 for an NDJSON event stream, VAULTSPEC_INIT_FORCE=1 to
# ignore the stamp. Every run writes `.venv/init-report.json`.
#
# The phases run in dependency order and stop at the first failure: unlike the
# `-all` aggregates, which chain independent inspectors and run every one,
# these build one artifact, and `init-tools` runs executables out of the
# environment `init-python` creates. The report still lists every phase, with
# the ones that were not attempted naming the failure that stopped them.

# Initialize a fresh clone or worktree: dependencies, framework, hooks, .env.
[group('setup')]
init:
    uv run --no-project --python 3.13.14 -- python -m dev.init all

# Resolve the locked Python development toolchain into .venv.
[group('setup')]
init-python:
    uv run --no-project --python 3.13.14 -- python -m dev.init python

# Restore the pinned Node dependency graph. A no-op in this repository.
[group('setup')]
init-node:
    uv run --no-project --python 3.13.14 -- python -m dev.init node

# Enroll the Vaultspec framework and install the committed git hooks.
[group('setup')]
init-tools:
    uv run --no-project --python 3.13.14 -- python -m dev.init tools

# Report whether this worktree is initialized. Mutates nothing; exits 3 if not.
[group('setup')]
init-check:
    uv run --no-project --python 3.13.14 -- python -m dev.init check

# Resolve the development environment from the lock.
[group('setup')]
deps-sync:
    {{dev}} deps sync

# Re-resolve every group to the newest permitted versions.
[group('setup')]
deps-upgrade:
    {{dev}} deps upgrade

# Refresh the lockfile without changing the environment.
[group('setup')]
deps-lock:
    {{dev}} deps lock

# Refresh the lockfile, raising pins where permitted.
[group('setup')]
deps-lock-upgrade:
    {{dev}} deps lock-upgrade

# ===========================================================================
#  check - GATES. Read-only, and a finding fails the build.
# ===========================================================================

# Check style and formatting.
[group('check')]
check-python:
    {{dev}} lint python

# `check-type` checks `tools` alongside the package. tools/ carries the release
# binary builder and the Scoop/Homebrew generators, where a break fails a
# release rather than a test. Both were outside this gate when a generator
# default naming a product that does not exist, and a builder invoked so it
# could not import its own package, reached main with CI green.

# Check types across the package and the release tooling.
[group('check')]
check-type:
    {{dev}} lint type

# Check types under the strict profile.
[group('check')]
check-type-strict:
    {{dev}} lint type-strict

# Check every documentation link resolves.
[group('check')]
check-links:
    {{dev}} lint links

# Check TOML formatting.
[group('check')]
check-toml:
    {{dev}} lint toml

# Check markdown formatting and structure.
[group('check')]
check-markdown:
    {{dev}} lint markdown

# Check the GitHub Actions workflows.
[group('check')]
check-workflow:
    {{dev}} lint workflow

# The complexity gate measures PRODUCTION code; the test tree is measured by
# `audit-complexity`, which reports without failing. That split is not a
# concession: the worst scores in this tree belong to guard tests that walk the
# AST of every module to prove a structural invariant, and branch count and
# nesting are what those tests ARE, so gating them at a production threshold
# would price the guard out rather than simplify it.

# Gate production cyclomatic and cognitive complexity.
[group('check')]
check-complexity:
    {{dev}} lint complexity

# Gate nesting depth.
[group('check')]
check-nesting:
    {{dev}} lint nesting

# Gate module length and class design limits.
[group('check')]
check-size:
    {{dev}} lint size

# Check the documented version matches the packaged one.
[group('check')]
check-docs-version:
    {{dev}} lint docs-version

# Check every citation resolves to a real source.
[group('check')]
check-citations:
    {{dev}} lint citations

# Check manual invocation lanes, version examples, and PATH checks.
[group('check')]
check-docs-conventions:
    {{dev}} lint docs-conventions

# Check the package uses absolute imports throughout.
[group('check')]
check-absolute-imports:
    {{dev}} lint absolute-imports

# Check the vault's structure, frontmatter and links.
[group('check')]
check-vault:
    {{dev}} lint vault

# AGGREGATES RUN EVERY STEP and exit with the first non-zero status; they do
# not stop at the first failure. An aggregate is asked for a complete picture,
# and fail-fast costs a CI round-trip per defect. That is why this dispatches
# into `dev/` rather than listing its members as just dependencies: a
# dependency chain cannot express run-all-then-report. The membership lives in
# `dev/toolchain.py` as references to the same targets the individual recipes
# above run, so this aggregate and those gates cannot disagree.

# Run every gating dimension.
[group('check')]
check-all:
    {{dev}} lint all

# ===========================================================================
#  fix - MUTATES. Everything automatically repairable, in one pass.
# ===========================================================================

# Format and auto-fix Python.
[group('fix')]
fix-python:
    {{dev}} fix python

# Format TOML.
[group('fix')]
fix-toml:
    {{dev}} fix toml

# Format and repair markdown.
[group('fix')]
fix-markdown:
    {{dev}} fix markdown

# Reconcile and format this checkout's own .vault/ corpus.
[group('fix')]
fix-vault:
    {{dev}} fix vault

# Apply every automatic fix, in one pass.
[group('fix')]
fix-all:
    {{dev}} fix all

# ===========================================================================
#  audit - ADVISORY, except `audit-deps`, which gates.
#
#  `audit-deps` GATES: a published advisory against a pinned version is a
#  verdict, not a lead. Every other recipe here is ADVISORY and exits 0 even
#  with findings, because each yields a lead to confirm - vulture infers
#  reachability it cannot always see, bandit reports this project's deliberate
#  subprocess design alongside anything real, and deptry reports imports that
#  resolve transitively. Promote a dimension into `check` once its finding
#  count reaches zero and the gate can hold that line.
# ===========================================================================

# Gate on published advisories against the locked versions.
[group('audit')]
audit-deps:
    {{dev}} audit deps

# Scan for insecure patterns; advisory, exits 0.
[group('audit')]
audit-security:
    {{dev}} audit security

# Report unreachable code; advisory, exits 0.
[group('audit')]
audit-dead-code:
    {{dev}} audit dead-code

# Report undeclared and unused dependencies; advisory, exits 0.
[group('audit')]
audit-dependencies:
    {{dev}} audit dependencies

# Report copy-paste clones; advisory, exits 0.
[group('audit')]
audit-duplication:
    {{dev}} audit duplication

# Report test-tree cognitive and cyclomatic complexity; advisory, exits 0.
[group('audit')]
audit-complexity:
    {{dev}} audit complexity

# `audit-all` is every ADVISORY dimension. `audit-deps` is not among them: it
# GATES, so a report that cannot fail is the wrong place for it, and running
# it there took the same published-advisory query twice for one commit.

# Report every advisory dimension; one red never hides the rest.
[group('audit')]
audit-all:
    {{dev}} audit all

# MEASUREMENT ONLY - always exits 0. Composes the gates rather than
# re-implementing any threshold, so the report and the gate cannot disagree.

# Rank the worst offenders across every code-health dimension.
[group('audit')]
health-report:
    {{dev}} health report

# The same report, skipping the strict type check.
[group('audit')]
health-fast:
    {{dev}} health fast

# ===========================================================================
#  test - GATES.
# ===========================================================================

# Run every lane that needs no accelerator, in parallel.
[group('test')]
test-python:
    {{dev}} test python

# Run the unit tier only, stopping at the first failure.
[group('test')]
test-fast:
    {{dev}} test fast

# Run the real-GPU correctness tiers, serially, on a CUDA host.
[group('test')]
test-gpu:
    {{dev}} test gpu

# Run the latency and footprint lane; quiet machines only.
[group('test')]
test-perf:
    {{dev}} test perf

# Run the Apple-silicon backend lane with the fallback disabled.
[group('test')]
test-mps:
    {{dev}} test mps

# Run the environment-provisioning and readiness holders.
[group('test')]
test-provisioning:
    {{dev}} test provisioning

# `test-all` runs EVERY lane: python, gpu, mps and perf. The three
# hardware-gated lanes are probed first and, where the host cannot run one,
# reported by name as SKIPPED with the reason - they are never silently
# omitted. It exits non-zero when every lane was skipped, because a run that
# proved nothing must not read as a pass. `test-fast` and `test-provisioning`
# are selections WITHIN the python lane rather than lanes of their own, so
# `test-all` does not re-run them.

# Run every lane; gated lanes are reported skipped, never dropped.
[group('test')]
test-all:
    {{dev}} test all

# ===========================================================================
#  build
# ===========================================================================

# Build the wheel and sdist.
[group('build')]
build-python:
    {{dev}} build python

# `build-all` builds everything this repository produces from a plain checkout,
# which is the wheel and the sdist. The standalone PyApp binaries and the
# Scoop/Homebrew channel pointers are NOT part of it: both need a released tag
# and a Rust target that only exist at release time, so they stay on their own
# recipes in the `release` group rather than being left unmentioned.

# Build every artifact producible without a release tag.
[group('build')]
build-all:
    {{dev}} build all

# ===========================================================================
#  docs
#
#  Requires the managed search server running and this repo's own index current.
# ===========================================================================

# Regenerate the README terminal-render SVGs.
[group('docs')]
docs-readme-assets out_dir='assets':
    uv run --no-sync python scripts/render_readme_assets.py {{out_dir}}

# Regenerate the CLI reference from the live command surface.
[group('docs')]
docs-cli:
    uv run --no-sync python -m dev.generate_cli_reference

# Check that the generated CLI reference is current.
[group('check')]
check-docs-cli:
    {{dev}} lint docs-cli

# ===========================================================================
#  release
#
#  Both recipes deliberately bypass the project environment and run under a
#  bare `--no-project` interpreter, exactly as .github/workflows/binaries.yml
#  does, so a local reproduction and CI execute the same command. Routing them
#  through .venv would put the environment between the maintainer and the
#  artifact being reproduced.
# ===========================================================================

# Build the standalone PyApp binaries for one release tag and Rust target.
[group('release')]
release-binaries tag rust_target outdir='dist-bin':
    uv run --no-project --python 3.13 -- python -m tools.binaries.build_pyapp --tag {{tag}} --target {{rust_target}} --outdir {{outdir}}

# `root` is REQUIRED and is a checkout of nevenincs/homebrew-tap - the account
# channel root, which is where these pointers live. It used to default to this
# repository, which quietly wrote into a local `bucket/` and `Formula/` that the
# release job never read; those copies sat at 0.4.11 while the live tap served
# 0.4.14. Point `checksums` at the release's SHA256SUMS.

# Regenerate and validate a release's channel pointers, as the release job does.
[group('release')]
release-channels tag root checksums='dist-bin/SHA256SUMS':
    uv run --no-project --python 3.13 -- python -m tools.packaging.generate --tag {{tag}} --checksums {{checksums}} --root {{root}}
    uv run --no-project --python 3.13 -- python -m tools.packaging.validate --root {{root}}

# ===========================================================================
#  meta
# ===========================================================================

# Run the full local gate: static analysis, dependency audit, vault, tests.
[group('check')]
ci:
    {{dev}} ci all
