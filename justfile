# ===========================================================================
#  vaultspec-rag development harness
#
#  Every entry point is a top-level verb; behaviour within a verb is selected
#  by a `target` argument - `just lint type`, `just test fast`, `just fix
#  markdown`. Run `just` for the annotated recipe list, and `just <verb> help`
#  (or any unrecognised target) for that verb's targets with descriptions.
#
#  PLATFORM AGNOSTIC BY CONSTRUCTION. Every recipe body below is a single
#  command with no shell branching, no pipes, no conditionals, and no `sh`
#  versus PowerShell dialect. All of the logic - target dispatch, step
#  chaining, tool-or-Docker fallback, advisory-versus-gating exit codes, the
#  working directory the complexity tools need - lives in the stdlib-only
#  modules under `dev/`, which therefore behave identically on every platform.
#  There is no shell script backing this file. To change what a target runs,
#  edit `dev/toolchain.py`, which is the single declarative source of truth for
#  the whole toolchain, and from which the help text is DERIVED, so a target
#  cannot exist undocumented.
#
#  This replaced roughly 350 lines of backslash-joined PowerShell `switch`
#  blocks executed through a bespoke `scripts/run-just-recipe.ps1` shim. Those
#  blocks carried a hazard their own comments warned about three separate
#  times: because a `switch` body was one continuation-joined logical line, a
#  `#` anywhere inside it ran to the end of that line and silently swallowed
#  every remaining case, closing braces included.
#
#  The verbs split by CONSEQUENCE, not by tool:
#
#    deps   MUTATES the environment.
#    lint   GATES.    Read-only, and a finding fails the build.
#    fix    MUTATES.  Everything automatically repairable, in one pass.
#    audit  Only `deps` gates. Every other target is advisory and exits 0
#           even with findings, because each yields a lead to confirm.
#    test   GATES.    `just test help` states what each lane proves, and what
#           the `all` aggregate deliberately leaves out.
#    health MEASURES. Always exits 0.
# ===========================================================================

set positional-arguments := false
set quiet := true

# just defaults to `sh -cu` on every platform, which on Windows means a Git Bash
# `sh.exe` that is only on PATH for some Git for Windows install options. This
# names the one interpreter every Windows machine is guaranteed to have. It is a
# shell DECLARATION, not platform-specific logic: because each recipe body below
# is a single command with no shell syntax, `cmd` and `sh` execute all of them
# identically, and there is no second dialect of anything to maintain.
set windows-shell := ["cmd.exe", "/c"]

# Every recipe that merely *uses* the environment goes through `uv run
# --no-sync`. Skipping the sync keeps `uv run` from re-resolving and rebuilding
# the project into `.venv`, which fails on Windows whenever a resident process
# - an MCP server, an editor, another agent's session - holds one of the
# console-script executables open. The recipes whose purpose IS to change the
# environment call `uv` directly, inside `dev/`.
dev := "uv run --no-sync python -m dev"

# List available recipes.
default:
    @just --list

# ===========================================================================
#  Toolchain verbs
# ===========================================================================

# Manage project dependencies and the lockfile.
deps target='sync':
    {{dev}} deps {{target}}

# Run gating static analysis: style, types, complexity, links, and markdown.
lint target='all':
    {{dev}} lint {{target}}

# Apply every available formatter and automatic fix.
fix target='all':
    {{dev}} fix {{target}}

# Audit dependencies and code quality; only 'deps' gates.
audit target='all':
    {{dev}} audit {{target}}

# Run the project test suites.
test target='all':
    {{dev}} test {{target}}

# Build the Python distribution artifacts.
build target='all':
    {{dev}} build {{target}}

# MEASUREMENT ONLY - always exits 0. Composes the gates rather than
# re-implementing any threshold, so the report and the gate cannot disagree.

# Rank the worst offenders across every code-health dimension.
health target='report':
    {{dev}} health {{target}}

# ===========================================================================
#  README assets
#
#  Requires the managed search server running and this repo's own index current.
# ===========================================================================

# Regenerate the README terminal-render SVGs.
readme-assets out_dir='assets':
    uv run --no-sync python scripts/render_readme_assets.py {{out_dir}}

# ===========================================================================
#  Release channels
#
#  Both recipes deliberately bypass the project environment and run under a
#  bare `--no-project` interpreter, exactly as .github/workflows/binaries.yml
#  does, so a local reproduction and CI execute the same command. Routing them
#  through .venv would put the environment between the maintainer and the
#  artifact being reproduced.
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

# ===========================================================================
#  Aggregate pipeline
# ===========================================================================

# Run the full local gate: lint, dependency audit, vault checks, tests.
ci:
    {{dev}} ci all
